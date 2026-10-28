"""PH1 CN1 (bản tối thiểu) và CN5 (bản tối thiểu): đủ để NC1 tạo chương trình qua duyệt hai bước và để
nhận đầu ra NC2 của PH2. Hai chức năng này không nằm trong 12 chức năng cốt lõi."""
from datetime import date, timedelta

from sqlalchemy import select

from app import clock
from app.db import new_id
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import audit, events, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import GDKD, NPP, PKD, User, check_npp, require_role
from app.ph1_order.models import ChuongTrinhKM, DonBoSung
from app.ph1_order.pricing import price_list_for
from app.ph1_order.models import DongGia


def create_promo(s, user: User, data: dict) -> ChuongTrinhKM:
    require_role(user, PKD)
    km = ChuongTrinhKM(ma_km=new_id("KM"), trang_thai="nhap", nguoi_lap=user.ma, da_dung=0, **data)
    s.add(km)
    audit.log(s, user.ma, "lap_km", "chuong_trinh_km", km.ma_km, None, {k: str(v) for k, v in data.items()})
    return km


def approve_promo(s, user: User, ma_km: str) -> ChuongTrinhKM:
    """BR-13: người duyệt khác người lập; sau duyệt chương trình bị khóa, không sửa khi đang chạy."""
    require_role(user, GDKD)
    km = s.get(ChuongTrinhKM, ma_km)
    if km is None:
        raise NotFound("chương trình KM", ma_km)
    if km.trang_thai not in ("nhap", "de_xuat"):
        raise Conflict("SAI_TRANG_THAI", f"Chương trình đang {km.trang_thai}")
    if km.nguoi_lap == user.ma:
        raise DomainError("TU_LAP_TU_DUYET", "Người duyệt phải khác người lập (BR-13)", status=403)
    km.trang_thai, km.nguoi_duyet = "da_duyet", user.ma
    audit.log(s, user.ma, "duyet_km", "chuong_trinh_km", ma_km, {"trang_thai": "nhap"}, {"trang_thai": "da_duyet"})
    return km


def stop_promo(s, user: User, ma_km: str, ly_do: str) -> ChuongTrinhKM:
    require_role(user, GDKD)
    km = s.get(ChuongTrinhKM, ma_km)
    if km is None:
        raise NotFound("chương trình KM", ma_km)
    km.trang_thai, km.ghi_chu = "dung", ly_do
    audit.log(s, user.ma, "dung_km", "chuong_trinh_km", ma_km, {"trang_thai": "da_duyet"}, {"ly_do": ly_do})
    return km


@events.subscribe(ev.DE_XUAT_KM_XA_LO, "ph1.nhan_de_xuat_xa_lo")
def on_clearance_proposal(s, p: dict, ma_su_kien: str) -> None:
    """Đề xuất KM xả lô cận hạn từ PH2: đi theo cùng quy trình duyệt, ưu tiên duyệt trong ngày; không giữ đối chứng."""
    gia = list_price_npp(s, p["ma_sp"])
    today = clock.today()
    km = ChuongTrinhKM(ma_km=new_id("XL"), ten=f"Xả lô {p['ma_lo']}", ma_sp=p["ma_sp"], sl_toi_thieu=1,
                       muc_giam=0.2, ma_npp=p["ma_npp"], tu_ngay=today,
                       den_ngay=date.fromisoformat(p["ngay_den_muc_do"]),
                       ngan_sach=int(gia * p["so_luong_du"] * 0.2), trang_thai="de_xuat", nguon="ph2_xa_lo",
                       nguoi_lap="HE_THONG", ghi_chu=f"Lô {p['ma_lo']} dư {p['so_luong_du']} thùng – duyệt trong ngày")
    s.add(km)
    notification.send(s, "GDKD", "Đề xuất KM xả lô", f"{km.ten}: {p['so_luong_du']} thùng, cần duyệt trong ngày.")


def list_price_npp(s, ma_sp: str) -> int:
    bg = price_list_for(s, "diem_ban", None, clock.today())
    g = s.get(DongGia, (bg.ma_bang_gia, ma_sp))
    return g.don_gia if g else 0


# ---- CN5 tối thiểu: đơn bổ sung của NPP ----------------------------------------------------

@events.subscribe(ev.DE_XUAT_BO_SUNG, "ph1.nhan_de_xuat_bo_sung")
def on_replenishment_proposal(s, p: dict, ma_su_kien: str) -> None:
    ma = f"BS-{p['ma_kho']}-{p['ngay']}"
    if s.get(DonBoSung, ma) is not None:
        return
    s.add(DonBoSung(ma_don_bs=ma, ma_npp=p["ma_npp"], ma_kho=p["ma_kho"], ngay=date.fromisoformat(p["ngay"]),
                    trang_thai="de_xuat",
                    dong=[{"ma_sp": d["ma_sp"], "de_xuat": d["so_luong"], "so_luong": d["so_luong"],
                           "ly_do_lech": None, "can_cu": {k: v for k, v in d.items() if k not in ("ma_sp", "so_luong")}}
                          for d in p["dong"]]))
    notification.send(s, p["ma_npp"], "Đơn bổ sung đề xuất", f"Đơn {ma} đã sẵn sàng để xem và gửi công ty.")


def submit_replenishment(s, user: User, ma_don_bs: str, dieu_chinh: dict[str, dict]) -> DonBoSung:
    """NPP chỉnh và gửi; lệch đề xuất trên 30% phải ghi lý do (lý do trả về NC2)."""
    require_role(user, NPP)
    d = s.get(DonBoSung, ma_don_bs)
    if d is None:
        raise NotFound("đơn bổ sung", ma_don_bs)
    check_npp(user, d.ma_npp, "đơn bổ sung", ma_don_bs)
    if d.trang_thai != "de_xuat":
        raise Conflict("SAI_TRANG_THAI", f"Đơn đang {d.trang_thai}")
    dong = []
    for line in d.dong:
        adj = dieu_chinh.get(line["ma_sp"], {})
        qty = int(adj.get("so_luong", line["so_luong"]))
        base = max(line["de_xuat"], 1)
        if abs(qty - line["de_xuat"]) / base > 0.3 and not adj.get("ly_do"):
            raise DomainError("CAN_LY_DO_LECH", f"{line['ma_sp']}: lệch đề xuất trên 30% phải ghi lý do")
        dong.append({**line, "so_luong": qty, "ly_do_lech": adj.get("ly_do")})
    d.dong, d.trang_thai = dong, "da_gui"
    return d


def confirm_replenishment(s, user: User, ma_don_bs: str) -> DonBoSung:
    """Phòng KD xác nhận: đơn thành tệp gửi ERP (ERP không có API, mục 2.7.6)."""
    require_role(user, PKD)
    d = s.get(DonBoSung, ma_don_bs)
    if d is None or d.trang_thai != "da_gui":
        raise Conflict("SAI_TRANG_THAI", "Đơn chưa được NPP gửi")
    d.trang_thai = "da_chot"
    events.publish(s, ev.DON_BO_SUNG_DA_CHOT, {"ma_don_bs": d.ma_don_bs, "ma_npp": d.ma_npp, "ma_kho": d.ma_kho,
                                               "phien_ban": d.phien_ban,
                                               "dong": [{"ma_sp": l["ma_sp"], "so_luong": l["so_luong"]}
                                                        for l in d.dong if l["so_luong"] > 0]})
    return d
