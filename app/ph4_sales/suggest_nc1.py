"""PH4 NC1 – Gợi ý đơn hàng thông minh (mục 3.5.10).

PH4 chỉ là bộ máy gợi ý: đọc kho dữ liệu, sinh giỏ nháp chỉ gồm hàng còn tồn khả dụng (BR14).
PH1 là bộ máy thực thi: giá, giữ tồn, tín dụng. Mô hình lỗi thì quay về đường cơ sở BR9.
"""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from app import clock
from app.db import tx
from app.ph0_platform import ai_engine
from app.ph2_inventory import contracts as ph2
from app.ph4_sales.models import DiemBan, DwBanHangNgay, GoiYDon, LuotGhe

SO_TUAN_CO_SO = 8          # BR9
TUAN_TOI_THIEU = 4         # dưới 4 tuần lịch sử dùng trung bình nhóm
TUAN_DE_HUAN_LUYEN = 26
NGUONG_CF = 0.3


def _weekly(s, ngay: date, weeks: int) -> pd.DataFrame:
    start = ngay - timedelta(days=7 * weeks)
    rows = s.execute(select(DwBanHangNgay.ma_diem_ban, DwBanHangNgay.ma_sp, DwBanHangNgay.ngay,
                            DwBanHangNgay.so_luong)
                     .where(DwBanHangNgay.ngay > start, DwBanHangNgay.ngay <= ngay)).all()
    df = pd.DataFrame(rows, columns=["db", "sp", "ngay", "q"])
    if df.empty:
        return df
    df["tuan"] = df["ngay"].map(lambda d: (ngay - d).days // 7)   # 0 = 7 ngày gần nhất
    return df


def _train_model(wk: pd.DataFrame, nhom: dict[str, str]):
    """LightGBM/HGB hồi quy Poisson (hợp dữ liệu nhiều số 0) trên đặc trưng trễ theo tuần."""
    piv = wk.groupby(["db", "sp", "tuan"])["q"].sum().unstack(fill_value=0)
    max_w = int(wk["tuan"].max())
    piv = piv.reindex(columns=range(max_w + 1), fill_value=0)
    X, y = [], []
    sp_codes = {sp: i for i, sp in enumerate(sorted(wk["sp"].unique()))}
    nhom_codes = {n: i for i, n in enumerate(sorted(set(nhom.values())))}
    for (db, sp), r in piv.iterrows():
        v = r.values
        for w in range(0, max_w - SO_TUAN_CO_SO):
            lags = v[w + 1:w + 5]
            X.append([*lags, v[w + 1:w + 1 + SO_TUAN_CO_SO].mean(), sp_codes[sp], nhom_codes.get(nhom.get(db), 0)])
            y.append(v[w])
    if len(X) < 200:
        return None
    m = ai_engine.regressor(loss="poisson")
    m.fit(np.array(X), np.array(y))
    return m, piv, sp_codes, nhom_codes


def generate(ngay: date | None = None) -> dict:
    ngay = ngay or clock.today()
    with tx() as s:
        outlets = {d.ma_diem_ban: d for d in s.scalars(select(DiemBan).where(DiemBan.trang_thai == "hoat_dong"))}
        wk = _weekly(s, ngay, TUAN_DE_HUAN_LUYEN + 4)
        if wk.empty:
            return {"ngay": str(ngay), "so_goi_y": 0}
        recent = wk[wk["tuan"] < SO_TUAN_CO_SO]
        base = (recent.groupby(["db", "sp"])["q"].sum() / SO_TUAN_CO_SO).to_dict()
        first_week = wk.groupby("db")["tuan"].max().to_dict()   # tuần xa nhất có mua
        nhom = {k: f"{d.vung}|{d.nhom}" for k, d in outlets.items()}
        recent = recent.assign(nhom=recent["db"].map(nhom))
        group_mean = (recent.groupby(["nhom", "sp"])["q"].sum()
                      / (SO_TUAN_CO_SO * recent.groupby("nhom")["db"].nunique())).to_dict()
        model = None
        phuong_phap = "co_so_8_tuan"
        if int(wk["tuan"].max()) >= TUAN_DE_HUAN_LUYEN:
            try:
                model = _train_model(wk, {k: d.nhom for k, d in outlets.items()})
                phuong_phap = f"{ai_engine.BACKEND}_poisson" if model else phuong_phap
            except Exception:  # noqa: BLE001 - mô hình lỗi thì quay về BR9
                model = None
        # Lọc cộng tác theo điểm bán tương tự: ma trận nhị phân điểm bán × SKU 8 tuần
        mat = (recent.groupby(["db", "sp"])["q"].sum() > 0).unstack(fill_value=False).astype(float)
        sims = None
        if len(mat) > 1:
            norm = np.linalg.norm(mat.values, axis=1, keepdims=True)
            norm[norm == 0] = 1
            unit = mat.values / norm
            sims = unit @ unit.T
            np.fill_diagonal(sims, -1)
        # Hàng tồn ước tính tại điểm bán: lần mua gần nhất tiêu thụ dần trong 7 ngày; checklist hết hàng -> 0
        last_buy = wk.sort_values("ngay").groupby(["db", "sp"]).last()
        oos = {}
        for v in s.scalars(select(LuotGhe).where(LuotGhe.ngay > ngay - timedelta(days=7)).order_by(LuotGhe.ngay)):
            oos[v.ma_diem_ban] = set(v.het_hang or [])
        avail_by_kho = {k: ph2.available_map(s, k) for k in {d.ma_kho for d in outlets.values()}}
        s.execute(delete(GoiYDon).where(GoiYDon.ngay == ngay))
        n = 0
        for db, d in outlets.items():
            new_outlet = first_week.get(db, -1) < TUAN_TOI_THIEU
            avail = avail_by_kho[d.ma_kho]
            lines = []
            for sp in sorted(avail):
                if new_outlet:
                    pred, ly_do = group_mean.get((nhom[db], sp), 0.0), "trung_binh_nhom_cung_vung"
                elif model and (db, sp) in model[1].index:
                    m, piv, spc, nc = model
                    v = piv.loc[(db, sp)].values
                    x = [*v[0:4], v[0:SO_TUAN_CO_SO].mean(), spc.get(sp, 0), nc.get(d.nhom, 0)]
                    pred, ly_do = float(m.predict(np.array([x]))[0]), "du_bao_mo_hinh"
                else:
                    pred, ly_do = base.get((db, sp), 0.0), "trung_binh_8_tuan"
                ton_uoc = 0.0
                if (db, sp) in last_buy.index and sp not in oos.get(db, set()):
                    lb = last_buy.loc[(db, sp)]
                    ton_uoc = lb["q"] * max(0.0, 1 - (ngay - lb["ngay"]).days / 7)
                qty = max(0, math.ceil(pred - ton_uoc - 0.25))
                if qty > 0:
                    lines.append({"ma_sp": sp, "so_luong": qty, "du_bao": round(pred, 2), "ly_do": ly_do})
            if sims is not None and db in mat.index:
                i = mat.index.get_loc(db)
                neigh = np.argsort(-sims[i])[:10]
                share = mat.values[neigh].mean(axis=0)
                for j, sp in enumerate(mat.columns):
                    if mat.values[i, j] == 0 and share[j] >= NGUONG_CF and all(l["ma_sp"] != sp for l in lines):
                        lines.append({"ma_sp": sp, "so_luong": 1, "du_bao": None,
                                      "ly_do": f"{share[j]:.0%} diem_ban_tuong_tu_dang_mua"})
            lines = [{**l, "so_luong": min(l["so_luong"], avail.get(l["ma_sp"], 0))} for l in lines]
            lines = [l for l in lines if l["so_luong"] > 0]   # BR14: chỉ hàng còn tồn khả dụng
            if lines:
                s.add(GoiYDon(ma_goi_y=f"GY-{db}-{ngay:%Y%m%d}", ma_diem_ban=db, ngay=ngay, dong=lines,
                              phuong_phap=phuong_phap))
                n += 1
    return {"ngay": str(ngay), "so_goi_y": n, "phuong_phap": phuong_phap}
