"""PH4 CN5 – Báo cáo và dashboard quản trị (mục 3.5.9): nạp kho dữ liệu, kiểm tra chất lượng, tính KPI
của cả bốn phân hệ qua kpi_snapshot() trong contracts của từng phân hệ, cảnh báo vượt ngưỡng, khoan xuống."""
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app import clock
from app.db import tx
from app.ph0_platform import notification
from app.ph0_platform.identity import User, check_npp
from app.ph0_platform.models import NPP
from app.ph1_order import contracts as ph1
from app.ph2_inventory import contracts as ph2
from app.ph3_credit import contracts as ph3
from app.ph4_sales.models import DiemBan, DwBanHangNgay, DwKiemTra, KpiNgay, LuotGhe, NguongKpi, Tuyen, TuyenDiemBan


def load_warehouse(ngay: date | None = None) -> dict:
    """Nạp tăng dần dữ liệu một ngày (xóa rồi nạp lại ngày đó nên chạy lại không trùng, D9)."""
    ngay = ngay or clock.today()
    with tx() as s:
        src = ph2.list_deliveries(s, ngay)
        s.execute(delete(DwBanHangNgay).where(DwBanHangNgay.ngay == ngay, DwBanHangNgay.mo_phong.is_(False)))
        outlets = {d.ma_diem_ban: d for d in s.scalars(select(DiemBan))}
        promo_cache, info_cache = {}, {}
        for r in src:
            if r["ma_don"] not in promo_cache:
                promo_cache[r["ma_don"]] = ph1.order_line_promos(s, r["ma_don"])
                info_cache[r["ma_don"]] = ph1.order_info(s, r["ma_don"])
            km = promo_cache[r["ma_don"]].get(r["ma_sp"], {})
            db = outlets[r["ma_diem_ban"]]
            s.add(DwBanHangNgay(ngay=ngay, ma_npp=r["ma_npp"], ma_kho=r["ma_kho"], ma_diem_ban=r["ma_diem_ban"],
                                vung=db.vung, nhom=db.nhom, ma_sp=r["ma_sp"], so_luong=r["so_luong"],
                                doanh_thu=r["so_luong"] * r["don_gia"], muc_giam=km.get("muc_giam", 0.0),
                                ma_km=km.get("ma_km"), tu_dat=info_cache[r["ma_don"]]["nguon"] in ph1.TU_DAT))
        s.flush()
        loaded = int(s.scalar(select(func.coalesce(func.sum(DwBanHangNgay.so_luong), 0))
                              .where(DwBanHangNgay.ngay == ngay, DwBanHangNgay.mo_phong.is_(False))))
        expected = sum(r["so_luong"] for r in src)
        ok = loaded == expected
        s.add(DwKiemTra(ngay=ngay, nguon="ph2.giao_hang", ket_qua="dat" if ok else "loi",
                        chi_tiet=f"nguồn {expected} thùng, nạp {loaded} thùng"))
        if not ok:
            notification.send(s, "ADMIN", "Lỗi chất lượng dữ liệu", f"Ngày {ngay}: lệch tổng giao hàng")
    return {"ngay": str(ngay), "so_dong": len(src), "kiem_tra": "dat" if ok else "loi"}


def _ph4_kpis(s, ngay: date, ma_npp: str | None) -> dict:
    q = select(LuotGhe).where(LuotGhe.ngay == ngay)
    if ma_npp:
        q = q.where(LuotGhe.ma_npp == ma_npp)
    visits = s.scalars(q).all()
    planned_q = select(func.count()).select_from(TuyenDiemBan).join(Tuyen, Tuyen.ma_tuyen == TuyenDiemBan.ma_tuyen) \
        .where(Tuyen.thu_trong_tuan == ngay.weekday())
    if ma_npp:
        planned_q = planned_q.where(Tuyen.ma_npp == ma_npp)
    planned = s.scalar(planned_q) or 0
    on_route = len({v.ma_diem_ban for v in visits if v.dung_tuyen and v.trang_thai != "khong_hop_le"})
    active_q = select(func.count(func.distinct(DwBanHangNgay.ma_diem_ban))).where(
        DwBanHangNgay.ngay > ngay - timedelta(days=30), DwBanHangNgay.ngay <= ngay)
    if ma_npp:
        active_q = active_q.where(DwBanHangNgay.ma_npp == ma_npp)
    return {"ty_le_ghe_dung_tuyen": (on_route / planned) if planned else None,
            "ty_le_check_in_nghi_van": (sum(1 for v in visits if v.trang_thai == "nghi_van") / len(visits))
            if visits else None,
            "diem_ban_hoat_dong_30_ngay": s.scalar(active_q) or 0}


def snapshot(s, ngay: date, ma_npp: str | None) -> dict:
    return {"PH1": ph1.kpi_snapshot(s, ngay, ma_npp), "PH2": ph2.kpi_snapshot(s, ngay, ma_npp),
            "PH3": ph3.kpi_snapshot(s, ngay, ma_npp), "PH4": _ph4_kpis(s, ngay, ma_npp)}


def _breach(n: NguongKpi, value) -> bool:
    if value is None:
        return False
    return value > n.nguong if n.chieu == "max" else value < n.nguong


def compute_kpis(ngay: date | None = None) -> dict:
    """Tính KPI theo công ty và từng NPP, lưu lại và gửi cảnh báo khi vượt ngưỡng (báo cáo ngoại lệ)."""
    ngay = ngay or clock.today()
    alerts = []
    with tx() as s:
        nguong = {n.ma_kpi: n for n in s.scalars(select(NguongKpi))}
        s.execute(delete(KpiNgay).where(KpiNgay.ngay == ngay))
        scopes = [("cong_ty", None)] + [("npp", n) for n in s.scalars(select(NPP.ma_npp))]
        for cap, ma in scopes:
            for ph, kpis in snapshot(s, ngay, ma).items():
                for k, v in kpis.items():
                    n = nguong.get(k)
                    bad = bool(n and _breach(n, v))
                    s.add(KpiNgay(ngay=ngay, cap=cap, ma_cap=ma or "CONG_TY", ma_kpi=k,
                                  gia_tri=None if v is None else float(v), vuot_nguong=bad))
                    if bad:
                        alerts.append({"cap": cap, "ma": ma or "CONG_TY", "kpi": k, "gia_tri": v,
                                       "nguong": n.nguong})
                        notification.send(s, n.nguoi_nhan, f"KPI vượt ngưỡng: {n.ten}",
                                          f"{ma or 'Toàn công ty'} ngày {ngay}: {v:.3f} (ngưỡng {n.nguong})")
    return {"ngay": str(ngay), "canh_bao": alerts}


def dashboard(s, user: User, ngay: date | None = None, ma_npp: str | None = None) -> dict:
    ngay = ngay or clock.today()
    if not user.cap_cong_ty:
        ma_npp = user.ma_npp
    elif ma_npp:
        check_npp(user, ma_npp)
    snap = snapshot(s, ngay, ma_npp)
    nguong = {n.ma_kpi: n for n in s.scalars(select(NguongKpi))}
    kpis = []
    for ph, vals in snap.items():
        for k, v in vals.items():
            n = nguong.get(k)
            kpis.append({"phan_he": ph, "ma_kpi": k, "ten": n.ten if n else k, "gia_tri": v,
                         "nguong": n.nguong if n else None, "chieu": n.chieu if n else None,
                         "vuot_nguong": bool(n and _breach(n, v))})
    week = select(func.count(func.distinct(DwBanHangNgay.ma_diem_ban))).where(
        DwBanHangNgay.ngay > ngay - timedelta(days=7), DwBanHangNgay.tu_dat.is_(True))
    total = select(func.count(func.distinct(DwBanHangNgay.ma_diem_ban))).where(
        DwBanHangNgay.ngay > ngay - timedelta(days=7))
    if ma_npp:
        week, total = week.where(DwBanHangNgay.ma_npp == ma_npp), total.where(DwBanHangNgay.ma_npp == ma_npp)
    chi_so_chinh = {"diem_ban_hoat_dong_30_ngay": snap["PH4"]["diem_ban_hoat_dong_30_ngay"],
                    "ty_le_ghe_dung_tuyen": snap["PH4"]["ty_le_ghe_dung_tuyen"],
                    "ty_le_don_tu_dat": snap["PH1"]["ty_le_don_tu_dat"],
                    "diem_ban_tu_dat_7_ngay": f"{s.scalar(week) or 0}/{s.scalar(total) or 0}"}
    return {"ngay": str(ngay), "pham_vi": ma_npp or "CONG_TY", "chi_so_chinh": chi_so_chinh, "kpi": kpis}


def drill_down(s, user: User, cap: str, tu: date, den: date, ma_npp: str | None = None) -> list[dict]:
    """Khoan xuống: vùng -> NPP -> NVBH / điểm bán."""
    if not user.cap_cong_ty:
        ma_npp = user.ma_npp
    if cap == "nvbh":
        q = select(LuotGhe.ma_nvbh, func.count(LuotGhe.ma_luot_ghe)).where(LuotGhe.ngay >= tu, LuotGhe.ngay <= den)
        if ma_npp:
            q = q.where(LuotGhe.ma_npp == ma_npp)
        return [{"ma_nvbh": a, "so_luot_ghe": int(b)} for a, b in s.execute(q.group_by(LuotGhe.ma_nvbh)).all()]
    col = {"vung": DwBanHangNgay.vung, "npp": DwBanHangNgay.ma_npp, "diem_ban": DwBanHangNgay.ma_diem_ban,
           "san_pham": DwBanHangNgay.ma_sp}[cap]
    q = select(col, func.sum(DwBanHangNgay.so_luong), func.sum(DwBanHangNgay.doanh_thu)) \
        .where(DwBanHangNgay.ngay >= tu, DwBanHangNgay.ngay <= den)
    if ma_npp:
        q = q.where(DwBanHangNgay.ma_npp == ma_npp)
    rows = s.execute(q.group_by(col).order_by(func.sum(DwBanHangNgay.doanh_thu).desc()).limit(200)).all()
    return [{cap: k, "so_luong": int(a), "doanh_thu": int(b)} for k, a, b in rows]
