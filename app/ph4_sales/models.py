"""PH4 – Bán hàng, Điểm bán và Phân tích: bảng sở hữu (Bảng 4.1) và kho dữ liệu phân tích (schema dw)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class DiemBan(Base):
    __tablename__ = "diem_ban"
    ma_diem_ban: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ma_kho: Mapped[str] = mapped_column(String(20))
    ten: Mapped[str] = mapped_column(String(200))
    sdt: Mapped[str] = mapped_column(String(15), unique=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    kenh: Mapped[str] = mapped_column(String(20), default="truyen_thong")
    vung_gia: Mapped[str] = mapped_column(String(20))       # vùng giá dùng chọn bảng giá
    vung: Mapped[str] = mapped_column(String(20))           # vùng thị trường (đơn vị áp KM, đối chứng)
    nhom: Mapped[str] = mapped_column(String(20))           # tap_hoa_nho, tap_hoa_lon, cua_hang_sua
    trang_thai: Mapped[str] = mapped_column(String(30), default="hoat_dong")
    ngay_kich_hoat: Mapped[date] = mapped_column(Date)


class Tuyen(Base):
    __tablename__ = "tuyen"
    ma_tuyen: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"))
    ma_nvbh: Mapped[str] = mapped_column(ForeignKey("nguoi_dung.ma_nguoi_dung"))
    thu_trong_tuan: Mapped[int] = mapped_column(Integer)  # 0 = thứ Hai


class TuyenDiemBan(Base):
    __tablename__ = "tuyen_diem_ban"
    ma_tuyen: Mapped[str] = mapped_column(ForeignKey("tuyen.ma_tuyen"), primary_key=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), primary_key=True)
    thu_tu: Mapped[int] = mapped_column(Integer)


class LuotGhe(Base):
    """Check-in, ảnh, checklist, điểm bất thường. Khóa chính do app sinh trên máy để đồng bộ ngoại tuyến không trùng."""
    __tablename__ = "luot_ghe"
    ma_luot_ghe: Mapped[str] = mapped_column(String(40), primary_key=True)
    ma_nvbh: Mapped[str] = mapped_column(ForeignKey("nguoi_dung.ma_nguoi_dung"), index=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"))
    ma_tuyen: Mapped[str | None] = mapped_column(String(30), nullable=True)
    thoi_gian_may: Mapped[datetime] = mapped_column(DateTime)
    thoi_gian_dong_bo: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    ngay: Mapped[date] = mapped_column(Date, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    khoang_cach_m: Mapped[float] = mapped_column(Float)
    so_lan_thu: Mapped[int] = mapped_column(Integer, default=1)
    ly_do_xa: Mapped[str | None] = mapped_column(String(200), nullable=True)
    anh: Mapped[list] = mapped_column(JSON, default=list)            # [{url, sha256, thoi_gian, lat, lng}]
    het_hang: Mapped[list] = mapped_column(JSON, default=list)       # SKU hết hàng tại điểm bán
    trung_bay_dat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dung_tuyen: Mapped[bool] = mapped_column(Boolean, default=True)
    diem_bat_thuong: Mapped[float] = mapped_column(Float, default=0)
    ly_do_bat_thuong: Mapped[list] = mapped_column(JSON, default=list)
    trang_thai: Mapped[str] = mapped_column(String(30))              # hop_le, nghi_van, khong_hop_le


class NhiemVuThuNo(Base):
    __tablename__ = "nhiem_vu_thu_no"
    ma_nhiem_vu: Mapped[str] = mapped_column(String(80), primary_key=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    ma_npp: Mapped[str] = mapped_column(String(20))
    so_hoa_don: Mapped[str] = mapped_column(String(30))
    so_tien: Mapped[int] = mapped_column(Integer)
    han_tra: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30), default="mo")  # mo, da_thu, hen_tra
    ket_qua: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SoDiem(Base):
    __tablename__ = "so_diem"
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), primary_key=True)
    diem: Mapped[int] = mapped_column(Integer, default=0)
    hang: Mapped[str] = mapped_column(String(30), default="dong")


class LichSuDiem(Base):
    __tablename__ = "lich_su_diem"
    ma_su_kien: Mapped[str] = mapped_column(String(80), primary_key=True)  # UNIQUE: mỗi sự kiện cộng/trừ một lần (BR8)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    thay_doi: Mapped[int] = mapped_column(Integer)
    ly_do: Mapped[str] = mapped_column(String(100))
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)


class GoiYDon(Base):
    __tablename__ = "goi_y_don"
    ma_goi_y: Mapped[str] = mapped_column(String(40), primary_key=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    ngay: Mapped[date] = mapped_column(Date, index=True)
    dong: Mapped[list] = mapped_column(JSON)        # [{ma_sp, so_luong, ly_do, du_bao}]
    phuong_phap: Mapped[str] = mapped_column(String(30))
    trang_thai: Mapped[str] = mapped_column(String(30), default="moi")  # moi, da_dat
    ma_don: Mapped[str | None] = mapped_column(String(30), nullable=True)


class NguongKpi(Base):
    __tablename__ = "nguong_kpi"
    ma_kpi: Mapped[str] = mapped_column(String(50), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    phan_he: Mapped[str] = mapped_column(String(5))
    chieu: Mapped[str] = mapped_column(String(3))       # "max": vượt trên là xấu; "min": dưới là xấu
    nguong: Mapped[float] = mapped_column(Float)
    nguoi_nhan: Mapped[str] = mapped_column(String(30))


class KpiNgay(Base):
    __tablename__ = "kpi_ngay"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ngay: Mapped[date] = mapped_column(Date, index=True)
    cap: Mapped[str] = mapped_column(String(30))        # cong_ty, npp
    ma_cap: Mapped[str] = mapped_column(String(30))
    ma_kpi: Mapped[str] = mapped_column(String(50))
    gia_tri: Mapped[float | None] = mapped_column(Float, nullable=True)
    vuot_nguong: Mapped[bool] = mapped_column(Boolean, default=False)


# ---- Kho dữ liệu (schema phân tích; trên PostgreSQL đặt ở bản đọc) -------------------------

class DwBanHangNgay(Base):
    """Bán ra theo ngày × điểm bán × SKU. mo_phong=True là lịch sử giả lập cho thực nghiệm (phải ghi rõ trong báo cáo)."""
    __tablename__ = "dw_ban_hang_ngay"
    __table_args__ = (Index("ix_dw_bh_db_sp", "ma_diem_ban", "ma_sp"), Index("ix_dw_bh_kho_sp", "ma_kho", "ma_sp"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ngay: Mapped[date] = mapped_column(Date, index=True)
    ma_npp: Mapped[str] = mapped_column(String(20))
    ma_kho: Mapped[str] = mapped_column(String(20))
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    vung: Mapped[str] = mapped_column(String(20))
    nhom: Mapped[str] = mapped_column(String(20))
    ma_sp: Mapped[str] = mapped_column(String(20))
    so_luong: Mapped[int] = mapped_column(Integer)
    doanh_thu: Mapped[int] = mapped_column(Integer)
    muc_giam: Mapped[float] = mapped_column(Float, default=0)
    ma_km: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tu_dat: Mapped[bool] = mapped_column(Boolean, default=False)
    mo_phong: Mapped[bool] = mapped_column(Boolean, default=False)


class DwKiemTra(Base):
    __tablename__ = "dw_kiem_tra"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    ngay: Mapped[date] = mapped_column(Date)
    nguon: Mapped[str] = mapped_column(String(30))
    ket_qua: Mapped[str] = mapped_column(String(30))   # dat, loi
    chi_tiet: Mapped[str] = mapped_column(Text)
