"""PH4 CN1 – Đi tuyến và chăm sóc điểm bán (mục 3.5.5), cùng các bên nhận sự kiện của PH4."""
import math
from datetime import datetime, timedelta

from sqlalchemy import select

from app import clock, config
from app.errors import DomainError, NotFound
from app.ph0_platform import events, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import NVBH, User, check_npp, require_role
from app.ph4_sales.models import (DiemBan, GoiYDon, LichSuDiem, LuotGhe, NhiemVuThuNo, SoDiem, Tuyen,
                                  TuyenDiemBan)

NGUONG_NGHI_VAN = 0.5


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def route_today(s, user: User) -> dict:
    """NVBH mở tuyến: danh sách điểm bán trong ngày kèm nhiệm vụ thu nợ do PH3 gắn vào."""
    require_role(user, NVBH)
    thu = clock.today().weekday()
    tuyen = s.scalar(select(Tuyen).where(Tuyen.ma_nvbh == user.ma, Tuyen.thu_trong_tuan == thu))
    if tuyen is None:
        return {"ma_tuyen": None, "diem_ban": []}
    rows = s.execute(select(DiemBan, TuyenDiemBan.thu_tu).join(TuyenDiemBan,
                                                                TuyenDiemBan.ma_diem_ban == DiemBan.ma_diem_ban)
                     .where(TuyenDiemBan.ma_tuyen == tuyen.ma_tuyen).order_by(TuyenDiemBan.thu_tu)).all()
    ids = [d.ma_diem_ban for d, _ in rows]
    tasks = s.scalars(select(NhiemVuThuNo).where(NhiemVuThuNo.ma_diem_ban.in_(ids),
                                                 NhiemVuThuNo.trang_thai != "da_thu")).all()
    by_db: dict[str, list] = {}
    for t in tasks:
        by_db.setdefault(t.ma_diem_ban, []).append({"ma_nhiem_vu": t.ma_nhiem_vu, "so_hoa_don": t.so_hoa_don,
                                                    "so_tien": t.so_tien, "han_tra": str(t.han_tra)})
    return {"ma_tuyen": tuyen.ma_tuyen, "diem_ban": [
        {"thu_tu": tt, "ma_diem_ban": d.ma_diem_ban, "ten": d.ten, "lat": d.lat, "lng": d.lng,
         "thu_no": by_db.get(d.ma_diem_ban, [])} for d, tt in rows]}


def _anomaly(s, v: LuotGhe, sync_at: datetime) -> tuple[float, list[str]]:
    """Chấm điểm bất thường đơn giản theo luật; NC2 PH4 (ngoài phạm vi cốt lõi) sẽ thay bằng mô hình."""
    score, reasons = 0.0, []
    if v.khoang_cach_m > config.BAN_KINH_CHECKIN_M:
        score += 0.6; reasons.append("xa_diem_ban")
    hashes = [a.get("sha256") for a in v.anh if a.get("sha256")]
    if hashes:
        others = s.scalars(select(LuotGhe).where(LuotGhe.ma_luot_ghe != v.ma_luot_ghe,
                                                 LuotGhe.ngay >= v.ngay - timedelta(days=90))).all()
        seen = {a.get("sha256") for o in others for a in o.anh}
        if any(h in seen for h in hashes):
            score += 0.6; reasons.append("anh_trung_luot_ghe_khac")
    for a in v.anh:
        t = a.get("thoi_gian")
        if t and abs((datetime.fromisoformat(t) - v.thoi_gian_may).total_seconds()) > 1800:
            score += 0.3; reasons.append("gio_anh_lech_gio_check_in"); break
    if sync_at - v.thoi_gian_may > timedelta(hours=24):
        score += 0.2; reasons.append("dong_bo_qua_24h")   # BR10: gắn cờ cho giám sát
    return min(score, 1.0), reasons


def sync_visit(s, user: User, data: dict) -> dict:
    """Nhận một lượt ghé từ App Sales (trực tuyến hoặc đồng bộ ngoại tuyến). Mã lượt ghé do app sinh."""
    require_role(user, NVBH)
    old = s.get(LuotGhe, data["ma_luot_ghe"])
    if old is not None:
        return {"ma_luot_ghe": old.ma_luot_ghe, "trang_thai": old.trang_thai, "lap_lai": True}
    db = s.get(DiemBan, data["ma_diem_ban"])
    if db is None:
        raise NotFound("điểm bán", data["ma_diem_ban"])
    check_npp(user, db.ma_npp, "điểm bán", db.ma_diem_ban)
    dist = haversine_m(data["lat"], data["lng"], db.lat, db.lng)
    so_lan = int(data.get("so_lan_thu", 1))
    if dist > config.BAN_KINH_CHECKIN_M and so_lan <= 3:
        # BR6: xa hơn 100 m thì cảnh báo và cho thử lại; quá 3 lần mới được ghi kèm lý do
        raise DomainError("CHECK_IN_XA", f"Cách điểm bán {dist:.0f} m (> {config.BAN_KINH_CHECKIN_M} m), thử lại",
                          {"khoang_cach_m": round(dist), "so_lan_thu": so_lan})
    if dist > config.BAN_KINH_CHECKIN_M and not data.get("ly_do_xa"):
        raise DomainError("CAN_LY_DO", "Check-in xa quá 3 lần phải ghi lý do")
    thoi_gian_may = datetime.fromisoformat(data["thoi_gian_may"])
    tuyen = s.scalar(select(Tuyen.ma_tuyen).join(TuyenDiemBan, TuyenDiemBan.ma_tuyen == Tuyen.ma_tuyen)
                     .where(Tuyen.ma_nvbh == user.ma, Tuyen.thu_trong_tuan == thoi_gian_may.weekday(),
                            TuyenDiemBan.ma_diem_ban == db.ma_diem_ban))
    v = LuotGhe(ma_luot_ghe=data["ma_luot_ghe"], ma_nvbh=user.ma, ma_diem_ban=db.ma_diem_ban, ma_npp=db.ma_npp,
                ma_tuyen=tuyen, thoi_gian_may=thoi_gian_may, thoi_gian_dong_bo=clock.now(),
                ngay=thoi_gian_may.date(), lat=data["lat"], lng=data["lng"], khoang_cach_m=dist, so_lan_thu=so_lan,
                ly_do_xa=data.get("ly_do_xa"), anh=data.get("anh", []), het_hang=data.get("het_hang", []),
                trung_bay_dat=data.get("trung_bay_dat"), dung_tuyen=tuyen is not None, trang_thai="hop_le")
    v.diem_bat_thuong, v.ly_do_bat_thuong = _anomaly(s, v, clock.now())
    if v.diem_bat_thuong >= NGUONG_NGHI_VAN:
        v.trang_thai = "nghi_van"
        notification.send(s, f"GS-{db.ma_npp}", "Check-in nghi vấn",
                          f"{user.ma} tại {db.ma_diem_ban}: {', '.join(v.ly_do_bat_thuong)}")
    s.add(v)
    s.flush()
    for kq in data.get("thu_no", []):   # kết quả thu nợ gửi PH3
        nv = s.get(NhiemVuThuNo, kq["ma_nhiem_vu"])
        if nv is None:
            continue
        nv.trang_thai = "da_thu" if kq.get("so_tien_thu", 0) >= nv.so_tien else "hen_tra"
        nv.ket_qua = kq
        events.publish(s, ev.KET_QUA_THU_NO, {"ma_luot_ghe": v.ma_luot_ghe, "ma_nvbh": user.ma,
                                              "ma_diem_ban": db.ma_diem_ban, "so_hoa_don": nv.so_hoa_don,
                                              "so_tien_thu": int(kq.get("so_tien_thu", 0)),
                                              "hen_tra": kq.get("hen_tra")}, ma_su_kien=f"KQTN-{v.ma_luot_ghe}-{nv.so_hoa_don}")
    return {"ma_luot_ghe": v.ma_luot_ghe, "trang_thai": v.trang_thai, "khoang_cach_m": round(dist),
            "dung_tuyen": v.dung_tuyen, "diem_bat_thuong": v.diem_bat_thuong, "ly_do": v.ly_do_bat_thuong}


# ---- Bên nhận sự kiện ---------------------------------------------------------------------

def _hang(diem: int) -> str:
    return "vang" if diem >= 5000 else "bac" if diem >= 1000 else "dong"


def _change_points(s, ma_diem_ban: str, delta: int, ma_su_kien: str, ly_do: str) -> None:
    if s.get(LichSuDiem, ma_su_kien) is not None:   # BR8: mỗi mã sự kiện cộng/trừ một lần
        return
    sd = s.get(SoDiem, ma_diem_ban)
    if sd is None:
        sd = SoDiem(ma_diem_ban=ma_diem_ban, diem=0)
        s.add(sd)
    sd.diem = max(0, sd.diem + delta)
    sd.hang = _hang(sd.diem)
    s.add(LichSuDiem(ma_su_kien=ma_su_kien, ma_diem_ban=ma_diem_ban, thay_doi=delta, ly_do=ly_do))


@events.subscribe(ev.DON_DA_GIAO, "ph4.cong_diem")
def on_delivered(s, p: dict, ma_su_kien: str) -> None:
    _change_points(s, p["ma_diem_ban"], p["gia_tri"] // config.DIEM_MOI_VND, ma_su_kien, f"don {p['ma_don']}")


@events.subscribe(ev.CAN_TRU_DA_XAC_NHAN, "ph4.tru_diem")
def on_offset(s, p: dict, ma_su_kien: str) -> None:
    _change_points(s, p["ma_diem_ban"], -(p["gia_tri"] // config.DIEM_MOI_VND), ma_su_kien,
                   f"can tru {p['ma_phieu']}")   # BR13


@events.subscribe(ev.NHIEM_VU_THU_NO, "ph4.gan_nhiem_vu_thu_no")
def on_collection_task(s, p: dict, ma_su_kien: str) -> None:
    if s.get(NhiemVuThuNo, ma_su_kien) is None:
        s.add(NhiemVuThuNo(ma_nhiem_vu=ma_su_kien, ma_diem_ban=p["ma_diem_ban"], ma_npp=p["ma_npp"],
                           so_hoa_don=p["so_hoa_don"], so_tien=p["so_tien"],
                           han_tra=datetime.fromisoformat(p["han_tra"]).date()))


@events.subscribe(ev.DON_DA_TAO, "ph4.ghi_nhan_goi_y")
def on_order_created(s, p: dict, _ma: str) -> None:
    if p.get("ma_goi_y"):
        g = s.get(GoiYDon, p["ma_goi_y"])
        if g is not None:
            g.trang_thai, g.ma_don = "da_dat", p["ma_don"]


@events.subscribe(ev.LO_DA_KHOA, "ph4.thong_bao_lo_khoa")
def on_lot_locked(s, p: dict, _ma: str) -> None:
    notification.send(s, "PKD", "Lô bị khóa", f"Lô {p['ma_lo']} ({p['ma_sp']}) bị QA khóa: {p['ly_do']}")


def points(s, user: User, ma_diem_ban: str) -> dict:
    from app.ph0_platform.identity import check_outlet
    db = s.get(DiemBan, ma_diem_ban)
    if db is None:
        raise NotFound("điểm bán", ma_diem_ban)
    check_outlet(user, ma_diem_ban, db.ma_npp)
    sd = s.get(SoDiem, ma_diem_ban)
    return {"ma_diem_ban": ma_diem_ban, "diem": sd.diem if sd else 0, "hang": sd.hang if sd else "dong"}
