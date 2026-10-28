"""Áp giá và khuyến mãi từ bảng đã duyệt (BR-01, BR-09, BR-12). Không ai sửa giá tay trên đơn."""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.errors import DomainError
from app.ph1_order.models import BangGia, ChuongTrinhKM, DongGia


@dataclass
class PricedLine:
    ma_sp: str
    so_luong: int
    don_gia: int
    ma_bang_gia: str
    ma_km: str | None = None
    muc_giam: float = 0.0
    tien_km: int = 0

    @property
    def thanh_tien(self) -> int:
        return self.don_gia * self.so_luong - self.tien_km


@dataclass
class PricedCart:
    dong: list[PricedLine]
    km_dung: dict[str, int] = field(default_factory=dict)   # ma_km -> chi phí KM của đơn

    @property
    def tong_truoc_km(self) -> int:
        return sum(l.don_gia * l.so_luong for l in self.dong)

    @property
    def tong_km(self) -> int:
        return sum(l.tien_km for l in self.dong)

    @property
    def tong_tien(self) -> int:
        return self.tong_truoc_km - self.tong_km

    def as_dict(self) -> dict:
        return {"dong": [{"ma_sp": l.ma_sp, "so_luong": l.so_luong, "don_gia": l.don_gia, "ma_km": l.ma_km,
                          "tien_km": l.tien_km, "thanh_tien": l.thanh_tien} for l in self.dong],
                "tong_truoc_km": self.tong_truoc_km, "tong_km": self.tong_km, "tong_tien": self.tong_tien}


def price_list_for(s, doi_tuong: str, vung_gia: str | None, ngay: date) -> BangGia:
    """Phiên bản mới nhất đã duyệt, đang hiệu lực; bảng riêng của vùng ưu tiên hơn bảng chung."""
    rows = s.scalars(select(BangGia).where(BangGia.doi_tuong == doi_tuong, BangGia.trang_thai == "da_duyet",
                                           BangGia.hieu_luc_tu <= ngay)).all()
    rows = [b for b in rows if b.vung_gia in (None, vung_gia)]
    if not rows:
        raise DomainError("KHONG_CO_BANG_GIA", f"Chưa có bảng giá {doi_tuong} hiệu lực cho vùng {vung_gia}")
    return max(rows, key=lambda b: (b.vung_gia is not None, b.phien_ban))


def unit_key(outlet) -> str:
    return f"{outlet.vung}|{outlet.nhom}"


def promo_rate_for(km: ChuongTrinhKM, outlet) -> float | None:
    """Mức giảm áp cho điểm bán này, hoặc None nếu chương trình không áp cho điểm bán (kể cả đơn vị đối chứng)."""
    key = unit_key(outlet)
    if km.ma_npp and km.ma_npp != outlet.ma_npp:
        return None
    if km.don_vi_doi_chung and key in km.don_vi_doi_chung:
        return None
    if km.muc_giam_theo_don_vi is not None:
        return km.muc_giam_theo_don_vi.get(key)
    if km.vung_ap_dung and outlet.vung not in km.vung_ap_dung:
        return None
    return km.muc_giam


def active_promos(s, doi_tuong: str, ngay: date, ma_sps) -> list[ChuongTrinhKM]:
    return list(s.scalars(select(ChuongTrinhKM).where(
        ChuongTrinhKM.doi_tuong == doi_tuong, ChuongTrinhKM.trang_thai == "da_duyet",
        ChuongTrinhKM.tu_ngay <= ngay, ChuongTrinhKM.den_ngay >= ngay, ChuongTrinhKM.ma_sp.in_(list(ma_sps)),
        ChuongTrinhKM.da_dung < ChuongTrinhKM.ngan_sach)))


def price_cart(s, outlet, lines: list[tuple[str, int]], ngay: date, bo_km: set[str] = frozenset()) -> PricedCart:
    bg = price_list_for(s, "diem_ban", outlet.vung_gia, ngay)
    gia = {g.ma_sp: g.don_gia for g in s.scalars(select(DongGia).where(DongGia.ma_bang_gia == bg.ma_bang_gia))}
    promos = active_promos(s, "diem_ban", ngay, [sp for sp, _ in lines])
    cart = PricedCart(dong=[])
    for sp, qty in lines:
        if sp not in gia:
            raise DomainError("SP_KHONG_CO_GIA", f"Sản phẩm {sp} không có trong bảng giá {bg.ma_bang_gia}")
        line = PricedLine(ma_sp=sp, so_luong=qty, don_gia=gia[sp], ma_bang_gia=bg.ma_bang_gia)
        best = None
        for km in promos:  # KM không cộng dồn: chọn mức có lợi nhất cho điểm bán (BR-09)
            rate = promo_rate_for(km, outlet)
            if km.ma_sp != sp or km.ma_km in bo_km or rate is None or qty < km.sl_toi_thieu:
                continue
            if best is None or rate > best[1]:
                best = (km, rate)
        if best:
            km, rate = best
            line.ma_km, line.muc_giam = km.ma_km, rate
            line.tien_km = round(line.don_gia * qty * rate)
            cart.km_dung[km.ma_km] = cart.km_dung.get(km.ma_km, 0) + line.tien_km
        cart.dong.append(line)
    return cart
