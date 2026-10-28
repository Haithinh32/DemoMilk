"""PH3 – Công nợ và Thanh toán: bảng sở hữu (Bảng 4.1)."""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base


class HanMuc(Base):
    __tablename__ = "han_muc"
    __table_args__ = (CheckConstraint("dang_giu >= 0", name="ck_han_muc_giu"),)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), primary_key=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    mua_chiu: Mapped[bool] = mapped_column(Boolean, default=False)   # điểm bán mới: trả khi nhận hàng
    han_muc: Mapped[int] = mapped_column(Integer, default=0)
    ky_han_ngay: Mapped[int] = mapped_column(Integer, default=0)
    dang_giu: Mapped[int] = mapped_column(Integer, default=0)        # tổng hạn mức đang giữ cho đơn chưa giao
    nguoi_duyet: Mapped[str | None] = mapped_column(String(30), nullable=True)


class GiuHanMuc(Base):
    __tablename__ = "giu_han_muc"
    ma_don: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    so_tien: Mapped[int] = mapped_column(Integer)
    ngoai_le: Mapped[bool] = mapped_column(Boolean, default=False)
    trang_thai: Mapped[str] = mapped_column(String(30), default="dang_giu")  # dang_giu, da_nha, thanh_no
    tao_luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)


class YeuCauNgoaiLe(Base):
    __tablename__ = "yeu_cau_ngoai_le"
    ma_yc: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_don: Mapped[str] = mapped_column(String(30), unique=True)
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    ma_npp: Mapped[str] = mapped_column(String(20), index=True)
    so_tien: Mapped[int] = mapped_column(Integer)
    ly_do: Mapped[str] = mapped_column(Text)
    nguoi_de_xuat: Mapped[str] = mapped_column(String(30))
    han: Mapped[datetime] = mapped_column(DateTime)
    trang_thai: Mapped[str] = mapped_column(String(30), default="cho")   # cho, duyet, tu_choi, het_han
    nguoi_duyet: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quyet_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KhoanPhaiThu(Base):
    __tablename__ = "khoan_phai_thu"
    __table_args__ = (CheckConstraint("da_tra >= 0 AND da_tra <= so_tien", name="ck_phai_thu"),)
    so_hoa_don: Mapped[str] = mapped_column(String(30), primary_key=True)
    ma_don: Mapped[str] = mapped_column(String(30), unique=True)
    ma_diem_ban: Mapped[str] = mapped_column(ForeignKey("diem_ban.ma_diem_ban"), index=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    so_hddt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    so_tien: Mapped[int] = mapped_column(Integer)
    da_tra: Mapped[int] = mapped_column(Integer, default=0)     # tổng phân bổ + cấn trừ
    ngay: Mapped[date] = mapped_column(Date, index=True)
    han_tra: Mapped[date] = mapped_column(Date, index=True)
    hinh_thuc_tt: Mapped[str] = mapped_column(String(30))
    trang_thai: Mapped[str] = mapped_column(String(30), default="chua_tra")  # chua_tra, tra_mot_phan, da_tra

    @property
    def con_lai(self) -> int:
        return self.so_tien - self.da_tra


class DongPhaiThu(Base):
    __tablename__ = "dong_phai_thu"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    so_hoa_don: Mapped[str] = mapped_column(ForeignKey("khoan_phai_thu.so_hoa_don"), index=True)
    ma_sp: Mapped[str] = mapped_column(String(20))
    ma_lo: Mapped[str] = mapped_column(String(30), index=True)
    so_luong: Mapped[int] = mapped_column(Integer)
    don_gia: Mapped[int] = mapped_column(Integer)


class GiaoDichTT(Base):
    __tablename__ = "giao_dich_tt"
    ma_gd: Mapped[str] = mapped_column(String(30), primary_key=True)
    loai: Mapped[str] = mapped_column(String(30))   # VIETQR, TIEN_MAT
    ma_gd_ngan_hang: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)  # BR-07
    ma_bien_nhan: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)     # chống ghi trùng khi đồng bộ
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ma_diem_ban: Mapped[str | None] = mapped_column(String(30), nullable=True)
    so_tien: Mapped[int] = mapped_column(Integer)
    noi_dung: Mapped[str] = mapped_column(String(200), default="")
    ngay: Mapped[date] = mapped_column(Date, index=True)
    luc: Mapped[datetime] = mapped_column(DateTime, default=clock.now)
    trang_thai: Mapped[str] = mapped_column(String(30))  # da_ghi_nhan, cho_xu_ly
    gach_tu_dong: Mapped[bool] = mapped_column(Boolean, default=False)
    ma_nguoi_thu: Mapped[str | None] = mapped_column(String(30), nullable=True)


class PhanBoTT(Base):
    """Quan hệ nhiều – nhiều giữa giao dịch thanh toán và hóa đơn (mục 3.4.7)."""
    __tablename__ = "phan_bo_tt"
    ma_gd: Mapped[str] = mapped_column(ForeignKey("giao_dich_tt.ma_gd"), primary_key=True)
    so_hoa_don: Mapped[str] = mapped_column(ForeignKey("khoan_phai_thu.so_hoa_don"), primary_key=True)
    so_tien: Mapped[int] = mapped_column(Integer)
    ngay: Mapped[date] = mapped_column(Date)


class SoDuCo(Base):
    """Tiền trả dư không còn hóa đơn để phân bổ – vẫn là tiền đã ghi nhận khi đối soát."""
    __tablename__ = "so_du_co"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_gd: Mapped[str] = mapped_column(ForeignKey("giao_dich_tt.ma_gd"))
    ma_diem_ban: Mapped[str] = mapped_column(String(30))
    ma_npp: Mapped[str] = mapped_column(String(20))
    so_tien: Mapped[int] = mapped_column(Integer)
    ngay: Mapped[date] = mapped_column(Date)


class NopQuy(Base):
    __tablename__ = "nop_quy"
    __table_args__ = (UniqueConstraint("ma_nvgh", "ngay"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"))
    ma_nvgh: Mapped[str] = mapped_column(String(30))
    ngay: Mapped[date] = mapped_column(Date)
    tong_bien_nhan: Mapped[int] = mapped_column(Integer)
    thuc_nop: Mapped[int] = mapped_column(Integer)
    chenh_lech: Mapped[int] = mapped_column(Integer)
    thu_quy: Mapped[str] = mapped_column(String(30))


class SoDoiSoat(Base):
    __tablename__ = "so_doi_soat"
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), primary_key=True)
    ngay: Mapped[date] = mapped_column(Date, primary_key=True)
    ngan_hang: Mapped[int] = mapped_column(Integer)
    quy: Mapped[int] = mapped_column(Integer)
    ghi_nhan: Mapped[int] = mapped_column(Integer)
    chenh_lech: Mapped[int] = mapped_column(Integer)
    cho_xu_ly: Mapped[int] = mapped_column(Integer, default=0)
    khoa_so: Mapped[bool] = mapped_column(Boolean, default=False)
    khoa_luc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    khoa_boi: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ButToan(Base):
    __tablename__ = "but_toan"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_npp: Mapped[str] = mapped_column(ForeignKey("npp.ma_npp"), index=True)
    ngay: Mapped[date] = mapped_column(Date)
    no_tk: Mapped[str] = mapped_column(String(30))
    co_tk: Mapped[str] = mapped_column(String(30))
    so_tien: Mapped[int] = mapped_column(Integer)
    dien_giai: Mapped[str] = mapped_column(String(200))
    chung_tu: Mapped[str] = mapped_column(String(40))
    dieu_chinh: Mapped[bool] = mapped_column(Boolean, default=False)
    ly_do: Mapped[str | None] = mapped_column(Text, nullable=True)
    nguoi_lap: Mapped[str] = mapped_column(String(30), default="HE_THONG")


class PhieuCanTru(Base):
    __tablename__ = "phieu_can_tru"
    ma_phieu: Mapped[str] = mapped_column(String(30), primary_key=True)
    nguon: Mapped[str] = mapped_column(String(30))                     # thu_hoi, tra_hang
    ma_tham_chieu: Mapped[str] = mapped_column(String(60), unique=True)  # mã nhiệm vụ thu hồi / phiếu trả
    ma_diem_ban: Mapped[str] = mapped_column(String(30), index=True)
    ma_npp: Mapped[str] = mapped_column(String(20))
    ma_lo: Mapped[str] = mapped_column(String(30))
    ma_sp: Mapped[str] = mapped_column(String(20))
    so_luong: Mapped[int] = mapped_column(Integer)
    gia_tri: Mapped[int] = mapped_column(Integer)
    ngay: Mapped[date] = mapped_column(Date)


class DwTinDungThang(Base):
    """Đặc trưng tín dụng theo tháng (kho dữ liệu). mo_phong=True là lịch sử giả lập."""
    __tablename__ = "dw_tin_dung_thang"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_diem_ban: Mapped[str] = mapped_column(String(30), index=True)
    thang: Mapped[date] = mapped_column(Date, index=True)
    doanh_so_chiu: Mapped[int] = mapped_column(Integer)
    do_deu_dat_hang: Mapped[float] = mapped_column(Float)
    so_thang_hoat_dong: Mapped[int] = mapped_column(Integer)
    so_ngay_tra_tb: Mapped[float] = mapped_column(Float)
    so_lan_qua_han_6t: Mapped[int] = mapped_column(Integer)
    ty_le_qr: Mapped[float] = mapped_column(Float)
    muc_su_dung_han_muc: Mapped[float] = mapped_column(Float)
    ty_le_tra_hang: Mapped[float] = mapped_column(Float)
    so_lan_dong_cua: Mapped[int] = mapped_column(Integer)
    qua_han_30: Mapped[bool] = mapped_column(Boolean)      # nhãn: có quá hạn trong 30 ngày sau ngày chấm
    mo_phong: Mapped[bool] = mapped_column(Boolean, default=True)


class DiemTinDung(Base):
    __tablename__ = "diem_tin_dung"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ma_diem_ban: Mapped[str] = mapped_column(String(30), index=True)
    ma_npp: Mapped[str] = mapped_column(String(20), index=True)
    ky: Mapped[date] = mapped_column(Date)
    xac_suat: Mapped[float | None] = mapped_column(Float, nullable=True)
    hang: Mapped[str] = mapped_column(String(2))
    han_muc_hien_tai: Mapped[int] = mapped_column(Integer)
    han_muc_de_xuat: Mapped[int] = mapped_column(Integer)
    ly_do: Mapped[list] = mapped_column(JSON)
    mo_hinh: Mapped[str] = mapped_column(String(40))
    trang_thai: Mapped[str] = mapped_column(String(30), default="de_xuat")  # de_xuat, chap_nhan, sua, giu_mac_dinh
    han_muc_chot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ly_do_lech: Mapped[str | None] = mapped_column(Text, nullable=True)
    quyet_boi: Mapped[str | None] = mapped_column(String(30), nullable=True)
    __table_args__ = (UniqueConstraint("ma_diem_ban", "ky"),)
