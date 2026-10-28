"""Hợp đồng công khai của PH4: hồ sơ điểm bán, trạng thái check-in, đơn gợi ý."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.errors import NotFound
from app.ph4_sales.models import DiemBan, GoiYDon, LuotGhe


@dataclass(frozen=True)
class OutletInfo:
    ma_diem_ban: str
    ma_npp: str
    ma_kho: str
    ten: str
    vung_gia: str
    vung: str
    nhom: str
    kenh: str
    trang_thai: str
    lat: float
    lng: float


def get_outlet(s, ma_diem_ban: str) -> OutletInfo:
    d = s.get(DiemBan, ma_diem_ban)
    if d is None:
        raise NotFound("điểm bán", ma_diem_ban)
    return OutletInfo(d.ma_diem_ban, d.ma_npp, d.ma_kho, d.ten, d.vung_gia, d.vung, d.nhom, d.kenh, d.trang_thai,
                      d.lat, d.lng)


def has_valid_checkin(s, ma_nvbh: str, ma_diem_ban: str, ngay: date) -> bool:
    return s.scalar(select(LuotGhe.ma_luot_ghe).where(LuotGhe.ma_nvbh == ma_nvbh, LuotGhe.ma_diem_ban == ma_diem_ban,
                                                      LuotGhe.ngay == ngay,
                                                      LuotGhe.trang_thai.in_(["hop_le", "nghi_van"])).limit(1)) is not None


def get_suggestion(s, ma_diem_ban: str, ngay: date) -> dict | None:
    g = s.scalar(select(GoiYDon).where(GoiYDon.ma_diem_ban == ma_diem_ban, GoiYDon.ngay <= ngay)
                 .order_by(GoiYDon.ngay.desc()).limit(1))
    if g is None or (ngay - g.ngay).days > 1:
        return None
    return {"ma_goi_y": g.ma_goi_y, "ngay": str(g.ngay), "dong": g.dong, "phuong_phap": g.phuong_phap,
            "trang_thai": g.trang_thai}
