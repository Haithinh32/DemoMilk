"""Thực thể dùng chung của PH0 (Bảng 4.1): NPP, sản phẩm, người dùng, nhật ký, thông báo, sự kiện."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class NPP(Base):
    __tablename__ = "npp"
    ma_npp: Mapped[str] = mapped_column(String(20), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    vung: Mapped[str] = mapped_column(String(50))
    so_tai_khoan: Mapped[str] = mapped_column(String(30), unique=True)  # tài khoản nhận VietQR của NPP


class SanPham(Base):
    __tablename__ = "san_pham"
    ma_sp: Mapped[str] = mapped_column(String(20), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    nhom_nhiet: Mapped[str] = mapped_column(String(30))       # "lanh" (2–6 °C) hoặc "thuong"
    so_ngay_han: Mapped[int] = mapped_column(Integer)          # hạn dùng tính từ NSX
    quy_cach_thung: Mapped[int] = mapped_column(Integer)       # số hộp/thùng (mọi số lượng trong hệ thống tính theo thùng)
    bien_ln: Mapped[float] = mapped_column()                   # biên lợi nhuận gộp (từ ERP), dùng cho NC1 PH1
    so_ngay_phu: Mapped[int] = mapped_column(Integer, default=3)  # L: số ngày cần phủ đến lần nhập sau (NC2 PH2)


class NguoiDung(Base):
    __tablename__ = "nguoi_dung"
    ma_nguoi_dung: Mapped[str] = mapped_column(String(30), primary_key=True)
    ten: Mapped[str] = mapped_column(String(200))
    vai_tro: Mapped[str] = mapped_column(String(30))
    ma_npp: Mapped[str | None] = mapped_column(ForeignKey("npp.ma_npp"), nullable=True)
    ma_diem_ban: Mapped[str | None] = mapped_column(String(30), nullable=True)
    token: Mapped[str] = mapped_column(String(100), unique=True)
    zalo_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)


class NhatKy(Base):
    """NFR5: ai, lúc nào, sửa gì, giá trị cũ và mới."""
    __tablename__ = "nhat_ky"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    ma_nguoi_dung: Mapped[str] = mapped_column(String(30))
    hanh_dong: Mapped[str] = mapped_column(String(80))
    doi_tuong: Mapped[str] = mapped_column(String(50))
    ma_doi_tuong: Mapped[str] = mapped_column(String(50))
    gia_tri_cu: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    gia_tri_moi: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ThongBao(Base):
    __tablename__ = "thong_bao"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    kenh: Mapped[str] = mapped_column(String(30))           # app, zalo, sms
    nguoi_nhan: Mapped[str] = mapped_column(String(30))     # mã người dùng hoặc mã điểm bán
    tieu_de: Mapped[str] = mapped_column(String(200))
    noi_dung: Mapped[str] = mapped_column(Text)


class SuKien(Base):
    """Hộp thư đi (outbox): sự kiện được ghi trong cùng giao dịch với thay đổi nghiệp vụ sinh ra nó."""
    __tablename__ = "su_kien"
    ma_su_kien: Mapped[str] = mapped_column(String(80), primary_key=True)
    loai: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now, index=True)
    seq: Mapped[int] = mapped_column(BigInteger, default=0)  # time.monotonic_ns() vượt int32
    trang_thai: Mapped[str] = mapped_column(String(30), default="cho", index=True)  # cho, xong, loi
    so_lan_thu: Mapped[int] = mapped_column(Integer, default=0)
    loi: Mapped[str | None] = mapped_column(Text, nullable=True)


class SuKienDaXuLy(Base):
    """Hộp thư đến (inbox) của từng bên nhận: mỗi sự kiện chỉ được một bên nhận xử lý một lần."""
    __tablename__ = "su_kien_da_xu_ly"
    __table_args__ = (UniqueConstraint("ben_nhan", "ma_su_kien"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ben_nhan: Mapped[str] = mapped_column(String(60))
    ma_su_kien: Mapped[str] = mapped_column(String(80))
    xu_ly_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)


class NhatKyAgent(Base):
    """Agent Gateway: nhật ký mọi lần agent gọi công cụ (mục 3.1, PH0)."""
    __tablename__ = "nhat_ky_agent"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    zalo_id: Mapped[str] = mapped_column(String(50))
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    cong_cu: Mapped[str] = mapped_column(String(50))
    dau_vao: Mapped[dict] = mapped_column(JSON)
    ket_qua: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thanh_cong: Mapped[bool] = mapped_column(Boolean, default=True)
