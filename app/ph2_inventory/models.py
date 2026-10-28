"""PH2 – Kho theo lô và Giao hàng: bảng sở hữu (Bảng 4.1)."""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class Kho(Base):
    __tablename__ = "kho"
    ma_kho: Mapped[str] = mapped_column(String(20), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ten: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)


class LoHang(Base):
    __tablename__ = "lo_hang"
    __table_args__ = (CheckConstraint("hsd > nsx", name="ck_lo_hsd"),)   # BR2.1
    ma_lo: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"), index=True)
    nsx: Mapped[date] = mapped_column(Date)
    hsd: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30), default="binh_thuong")  # binh_thuong | khoa
    ly_do_khoa: Mapped[str | None] = mapped_column(Text, nullable=True)
    ket_qua_kiem_nghiem: Mapped[str | None] = mapped_column(Text, nullable=True)


class TonKhoLo(Base):
    """Tồn thực theo lô – kho – vị trí. Khu 'hong' (hàng hỏng, hàng thu hồi) không bao giờ bán."""
    __tablename__ = "ton_kho_lo"
    __table_args__ = (CheckConstraint("so_luong >= 0", name="ck_ton_lo_am"),)
    ma_lo: Mapped[str] = mapped_column(ForeignKey("lo_hang.ma_lo"), primary_key=True)
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"), primary_key=True)
    khu: Mapped[str] = mapped_column(String(30), primary_key=True, default="ban")  # ban | hong
    so_luong: Mapped[int] = mapped_column(Integer)


class TonKhoSP(Base):
    """Một dòng mỗi kho × sản phẩm: đây là dòng bị khóa (FOR UPDATE) khi giữ tồn, theo thứ tự mã sản phẩm."""
    __tablename__ = "ton_kho_sp"
    __table_args__ = (CheckConstraint("da_giu >= 0", name="ck_da_giu_am"),)
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"), primary_key=True)
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"))
    da_giu: Mapped[int] = mapped_column(Integer, default=0)


class LuotGiuTon(Base):
    """Lượt giữ theo sản phẩm – kho; lô chỉ chọn khi xuất theo FEFO (Bảng 3.27)."""
    __tablename__ = "luot_giu_ton"
    __table_args__ = (UniqueConstraint("khoa_chong_trung", "ma_sp", name="uq_giu_chong_trung"),
                      CheckConstraint("so_luong >= 0", name="ck_giu_am"))
    ma_luot: Mapped[str] = mapped_column(String(30), primary_key=True)
    khoa_chong_trung: Mapped[str] = mapped_column(String(80), index=True)
    ma_don: Mapped[str] = mapped_column(String(30), index=True)
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"))
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"))
    so_luong: Mapped[int] = mapped_column(Integer)
    han_giu: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    trang_thai: Mapped[str] = mapped_column(String(30), default="dang_giu", index=True)  # dang_giu, da_nha, da_xuat
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)


class NhapKho(Base):
    """Lịch sử nhập theo lô vào từng kho – nguồn cho truy xuất xuôi (CN5)."""
    __tablename__ = "nhap_kho"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_lo: Mapped[str] = mapped_column(ForeignKey("lo_hang.ma_lo"), index=True)
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"))
    so_luong: Mapped[int] = mapped_column(Integer)
    ngay: Mapped[date] = mapped_column(Date)
    nguon: Mapped[str] = mapped_column(String(30))   # nha_may, dieu_chuyen, tra_lai


class HangDangVe(Base):
    """Phiếu xuất nhà máy đã nhận từ ERP nhưng chưa quét nhận: không tính vào tồn khả dụng (mục 4.7.2)."""
    __tablename__ = "hang_dang_ve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_phieu_erp: Mapped[str] = mapped_column(String(40))
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"))
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"))
    ma_lo: Mapped[str] = mapped_column(String(30))
    nsx: Mapped[date] = mapped_column(Date)
    hsd: Mapped[date] = mapped_column(Date)
    so_luong: Mapped[int] = mapped_column(Integer)
    ngay_ve_du_kien: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30), default="dang_ve")
    __table_args__ = (UniqueConstraint("ma_phieu_erp", "ma_lo", name="uq_hang_ve"),)


class PhieuXuat(Base):
    __tablename__ = "phieu_xuat"
    ma_phieu: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_don: Mapped[str] = mapped_column(String(30), unique=True)
    ma_kho: Mapped[str] = mapped_column(ForeignKey("kho.ma_kho"))
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    ngay_giao: Mapped[date] = mapped_column(Date)
    trang_thai: Mapped[str] = mapped_column(String(30))   # cho_soan, da_xuat, da_giao
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    xuat_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DongPhieuXuat(Base):
    __tablename__ = "dong_phieu_xuat"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_phieu: Mapped[str] = mapped_column(ForeignKey("phieu_xuat.ma_phieu"), index=True)
    ma_sp: Mapped[str] = mapped_column(ForeignKey("san_pham.ma_sp"))
    ma_lo_de_xuat: Mapped[str] = mapped_column(String(30))
    so_luong: Mapped[int] = mapped_column(Integer)
    ma_lo_quet: Mapped[str | None] = mapped_column(String(30), nullable=True)
    doi_lo: Mapped[bool] = mapped_column(Boolean, default=False)
    ly_do_doi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canh_bao_fefo: Mapped[bool] = mapped_column(Boolean, default=False)
    quet_boi: Mapped[str | None] = mapped_column(String(30), nullable=True)


class XacNhanGiao(Base):
    __tablename__ = "xac_nhan_giao"
    ma_su_kien: Mapped[str] = mapped_column(String(80), primary_key=True)   # BR2.7: đồng bộ lại thì bỏ qua
    ma_phieu: Mapped[str] = mapped_column(ForeignKey("phieu_xuat.ma_phieu"), unique=True)
    ma_don: Mapped[str] = mapped_column(String(30))
    ma_nvgh: Mapped[str] = mapped_column(String(30))
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    bang_chung: Mapped[dict] = mapped_column(JSON)


class DongGiao(Base):
    """Lô thực giao cho từng điểm bán – nguồn cho truy xuất tới điểm bán và kiểm tra hàng trả."""
    __tablename__ = "dong_giao"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_su_kien: Mapped[str] = mapped_column(ForeignKey("xac_nhan_giao.ma_su_kien"))
    ma_don: Mapped[str] = mapped_column(String(30))
    ma_diem_ban: Mapped[str] = mapped_column(String(30), index=True)
    ma_npp: Mapped[str] = mapped_column(String(20))
    ma_kho: Mapped[str] = mapped_column(String(20))
    ma_sp: Mapped[str] = mapped_column(String(20))
    ma_lo: Mapped[str] = mapped_column(String(30), index=True)
    so_luong: Mapped[int] = mapped_column(Integer)
    don_gia: Mapped[int] = mapped_column(Integer)
    ngay: Mapped[date] = mapped_column(Date, index=True)


class VuThuHoi(Base):
    __tablename__ = "vu_thu_hoi"
    ma_vu: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_lo: Mapped[str] = mapped_column(ForeignKey("lo_hang.ma_lo"))
    ly_do: Mapped[str] = mapped_column(Text)
    trang_thai: Mapped[str] = mapped_column(String(30), default="mo")
    mo_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    dong_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ty_le_thu_48h: Mapped[float | None] = mapped_column(Float, nullable=True)


class NhiemVuThuHoi(Base):
    __tablename__ = "nhiem_vu_thu_hoi"
    ma_nhiem_vu: Mapped[str] = mapped_column(String(40), primary_key=True)
    ma_vu: Mapped[str] = mapped_column(ForeignKey("vu_thu_hoi.ma_vu"), index=True)
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    ma_npp: Mapped[str] = mapped_column(String(20))
    ma_kho: Mapped[str] = mapped_column(String(20))
    ma_sp: Mapped[str] = mapped_column(String(20))
    so_luong_da_giao: Mapped[int] = mapped_column(Integer)
    so_luong_thu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trang_thai: Mapped[str] = mapped_column(String(30), default="mo")   # mo, da_nhan
    nhan_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NhatKyTruyXuat(Base):
    __tablename__ = "nhat_ky_truy_xuat"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    ma_lo: Mapped[str] = mapped_column(String(30))
    thoi_gian_ms: Mapped[float] = mapped_column(Float)


class DuBaoNhuCau(Base):
    __tablename__ = "du_bao_nhu_cau"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ngay_lap: Mapped[date] = mapped_column(Date, index=True)
    ma_kho: Mapped[str] = mapped_column(String(20))
    ma_sp: Mapped[str] = mapped_column(String(20))
    ngay: Mapped[date] = mapped_column(Date)
    du_bao: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float)
    phuong_phap: Mapped[str] = mapped_column(String(30))


class DeXuatDieuChuyen(Base):
    __tablename__ = "de_xuat_dieu_chuyen"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ngay: Mapped[date] = mapped_column(Date)
    ma_lo: Mapped[str] = mapped_column(String(30))
    ma_sp: Mapped[str] = mapped_column(String(20))
    tu_kho: Mapped[str] = mapped_column(String(20))
    den_kho: Mapped[str] = mapped_column(String(20))
    so_luong: Mapped[int] = mapped_column(Integer)
    gia_tri_cuu: Mapped[int] = mapped_column(Integer)
    chi_phi_cho: Mapped[int] = mapped_column(Integer)
    trang_thai: Mapped[str] = mapped_column(String(30), default="de_xuat")
