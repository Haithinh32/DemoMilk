"""PH3 NC1 – Chấm điểm tín dụng và đề xuất hạn mức (mục 3.4.11).

Nhãn: có quá hạn trong 30 ngày sau ngày chấm. Chia theo thời gian (9 tháng huấn luyện, 3 tháng kiểm tra).
Hồi quy logistic là đường cơ sở, dễ giải thích; cây tăng cường dùng khi đủ dữ liệu. Ba lý do chính lấy từ
đóng góp hệ số × độ lệch đặc trưng của mô hình logistic (chưa cài SHAP).
Chỉ dùng dữ liệu giao dịch, không dùng đặc trưng cá nhân của chủ điểm bán (NFR6).
"""
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from app import clock
from app.db import tx
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import ai_engine, audit
from app.ph0_platform.identity import KE_TOAN_TRUONG, User, check_npp, require_role
from app.ph3_credit import contracts as credit
from app.ph3_credit.models import DiemTinDung, DwTinDungThang, HanMuc

FEATURES = ["doanh_so_chiu", "do_deu_dat_hang", "so_thang_hoat_dong", "so_ngay_tra_tb", "so_lan_qua_han_6t",
            "ty_le_qr", "muc_su_dung_han_muc", "ty_le_tra_hang", "so_lan_dong_cua"]
HE_SO_HANG = {"A": 1.2, "B": 1.0, "C": 0.6, "D": 0.0}   # giả định, hiệu chỉnh khi thử nghiệm
THANG_TOI_THIEU = 6


def _rank(p: float) -> str:
    return "A" if p < 0.02 else "B" if p < 0.05 else "C" if p < 0.15 else "D"


def _frame(s) -> pd.DataFrame:
    rows = s.scalars(select(DwTinDungThang)).all()
    return pd.DataFrame([{**{f: getattr(r, f) for f in FEATURES}, "ma_diem_ban": r.ma_diem_ban, "thang": r.thang,
                          "y": int(r.qua_han_30)} for r in rows])


def train_and_score(ky: date | None = None) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    ky = ky or clock.today().replace(day=1)
    with tx() as s:
        df = _frame(s)
        if df.empty:
            raise DomainError("CHUA_CO_DU_LIEU", "Kho dữ liệu tín dụng trống")
        months = sorted(df["thang"].unique())
        hist = df[df["thang"] < ky]
        cut = months[max(0, len(months) - 4)]               # 3 tháng cuối trước kỳ chấm để kiểm tra
        train, test = hist[hist["thang"] < cut], hist[hist["thang"] >= cut]
        scaler = StandardScaler().fit(train[FEATURES])
        logit = LogisticRegression(max_iter=1000).fit(scaler.transform(train[FEATURES]), train["y"])
        metrics = {"auc_logistic": float(roc_auc_score(test["y"], logit.predict_proba(scaler.transform(test[FEATURES]))[:, 1]))
                   if test["y"].nunique() > 1 else None}
        gbm = None
        if len(train) >= 2000:
            gbm = ai_engine.classifier().fit(train[FEATURES].values, train["y"])
            if test["y"].nunique() > 1:
                metrics["auc_gbm"] = float(roc_auc_score(test["y"], gbm.predict_proba(test[FEATURES].values)[:, 1]))
        use_gbm = gbm is not None and (metrics.get("auc_gbm") or 0) > (metrics["auc_logistic"] or 0)
        model_name = f"{ai_engine.BACKEND}_classifier" if use_gbm else "logistic"
        # Kiểm tra theo hạng: tỷ lệ quá hạn thực tế trên tập kiểm tra (hạng A phải thấp nhất)
        p_test = (gbm.predict_proba(test[FEATURES].values)[:, 1] if use_gbm
                  else logit.predict_proba(scaler.transform(test[FEATURES]))[:, 1])
        by_rank = pd.DataFrame({"hang": [_rank(p) for p in p_test], "y": test["y"].values}) \
            .groupby("hang")["y"].agg(["mean", "count"]).round(4).to_dict("index")
        latest = df[df["thang"] == max(m for m in months if m <= ky)].set_index("ma_diem_ban")
        tenure = df.groupby("ma_diem_ban")["thang"].nunique()
        n = 0
        for hm in s.scalars(select(HanMuc)):
            if hm.ma_diem_ban not in latest.index:
                continue
            row = latest.loc[hm.ma_diem_ban]
            if tenure.get(hm.ma_diem_ban, 0) < THANG_TOI_THIEU:
                rec = DiemTinDung(ma_diem_ban=hm.ma_diem_ban, ma_npp=hm.ma_npp, ky=ky, xac_suat=None, hang="-",
                                  han_muc_hien_tai=hm.han_muc, han_muc_de_xuat=hm.han_muc,
                                  ly_do=["chua_du_6_thang_lich_su"], mo_hinh="chinh_sach_mac_dinh",
                                  trang_thai="giu_mac_dinh")
            else:
                x = row[FEATURES].values.astype(float).reshape(1, -1)
                p = float(gbm.predict_proba(x)[:, 1][0]) if use_gbm else \
                    float(logit.predict_proba(scaler.transform(pd.DataFrame(x, columns=FEATURES)))[:, 1][0])
                # Cộng thêm nợ quá hạn đang có trên sổ thật: không đề xuất tăng hạn mức cho điểm bán đang quá hạn
                if credit.overdue(s, hm.ma_diem_ban) > 0:
                    p = max(p, 0.15)
                hang = _rank(p)
                contrib = logit.coef_[0] * scaler.transform(pd.DataFrame(x, columns=FEATURES))[0]
                top = [FEATURES[i] + ("_cao" if contrib[i] > 0 else "_thap") for i in np.argsort(-np.abs(contrib))[:3]]
                ky_han = hm.ky_han_ngay or 7
                de_xuat = int(round(row["doanh_so_chiu"] * (ky_han / 30) * HE_SO_HANG[hang], -5))
                rec = DiemTinDung(ma_diem_ban=hm.ma_diem_ban, ma_npp=hm.ma_npp, ky=ky, xac_suat=round(p, 4), hang=hang,
                                  han_muc_hien_tai=hm.han_muc, han_muc_de_xuat=de_xuat, ly_do=top, mo_hinh=model_name)
            old = s.scalar(select(DiemTinDung).where(DiemTinDung.ma_diem_ban == hm.ma_diem_ban, DiemTinDung.ky == ky))
            if old is not None:
                s.delete(old)
                s.flush()
            s.add(rec)
            n += 1
    return {"ky": str(ky), "so_diem_ban": n, "mo_hinh": model_name, "chi_so": metrics, "ty_le_qua_han_theo_hang": by_rank,
            "ghi_chu": "Dữ liệu huấn luyện là lịch sử mô phỏng (mo_phong=True)"}


def decide(s, user: User, id_: int, han_muc_chot: int | None = None, ly_do: str | None = None) -> dict:
    """Kế toán trưởng chấp nhận hoặc sửa; lệch đề xuất trên 30% phải ghi lý do. Hệ thống chỉ đề xuất."""
    require_role(user, KE_TOAN_TRUONG)
    rec = s.get(DiemTinDung, id_)
    if rec is None:
        raise NotFound("điểm tín dụng", str(id_))
    check_npp(user, rec.ma_npp, "điểm tín dụng", str(id_))
    if rec.trang_thai not in ("de_xuat",):
        raise Conflict("SAI_TRANG_THAI", f"Đề xuất đang {rec.trang_thai}")
    chot = rec.han_muc_de_xuat if han_muc_chot is None else han_muc_chot
    if rec.han_muc_de_xuat and abs(chot - rec.han_muc_de_xuat) / rec.han_muc_de_xuat > 0.3 and not ly_do:
        raise DomainError("CAN_LY_DO_LECH", "Lệch đề xuất trên 30% phải ghi lý do")
    hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == rec.ma_diem_ban).with_for_update())
    old = {"han_muc": hm.han_muc, "mua_chiu": hm.mua_chiu}
    hm.han_muc, hm.mua_chiu, hm.nguoi_duyet = chot, chot > 0, user.ma
    if hm.mua_chiu and not hm.ky_han_ngay:
        hm.ky_han_ngay = 7
    rec.trang_thai = "chap_nhan" if chot == rec.han_muc_de_xuat else "sua"
    rec.han_muc_chot, rec.ly_do_lech, rec.quyet_boi = chot, ly_do, user.ma
    audit.log(s, user.ma, "cap_nhat_han_muc", "han_muc", rec.ma_diem_ban, old,
              {"han_muc": chot, "nguon": f"NC1 {rec.ky}", "ly_do": ly_do})
    return {"ma_diem_ban": rec.ma_diem_ban, "han_muc": chot, "trang_thai": rec.trang_thai}
