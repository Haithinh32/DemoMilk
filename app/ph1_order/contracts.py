"""Hợp đồng công khai của PH1 – các phân hệ khác chỉ đọc đơn hàng, giá, KM qua đây."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from app import clock
from app.db import new_id
from app.errors import NotFound
from app.ph1_order.models import ChuongTrinhKM, DongDon, DongGia, DonHang, DonNhap
from app.ph1_order.pricing import price_cart, price_list_for

TU_DAT = {"app", "goi_y", "agent"}   # đơn do điểm bán tự đặt (KPI6)


def order_info(s, ma_don: str) -> dict:
    d = s.get(DonHang, ma_don)
    if d is None:
        raise NotFound("đơn hàng", ma_don)
    return {"ma_don": d.ma_don, "ma_diem_ban": d.ma_diem_ban, "ma_npp": d.ma_npp, "ma_kho": d.ma_kho,
            "trang_thai": d.trang_thai, "hinh_thuc_tt": d.hinh_thuc_tt, "tong_tien": d.tong_tien,
            "ngay_giao": str(d.ngay_giao), "nguon": d.nguon}


def order_line_prices(s, ma_don: str) -> dict[str, int]:
    """Giá net (sau KM) mỗi thùng theo sản phẩm – PH2 gắn vào sự kiện Đã giao, PH3 dùng lập hóa đơn."""
    out = {}
    for l in s.scalars(select(DongDon).where(DongDon.ma_don == ma_don)):
        if l.so_luong:
            out[l.ma_sp] = round(l.thanh_tien / l.so_luong)
    return out


def order_line_promos(s, ma_don: str) -> dict[str, dict]:
    """KM đã áp theo sản phẩm của đơn – PH4 nạp vào kho dữ liệu làm biến tác động cho NC1."""
    out = {}
    for l in s.scalars(select(DongDon).where(DongDon.ma_don == ma_don)):
        gross = l.don_gia * l.so_luong
        out[l.ma_sp] = {"ma_km": l.ma_km, "muc_giam": (l.tien_km / gross) if gross else 0.0}
    return out


def list_price(s, ma_sp: str, vung_gia: str | None = None) -> int:
    bg = price_list_for(s, "diem_ban", vung_gia, clock.today())
    g = s.get(DongGia, (bg.ma_bang_gia, ma_sp))
    return g.don_gia if g else 0


def promo_calendar(s, ma_sp: str | None, tu: date, den: date) -> list[dict]:
    """Lịch KM đã duyệt giao với [tu, den] – đặc trưng có/không KM cho NC2 PH2."""
    q = select(ChuongTrinhKM).where(ChuongTrinhKM.trang_thai.in_(["da_duyet", "ket_thuc", "dung"]),
                                    ChuongTrinhKM.tu_ngay <= den, ChuongTrinhKM.den_ngay >= tu)
    if ma_sp:
        q = q.where(ChuongTrinhKM.ma_sp == ma_sp)
    return [{"ma_km": k.ma_km, "ma_sp": k.ma_sp, "tu_ngay": k.tu_ngay, "den_ngay": k.den_ngay,
             "muc_giam": k.muc_giam, "ma_npp": k.ma_npp} for k in s.scalars(q)]


def recent_orders(s, ma_diem_ban: str, limit: int = 5) -> list[dict]:
    rows = s.scalars(select(DonHang).where(DonHang.ma_diem_ban == ma_diem_ban)
                     .order_by(DonHang.tao_luc.desc()).limit(limit)).all()
    return [{"ma_don": d.ma_don, "trang_thai": d.trang_thai, "tong_tien": d.tong_tien,
             "ngay_giao": str(d.ngay_giao)} for d in rows]


def create_agent_draft(s, outlet, lines: list[tuple[str, int]]) -> dict:
    """Agent chỉ tạo đơn nháp: chưa giữ tồn, hết hạn sau 30 phút; điểm bán bấm xác nhận mới thành đơn."""
    from app.ph2_inventory import contracts as ph2
    avail = ph2.available_map(s, outlet.ma_kho, [sp for sp, _ in lines])
    adjusted = [(sp, min(q, avail.get(sp, 0))) for sp, q in lines]
    adjusted = [(sp, q) for sp, q in adjusted if q > 0]
    quote = price_cart(s, outlet, adjusted, clock.today()) if adjusted else None
    d = DonNhap(ma_nhap=new_id("NH"), ma_diem_ban=outlet.ma_diem_ban,
                dong=[{"ma_sp": sp, "so_luong": q} for sp, q in adjusted], han=clock.now() + timedelta(minutes=30))
    s.add(d)
    return {"ma_nhap": d.ma_nhap, "han": d.han.isoformat(), "bao_gia": quote.as_dict() if quote else None,
            "da_dieu_chinh_theo_ton": {sp: avail.get(sp, 0) for sp, q in lines if q > avail.get(sp, 0)}}


def kpi_snapshot(s, ngay: date, ma_npp: str | None) -> dict:
    start = datetime.combine(ngay, time.min)
    q = select(DonHang).where(DonHang.tao_luc >= start, DonHang.tao_luc < start + timedelta(days=1))
    if ma_npp:
        q = q.where(DonHang.ma_npp == ma_npp)
    orders = s.scalars(q).all()
    approved = [d for d in orders if d.duyet_luc]
    live = [d for d in orders if d.trang_thai != "DA_HUY"]
    minutes = [(d.duyet_luc - d.tao_luc).total_seconds() / 60 for d in approved]
    over = s.scalar(select(func.count()).select_from(ChuongTrinhKM).where(ChuongTrinhKM.da_dung > ChuongTrinhKM.ngan_sach))
    return {"so_don": len(orders),
            "ty_le_tu_dong_duyet": (sum(1 for d in approved if d.tu_dong_duyet) / len(approved)) if approved else None,
            "tg_duyet_tb_phut": (sum(minutes) / len(minutes)) if minutes else None,
            "ty_le_don_tu_dat": (sum(1 for d in live if d.nguon in TU_DAT) / len(live)) if live else None,
            "so_km_vuot_ngan_sach": over}
