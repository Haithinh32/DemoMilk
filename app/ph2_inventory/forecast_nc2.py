"""PH2 NC2 – Dự báo nhu cầu và hoạch định tồn kho NPP (mục 3.3.13).

Một mô hình dự báo, hai đầu ra: đơn đề xuất bổ sung (gửi PH1 CN5) và phương án cho lô vàng
(điều chuyển giải bằng bài toán vận tải, phần dư thành đề xuất KM xả lô gửi PH1).
"""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from app import clock, config
from app.db import tx
from app.ph0_platform import ai_engine, events
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.models import SanPham
from app.ph1_order import contracts as ph1
from app.ph2_inventory import contracts as stock
from app.ph2_inventory.models import DeXuatDieuChuyen, DuBaoNhuCau, Kho, LoHang, TonKhoLo
from app.ph4_sales.models import DwBanHangNgay

HORIZON = 14
Z_95 = 1.65
NGAY_DE_HUAN_LUYEN = 180
CHI_PHI_CHO_MOI_THUNG_KM = 300     # đồng / thùng / km (giả định)
TOC_DO_XE_KMH = 40


def _series(s, ngay: date, days: int = 200) -> pd.DataFrame:
    start = ngay - timedelta(days=days)
    rows = s.execute(select(DwBanHangNgay.ma_kho, DwBanHangNgay.ma_sp, DwBanHangNgay.ngay, DwBanHangNgay.so_luong)
                     .where(DwBanHangNgay.ngay > start, DwBanHangNgay.ngay <= ngay)).all()
    df = pd.DataFrame(rows, columns=["kho", "sp", "ngay", "q"])
    if df.empty:
        return df
    df = df.groupby(["kho", "sp", "ngay"])["q"].sum().reset_index()
    idx = pd.date_range(start + timedelta(days=1), ngay, freq="D").date
    out = []
    for (k, sp), g in df.groupby(["kho", "sp"]):
        full = g.set_index("ngay")["q"].reindex(idx, fill_value=0)
        out.append(pd.DataFrame({"kho": k, "sp": sp, "ngay": idx, "q": full.values}))
    return pd.concat(out, ignore_index=True)


def _same_dow_mean(v: np.ndarray, end: int, h: int) -> float:
    """Đường cơ sở: trung bình 4 ngày cùng thứ gần nhất đã quan sát, cho ngày thứ h sau điểm gốc end.

    v[end-1] là ngày quan sát cuối; ngày cần dự báo có chỉ số t = end + h - 1.
    """
    t, vals, k = end + h - 1, [], 1
    while len(vals) < 4 and t - 7 * k >= 0:
        if t - 7 * k < end:
            vals.append(v[t - 7 * k])
        k += 1
    return float(np.mean(vals)) if vals else 0.0


def _features(v: np.ndarray, end: int, h: int, dates, promo: set, sp_code: int, kho_code: int) -> list:
    """Đặc trưng tại điểm gốc end cho ngày thứ h; dates đã nối thêm HORIZON ngày tương lai."""
    target = dates[end + h - 1]
    return [h, target.weekday(), v[max(0, end - 7):end].mean(), v[max(0, end - 28):end].mean(),
            _same_dow_mean(v, end, h), 1 if target in promo else 0, sp_code, kho_code]


def forecast(s, ngay: date) -> dict:
    """Dự báo 14 ngày cho từng kho × sản phẩm; trả {(kho, sp): {"yhat": [...], "sigma", "phuong_phap"}}."""
    df = _series(s, ngay)
    if df.empty:
        return {}
    days = df["ngay"].nunique()
    calendar = ph1.promo_calendar(s, None, ngay - timedelta(days=210), ngay + timedelta(days=HORIZON))
    promo_days: dict[str, set] = {}
    for p in calendar:
        d = p["tu_ngay"]
        while d <= p["den_ngay"]:
            promo_days.setdefault(p["ma_sp"], set()).add(d)
            d += timedelta(days=1)
    groups = {key: g.sort_values("ngay") for key, g in df.groupby(["kho", "sp"])}
    sp_codes = {sp: i for i, sp in enumerate(sorted(df["sp"].unique()))}
    kho_codes = {k: i for i, k in enumerate(sorted(df["kho"].unique()))}
    use_model = days >= NGAY_DE_HUAN_LUYEN
    model = None
    if use_model:
        X, y = [], []
        for (k, sp), g in groups.items():
            v, dates = g["q"].values.astype(float), list(g["ngay"])
            ext_dates = dates + [dates[-1] + timedelta(days=i) for i in range(1, HORIZON + 1)]
            for end in range(35, len(v) - HORIZON, 3):
                for h in range(1, HORIZON + 1):
                    X.append(_features(v, end, h, ext_dates, promo_days.get(sp, set()), sp_codes[sp], kho_codes[k]))
                    y.append(v[end + h - 1])
        try:
            model = ai_engine.regressor()
            model.fit(np.array(X), np.array(y))
        except Exception:  # noqa: BLE001 - lỗi thì quay về trung bình trượt cùng thứ
            model = None
    out = {}
    for (k, sp), g in groups.items():
        v, dates = g["q"].values.astype(float), list(g["ngay"])
        ext_dates = dates + [dates[-1] + timedelta(days=i) for i in range(1, HORIZON + 1)]
        end = len(v)
        if model is not None:
            feats = [_features(v, end, h, ext_dates, promo_days.get(sp, set()), sp_codes[sp], kho_codes[k])
                     for h in range(1, HORIZON + 1)]
            yhat = np.clip(model.predict(np.array(feats)), 0, None)
            method = f"{ai_engine.BACKEND}"
        else:
            yhat = np.array([_same_dow_mean(v, end, h) for h in range(1, HORIZON + 1)])
            method = "tb_cung_thu_4_tuan"
        # σ: sai số của đường cơ sở 1 ngày tới trên 28 ngày gần nhất (ước lượng thận trọng)
        resid = [v[t] - _same_dow_mean(v, t, 1) for t in range(max(29, end - 28), end)]
        sigma = float(np.std(resid)) if resid else 1.0
        out[(k, sp)] = {"yhat": [float(x) for x in yhat], "sigma": max(sigma, 0.5), "phuong_phap": method}
    return out


def _yellow_days(sp: SanPham) -> int:
    """Lô vàng: còn ≤ max(4, 50% hạn dùng) ngày nhưng chưa đỏ (giả định; CN3 chốt ngưỡng theo sản phẩm)."""
    return max(4, math.ceil(0.5 * sp.so_ngay_han))


def _travel_days(a: Kho, b: Kho) -> tuple[float, float]:
    from app.ph4_sales.field import haversine_m
    km = haversine_m(a.lat, a.lng, b.lat, b.lng) / 1000 * 1.3   # hệ số đường bộ
    return km / TOC_DO_XE_KMH / 24, km


def run(ngay: date | None = None) -> dict:
    """23h: dự báo + đơn đề xuất bổ sung; cùng dự báo dùng cho phân bổ lô vàng (5h sau quét hạn)."""
    ngay = ngay or clock.today()
    with tx() as s:
        fc = forecast(s, ngay)
        s.execute(delete(DuBaoNhuCau).where(DuBaoNhuCau.ngay_lap == ngay))
        for (k, sp), f in fc.items():
            for h, yh in enumerate(f["yhat"], 1):
                s.add(DuBaoNhuCau(ngay_lap=ngay, ma_kho=k, ma_sp=sp, ngay=ngay + timedelta(days=h), du_bao=yh,
                                  sigma=f["sigma"], phuong_phap=f["phuong_phap"]))
        products = {p.ma_sp: p for p in s.scalars(select(SanPham))}
        proposals = []
        for kho in s.scalars(select(Kho)):
            avail = stock.available_map(s, kho.ma_kho)
            incoming = stock.incoming_qty(s, kho.ma_kho)
            dong = []
            for sp, p in sorted(products.items()):
                f = fc.get((kho.ma_kho, sp))
                if f is None:
                    continue
                H = int(p.so_ngay_han * 0.7)                        # hạn còn khi hàng về (≥ 70%, BR2.2)
                L = max(1, min(p.so_ngay_phu, H))
                d_hat = float(np.mean(f["yhat"][:L]))
                target = d_hat * L + Z_95 * f["sigma"] * math.sqrt(L)
                qty = math.ceil(max(0.0, target - avail.get(sp, 0) - incoming.get(sp, 0)))
                if qty > 0:
                    dong.append({"ma_sp": sp, "so_luong": qty, "du_bao_ngay": round(d_hat, 2),
                                 "ton_kha_dung": avail.get(sp, 0), "hang_dang_ve": incoming.get(sp, 0),
                                 "ton_muc_tieu": round(target, 1), "L": L, "sigma": round(f["sigma"], 2),
                                 "phuong_phap": f["phuong_phap"]})
            if dong:
                events.publish(s, ev.DE_XUAT_BO_SUNG, {"ma_npp": kho.ma_npp, "ma_kho": kho.ma_kho,
                                                       "ngay": str(ngay + timedelta(days=1)), "dong": dong},
                               ma_su_kien=f"BSX-{kho.ma_kho}-{ngay}")
                proposals.append({"ma_kho": kho.ma_kho, "so_dong": len(dong)})
    return {"ngay": str(ngay), "so_chuoi": len(fc), "de_xuat_bo_sung": proposals}


def plan_yellow_lots(ngay: date | None = None) -> dict:
    """Phần dư của từng lô vàng và phần thiếu của từng kho -> bài toán vận tải; dư còn lại -> KM xả lô."""
    ngay = ngay or clock.today()
    with tx() as s:
        fc = forecast(s, ngay)
        products = {p.ma_sp: p for p in s.scalars(select(SanPham))}
        khos = {k.ma_kho: k for k in s.scalars(select(Kho))}
        red = config.SO_NGAY_LO_DO
        rows = s.execute(select(TonKhoLo, LoHang).join(LoHang, LoHang.ma_lo == TonKhoLo.ma_lo)
                         .where(TonKhoLo.khu == "ban", TonKhoLo.so_luong > 0, LoHang.trang_thai == "binh_thuong")
                         .order_by(LoHang.hsd)).all()
        surplus = []   # (lo, kho, sp, du, d_i)
        earlier: dict[tuple, int] = {}
        for ton, lo in rows:
            days_left = (lo.hsd - ngay).days
            key = (ton.ma_kho, lo.ma_sp)
            if days_left < red:     # lô đỏ không bán cho điểm bán, không chiếm phần nhu cầu
                continue
            if days_left <= _yellow_days(products[lo.ma_sp]):
                d_i = days_left - red
                f = fc.get(key, {"yhat": [0.0] * HORIZON})["yhat"]
                ban_kip = sum(f[:d_i]) - earlier.get(key, 0)
                du = int(max(0, ton.so_luong - max(0.0, ban_kip)))
                if du > 0:
                    surplus.append((lo, ton.ma_kho, lo.ma_sp, du, d_i))
            earlier[key] = earlier.get(key, 0) + ton.so_luong
        s.execute(delete(DeXuatDieuChuyen).where(DeXuatDieuChuyen.ngay == ngay))
        result = {"dieu_chuyen": [], "xa_lo": []}
        for sp in sorted({x[2] for x in surplus}):
            items = [x for x in surplus if x[2] == sp]
            dest = sorted(khos)
            price = ph1.list_price(s, sp)
            supply = np.array([x[3] for x in items], dtype=float)
            demand, gain, feas = np.zeros(len(dest)), np.zeros((len(items), len(dest))), \
                np.zeros((len(items), len(dest)), dtype=bool)
            for j, k in enumerate(dest):
                f = fc.get((k, sp), {"yhat": [0.0] * HORIZON})["yhat"]
                horizon = max(x[4] for x in items)
                demand[j] = max(0.0, sum(f[:horizon]) - stock.available_map(s, k, [sp]).get(sp, 0))
                for i, (lo, src, _, du, d_i) in enumerate(items):
                    if src == k:
                        continue
                    days, km = _travel_days(khos[src], khos[k])
                    feas[i, j] = days + 1 < d_i       # chở + bán phải kịp trước mức đỏ
                    gain[i, j] = price - km * CHI_PHI_CHO_MOI_THUNG_KM
            x = ai_engine.solve_transport(supply, demand, gain, feas)
            for i, (lo, src, _, du, d_i) in enumerate(items):
                moved = 0
                for j, k in enumerate(dest):
                    q = int(x[i, j])
                    if q > 0:
                        _, km = _travel_days(khos[src], khos[k])
                        s.add(DeXuatDieuChuyen(ngay=ngay, ma_lo=lo.ma_lo, ma_sp=sp, tu_kho=src, den_kho=k, so_luong=q,
                                               gia_tri_cuu=q * price, chi_phi_cho=int(q * km * CHI_PHI_CHO_MOI_THUNG_KM)))
                        result["dieu_chuyen"].append({"ma_lo": lo.ma_lo, "tu": src, "den": k, "so_luong": q})
                        moved += q
                left = du - moved
                if left > 0:
                    events.publish(s, ev.DE_XUAT_KM_XA_LO, {
                        "ma_npp": khos[src].ma_npp, "ma_kho": src, "ma_sp": sp, "ma_lo": lo.ma_lo, "so_luong_du": left,
                        "ngay_den_muc_do": str(ngay + timedelta(days=d_i))}, ma_su_kien=f"XL-{lo.ma_lo}-{src}-{ngay}")
                    result["xa_lo"].append({"ma_lo": lo.ma_lo, "kho": src, "so_luong_du": left})
    return result
