"""PH1 – Đặt hàng B2B và Giá – KM: bảng sở hữu (Bảng 4.1)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class BangGia(Base):
    """Bảng giá có phiên bản, không ghi đè (BR-12)."""
    __tablename__ = "bang_gia"
    ma_bang_gia: Mapped[str] = mapped_column(String(30), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    doi_tuong: Mapped[str] = mapped_column(String(30))        # diem_ban | npp
    vung_gia: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None = mọi vùng
    phien_ban: Mapped[int] = mapped_column(Integer)
    hieu_luc_tu: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30))       # nhap, da_duyet
    nguoi_lap: Mapped[str] = mapped_column(String(30))
    nguoi_duyet: Mapped[str | None] = mapped_column(String(30), nullable=True)


class DongGia(Base):
    __tablename__ = "dong_gia"
    ma_bang_gia: Mapped[str] = mapped_column(ForeignKey("bang_gia.ma_bang_gia"), primary_key=True)
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"), primary_key=True)
    don_gia: Mapped[int] = mapped_column(Integer)             # đồng / thùng


class ChuongTrinhKM(Base):
    __tablename__ = "chuong_trinh_km"
    __table_args__ = (CheckConstraint("da_dung >= 0 AND da_dung <= ngan_sach", name="ck_km_ngan_sach"),)
    ma_km: Mapped[str] = mapped_column(String(30), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    doi_tuong: Mapped[str] = mapped_column(String(30), default="diem_ban")
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"))
    sl_toi_thieu: Mapped[int] = mapped_column(Integer, default=1)
    muc_giam: Mapped[float] = mapped_column(Float)            # tỷ lệ giảm trên giá
    # NC1: mức giảm theo đơn vị "vung|nhom". Có giá trị thì chỉ áp cho các đơn vị này.
    muc_giam_theo_don_vi: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vung_ap_dung: Mapped[list | None] = mapped_column(JSON, nullable=True)
    don_vi_doi_chung: Mapped[list | None] = mapped_column(JSON, nullable=True)  # "vung|nhom" giữ lại không áp KM
    ma_npp: Mapped[str | None] = mapped_column(String(20), nullable=True)      # KM xả lô chỉ cho một NPP
    tu_ngay: Mapped[date] = mapped_column(Date)
    den_ngay: Mapped[date] = mapped_column(Date)
    ngan_sach: Mapped[int] = mapped_column(Integer)
    da_dung: Mapped[int] = mapped_column(Integer, default=0)
    cong_don: Mapped[bool] = mapped_column(Boolean, default=False)
    trang_thai: Mapped[str] = mapped_column(String(30))       # nhap, de_xuat, da_duyet, dung, ket_thuc
    nguon: Mapped[str] = mapped_column(String(30), default="pkd")  # pkd, nc1, ph2_xa_lo
    phien_ban: Mapped[int] = mapped_column(Integer, default=1)
    nguoi_lap: Mapped[str] = mapped_column(String(30))
    nguoi_duyet: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ghi_chu: Mapped[str | None] = mapped_column(Text, nullable=True)


class DonHang(Base):
    __tablename__ = "don_hang"
    ma_don: Mapped[str] = mapped_column(String(30), primary_key=True)
    khoa_chong_trung: Mapped[str] = mapped_column(String(80), unique=True)   # mỗi lần bấm Đặt hàng một khóa
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ma_kho: Mapped[str] = mapped_column(String(20))
    nguon: Mapped[str] = mapped_column(String(30))        # app, goi_y, agent, nvbh, nvbh_offline
    nguoi_tao: Mapped[str] = mapped_column(String(30))
    ma_goi_y: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trang_thai: Mapped[str] = mapped_column(String(25), index=True)
    han_trang_thai: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    hinh_thuc_tt: Mapped[str] = mapped_column(String(30), default="cong_no")  # cong_no | tra_ngay
    yc_chiet_khau_pct: Mapped[float] = mapped_column(Float, default=0)   # chiết khấu ngoài quy định -> NPP duyệt
    tong_truoc_km: Mapped[int] = mapped_column(Integer)
    tong_km: Mapped[int] = mapped_column(Integer)
    tong_tien: Mapped[int] = mapped_column(Integer)
    ngay_giao: Mapped[date] = mapped_column(Date)
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    duyet_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tu_dong_duyet: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ly_do: Mapped[str | None] = mapped_column(Text, nullable=True)


class DongDon(Base):
    __tablename__ = "dong_don"
    ma_don: Mapped[str] = mapped_column(ForeignKey("don_hang.ma_don"), primary_key=True)
    stt: Mapped[int] = mapped_column(Integer, primary_key=True)
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"))
    so_luong: Mapped[int] = mapped_column(Integer)
    don_gia: Mapped[int] = mapped_column(Integer)
    ma_bang_gia: Mapped[str] = mapped_column(String(30))     # phiên bản giá đã áp (BR-12)
    ma_km: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tien_km: Mapped[int] = mapped_column(Integer, default=0)
    thanh_tien: Mapped[int] = mapped_column(Integer)


class DonNhap(Base):
    """Đơn nháp do agent Zalo tạo: chưa giữ tồn, hết hạn sau 30 phút (Bảng 3.6)."""
    __tablename__ = "don_nhap"
    ma_nhap: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"))
    dong: Mapped[list] = mapped_column(JSON)
    han: Mapped[datetime] = mapped_column(DateTime)
    trang_thai: Mapped[str] = mapped_column(String(30), default="moi")  # moi, da_dat, het_han
    ma_don: Mapped[str | None] = mapped_column(String(30), nullable=True)


class DonBoSung(Base):
    """Đơn NPP đặt lên công ty (CN5, ngoài 12 chức năng cốt lõi – bản tối thiểu để nhận đầu ra NC2 của PH2)."""
    __tablename__ = "don_bo_sung"
    ma_don_bs: Mapped[str] = mapped_column(String(40), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"))
    ma_kho: Mapped[str] = mapped_column(String(20))
    ngay: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30))   # de_xuat, da_gui, da_chot
    phien_ban: Mapped[int] = mapped_column(Integer, default=1)
    dong: Mapped[list] = mapped_column(JSON)               # [{ma_sp, de_xuat, so_luong, ly_do_lech, can_cu}]


class PhuongAnKM(Base):
    """NC1: phương án đề xuất, phương án được chọn và lý do (log để huấn luyện lại)."""
    __tablename__ = "phuong_an_km"
    ma_pa: Mapped[str] = mapped_column(String(30), primary_key=True)
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    nguoi_lap: Mapped[str] = mapped_column(String(30))
    dau_vao: Mapped[dict] = mapped_column(JSON)
    phuong_an: Mapped[list] = mapped_column(JSON)
    phuong_an_chon: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ma_km: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ly_do_chon: Mapped[str | None] = mapped_column(Text, nullable=True)


class DanhGiaKM(Base):
    __tablename__ = "danh_gia_km"
    ma_km: Mapped[str] = mapped_column(ForeignKey("chuong_trinh_km.ma_km"), primary_key=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    ket_qua: Mapped[dict] = mapped_column(JSON)
