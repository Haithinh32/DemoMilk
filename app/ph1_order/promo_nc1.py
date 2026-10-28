"""PH1 NC1 – Đề xuất và đánh giá hiệu quả khuyến mãi (mục 3.2.12).

- Ước lượng uplift theo đơn vị i = vùng × nhóm điểm bán bằng T-learner (hai mô hình: có KM / không KM).
- Lợi nhuận tăng thêm(i,m) = Biên LN × giá × [Ŷ1 − Ŷ0 − Sụt sau KM] − Chi phí KM; chọn bằng bài toán cái túi
  nhiều lựa chọn trong ngân sách.
- Sau chương trình: ROI thật bằng so sánh với đơn vị đối chứng (difference-in-differences).
Hệ thống chỉ đề xuất; Giám đốc KD duyệt qua CN1 như mọi chương trình.
"""
import random
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.db import new_id
from app.errors import DomainError, NotFound
from app.ph0_platform import ai_engine, audit
from app.ph0_platform.identity import PKD, User, require_role
from app.ph0_platform.models import SanPham
from app.ph1_order.contracts import list_price
from app.ph1_order.models import ChuongTrinhKM, DanhGiaKM, PhuongAnKM
from app.ph4_sales.models import DiemBan, DwBanHangNgay

SO_NGAY_SAU_KM = 14
TY_LE_DOI_CHUNG = 0.1
TY_LE_SUT_MAC_DINH = 0.2


def _plain(x):
    """Đổi kiểu NumPy sang kiểu Python để lưu cột JSON."""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x


def _unit_daily(s, ma_sp: str) -> tuple[pd.DataFrame, dict[str, int]]:
    rows = s.execute(select(DwBanHangNgay.ngay, DwBanHangNgay.vung, DwBanHangNgay.nhom, DwBanHangNgay.so_luong,
                            DwBanHangNgay.muc_giam).where(DwBanHangNgay.ma_sp == ma_sp)).all()
    df = pd.DataFrame(rows, columns=["ngay", "vung", "nhom", "q", "m"])
    sizes = defaultdict(int)
    for v, n in s.execute(select(DiemBan.vung, DiemBan.nhom)).all():
        sizes[f"{v}|{n}"] += 1
    if df.empty:
        return df, dict(sizes)
    df["unit"] = df["vung"] + "|" + df["nhom"]
    g = df.groupby(["unit", "ngay"]).agg(q=("q", "sum"), m=("m", "max")).reset_index()
    days = pd.date_range(g["ngay"].min(), g["ngay"].max(), freq="D").date
    full = pd.MultiIndex.from_product([sorted(g["unit"].unique()), days], names=["unit", "ngay"])
    g = g.set_index(["unit", "ngay"]).reindex(full, fill_value=0).reset_index()
    g["q_per_outlet"] = g.apply(lambda r: r["q"] / max(1, sizes[r["unit"]]), axis=1)
    return g, dict(sizes)


def _units_of(km: ChuongTrinhKM, sizes: dict) -> list[str]:
    if km.muc_giam_theo_don_vi:
        return list(km.muc_giam_theo_don_vi)
    return [u for u in sizes if not km.vung_ap_dung or u.split("|")[0] in km.vung_ap_dung]


def _did(g: pd.DataFrame, treated: list[str], control: list[str], tu: date, den: date) -> dict:
    """Chênh lệch 'sau trừ trước' của nhóm có KM trừ chênh lệch tương ứng của nhóm đối chứng, theo điểm bán/ngày."""
    D = (den - tu).days + 1
    pre = (g["ngay"] >= tu - timedelta(days=D)) & (g["ngay"] < tu)
    dur = (g["ngay"] >= tu) & (g["ngay"] <= den)
    post = (g["ngay"] > den) & (g["ngay"] <= den + timedelta(days=SO_NGAY_SAU_KM))
    T, C = g["unit"].isin(treated), g["unit"].isin(control)

    def m(mask):
        x = g.loc[mask, "q_per_outlet"]
        return float(x.mean()) if len(x) else float("nan")
    did_dur = (m(T & dur) - m(T & pre)) - (m(C & dur) - m(C & pre))
    did_post = (m(T & post) - m(T & pre)) - (m(C & post) - m(C & pre))
    return {"did_trong_km": did_dur, "did_sau_km": did_post, "so_ngay": D}


def _pull_forward_ratio(s, ma_sp: str, g: pd.DataFrame, sizes: dict) -> float:
    """Tỷ lệ mua dồn: sụt sau KM / tăng trong KM, ước từ các chương trình đã kết thúc có đối chứng."""
    up = dip = 0.0
    for km in s.scalars(select(ChuongTrinhKM).where(ChuongTrinhKM.ma_sp == ma_sp,
                                                    ChuongTrinhKM.trang_thai == "ket_thuc",
                                                    ChuongTrinhKM.don_vi_doi_chung.is_not(None))):
        r = _did(g, _units_of(km, sizes), km.don_vi_doi_chung, km.tu_ngay, km.den_ngay)
        if np.isfinite(r["did_trong_km"]) and np.isfinite(r["did_sau_km"]) and r["did_trong_km"] > 0:
            up += r["did_trong_km"] * r["so_ngay"]
            dip += max(0.0, -r["did_sau_km"]) * SO_NGAY_SAU_KM
    return float(np.clip(dip / up, 0, 0.8)) if up > 0 else TY_LE_SUT_MAC_DINH


def propose(s, user: User, ma_sp: str, tu_ngay: date, den_ngay: date, ngan_sach: int,
            cac_muc_giam: list[float]) -> dict:
    require_role(user, PKD)
    sp = s.get(SanPham, ma_sp)
    if sp is None:
        raise NotFound("sản phẩm", ma_sp)
    g, sizes = _unit_daily(s, ma_sp)
    promo_rows = g[g["m"] > 0] if not g.empty else g
    if len(promo_rows) < 30:
        similar = [evaluate(s, km.ma_km) for km in s.scalars(select(ChuongTrinhKM).where(
            ChuongTrinhKM.ma_sp == ma_sp, ChuongTrinhKM.trang_thai == "ket_thuc"))]
        raise DomainError("CHUA_DU_LICH_SU", "Chưa đủ lịch sử KM để huấn luyện; xem kết quả các chương trình tương tự",
                          {"chuong_trinh_tuong_tu": similar})
    units = sorted(g["unit"].unique())
    code = {u: i for i, u in enumerate(units)}
    base = g[g["m"] == 0].groupby("unit")["q_per_outlet"].mean().to_dict()

    # Đặc trưng theo nhóm điểm bán và vùng (không theo mã đơn vị) để phản ứng KM học được ở một vùng
    # khái quát sang đơn vị chưa từng chạy KM (ví dụ đơn vị luôn làm đối chứng)
    nhom_code = {x: i for i, x in enumerate(sorted({u.split("|")[1] for u in units}))}
    vung_code = {x: i for i, x in enumerate(sorted({u.split("|")[0] for u in units}))}

    def feats(df, m=None):
        parts = df["unit"].str.split("|", expand=True)
        return np.column_stack([pd.to_datetime(df["ngay"]).dt.weekday, parts[1].map(nhom_code), parts[0].map(vung_code),
                                df["unit"].map(base).fillna(0), df["m"] if m is None else np.full(len(df), m)])
    m1, m0 = ai_engine.regressor(), ai_engine.regressor()       # T-learner
    m1.fit(feats(promo_rows), promo_rows["q_per_outlet"])
    nopromo = g[g["m"] == 0]
    m0.fit(feats(nopromo), nopromo["q_per_outlet"])
    r_dip = _pull_forward_ratio(s, ma_sp, g, sizes)
    price, margin = list_price(s, ma_sp), sp.bien_ln
    days = pd.date_range(tu_ngay, den_ngay, freq="D").date
    levels = sorted(set(cac_muc_giam))
    n, k = len(units), len(levels)
    Y1, Y0 = np.zeros((n, k)), np.zeros(n)
    for i, u in enumerate(units):
        grid = pd.DataFrame({"ngay": days, "unit": u, "m": 0.0})
        y0 = np.clip(m0.predict(feats(grid, 0.0)), 0, None).sum() * sizes.get(u, 1)
        Y0[i] = y0
        for j, lv in enumerate(levels):
            Y1[i, j] = max(y0, np.clip(m1.predict(feats(grid, lv)), 0, None).sum() * sizes.get(u, 1))
    uplift = Y1 - Y0[:, None]
    cost = np.array([[lv * price * Y1[i, j] for j, lv in enumerate(levels)] for i in range(n)])
    profit = margin * price * (uplift - r_dip * uplift) - cost
    # Đối chứng ngẫu nhiên ~10% đơn vị, chọn TRƯỚC khi tối ưu để ROI đo sau không bị lệch (A/B theo vùng)
    rng = random.Random(f"{ma_sp}{tu_ngay}")
    ctrl = sorted(rng.sample(units, max(1, round(TY_LE_DOI_CHUNG * n)))) if n >= 3 else []
    for u in ctrl:
        profit[code[u], :] = -1.0

    def option(name: str, choice: list[int | None]) -> dict:
        apply = [(units[i], levels[c], i, c) for i, c in enumerate(choice) if c is not None and units[i] not in ctrl]
        tot_cost = sum(cost[i, c] for *_, i, c in apply)
        tot_profit = sum(profit[i, c] for *_, i, c in apply)
        return {"ten": name, "don_vi": [{"don_vi": u, "muc_giam": lv, "tang_them_thung": round(uplift[i, c], 1),
                                         "chi_phi": int(cost[i, c]), "loi_nhuan_tang_them": int(profit[i, c])}
                                        for u, lv, i, c in apply],
                "don_vi_doi_chung": ctrl, "tong_chi_phi": int(tot_cost), "tong_loi_nhuan_tang_them": int(tot_profit),
                "roi": round(tot_profit / tot_cost, 3) if tot_cost else None}

    # Cách hiện tại: một mức giảm đồng đều, áp cho các đơn vị bán lớn nhất đến khi hết ngân sách
    best_uniform, best_val = [None] * n, -np.inf
    for j in range(k):
        choice, spent = [None] * n, 0.0
        for i in np.argsort(-Y0):
            if units[i] not in ctrl and spent + cost[i, j] <= ngan_sach:
                choice[i], spent = j, spent + cost[i, j]
        val = sum(profit[i, j] for i in range(n) if choice[i] is not None)
        if val > best_val:
            best_uniform, best_val = choice, val
    opts = [option("toi_uu_ngan_sach", ai_engine.solve_mckp(profit, cost, ngan_sach)),
            option("tiet_kiem_70pct", ai_engine.solve_mckp(profit, cost, 0.7 * ngan_sach)),
            option("dong_deu_hien_tai", best_uniform)]
    from app.ph2_inventory import contracts as ph2
    from app.ph2_inventory.models import Kho
    ton = sum(ph2.available_map(s, kh, [ma_sp]).get(ma_sp, 0) for kh in s.scalars(select(Kho.ma_kho)))
    for o in opts:
        need = sum(d["tang_them_thung"] for d in o["don_vi"])
        o["canh_bao_ton"] = need > ton   # tồn hiện có chưa tính hàng về; PH2 NC2 sẽ cộng vào đề xuất bổ sung
    opts = _plain(opts)
    pa = PhuongAnKM(ma_pa=new_id("PA"), nguoi_lap=user.ma,
                    dau_vao={"ma_sp": ma_sp, "tu_ngay": str(tu_ngay), "den_ngay": str(den_ngay),
                             "ngan_sach": ngan_sach, "cac_muc_giam": levels, "ty_le_mua_don": r_dip,
                             "mo_hinh": f"t_learner_{ai_engine.BACKEND}"},
                    phuong_an=opts)
    s.add(pa)
    return {"ma_pa": pa.ma_pa, "ty_le_mua_don": round(r_dip, 3), "mo_hinh": pa.dau_vao["mo_hinh"],
            "ton_kha_dung_hien_tai": ton, "phuong_an": opts}


def create_program(s, user: User, ma_pa: str, chi_so: int, ly_do: str | None = None) -> ChuongTrinhKM:
    """Tạo chương trình nháp từ phương án đã chọn; vẫn phải qua duyệt hai bước (BR-13)."""
    require_role(user, PKD)
    pa = s.get(PhuongAnKM, ma_pa)
    if pa is None:
        raise NotFound("phương án", ma_pa)
    if chi_so != 0 and not ly_do:
        raise DomainError("CAN_LY_DO", "Chọn khác phương án tối ưu phải ghi lý do")
    o, dv = pa.phuong_an[chi_so], pa.dau_vao
    km = ChuongTrinhKM(ma_km=new_id("KM"), ten=f"KM {dv['ma_sp']} {dv['tu_ngay']} (NC1 – {o['ten']})",
                       ma_sp=dv["ma_sp"], sl_toi_thieu=1, muc_giam=max(d["muc_giam"] for d in o["don_vi"]),
                       muc_giam_theo_don_vi={d["don_vi"]: d["muc_giam"] for d in o["don_vi"]},
                       don_vi_doi_chung=o["don_vi_doi_chung"], tu_ngay=date.fromisoformat(dv["tu_ngay"]),
                       den_ngay=date.fromisoformat(dv["den_ngay"]), ngan_sach=int(dv["ngan_sach"]), da_dung=0,
                       trang_thai="nhap", nguon="nc1", nguoi_lap=user.ma)
    s.add(km)
    pa.phuong_an_chon, pa.ma_km, pa.ly_do_chon = chi_so, km.ma_km, ly_do
    audit.log(s, user.ma, "tao_km_tu_nc1", "chuong_trinh_km", km.ma_km, None, {"ma_pa": ma_pa, "chi_so": chi_so})
    return km


def evaluate(s, ma_km: str) -> dict:
    """ROI thật so với đơn vị đối chứng; lưu vào lịch sử để huấn luyện lần sau."""
    km = s.get(ChuongTrinhKM, ma_km)
    if km is None:
        raise NotFound("chương trình KM", ma_km)
    if km.nguon == "ph2_xa_lo":
        return {"ma_km": ma_km, "ghi_chu": "KM xả lô không giữ đối chứng, đo bằng sản lượng bán trước hạn"}
    if not km.don_vi_doi_chung:
        return {"ma_km": ma_km, "ghi_chu": "Chương trình không có đơn vị đối chứng, không đo được ROI thật"}
    g, sizes = _unit_daily(s, km.ma_sp)
    treated = [u for u in _units_of(km, sizes) if u not in km.don_vi_doi_chung]
    r = _did(g, treated, km.don_vi_doi_chung, km.tu_ngay, km.den_ngay)
    n_outlets = sum(sizes.get(u, 0) for u in treated)
    tang = r["did_trong_km"] * r["so_ngay"] * n_outlets
    sut = min(0.0, r["did_sau_km"]) * SO_NGAY_SAU_KM * n_outlets
    price, margin = list_price(s, km.ma_sp), s.get(SanPham, km.ma_sp).bien_ln
    ln = margin * price * (tang + sut) - km.da_dung
    out = {"ma_km": ma_km, "don_vi_ap": treated, "don_vi_doi_chung": km.don_vi_doi_chung,
           "tang_them_thung": round(tang, 1), "sut_sau_km_thung": round(sut, 1), "chi_phi": km.da_dung,
           "loi_nhuan_tang_them": int(ln), "roi_that": round(ln / km.da_dung, 3) if km.da_dung else None,
           "phuong_phap": "difference_in_differences"}
    s.merge(DanhGiaKM(ma_km=ma_km, ket_qua=out))
    return out
