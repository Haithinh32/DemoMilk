"""Danh mục sự kiện giữa các phân hệ – hợp đồng bất đồng bộ (Bảng 2.4, 3.7, 3.21, 3.34, 3.49).

Mỗi sự kiện có mã duy nhất (ma_su_kien); bên nhận ghi vào hộp thư đến nên xử lý đúng một lần.
Tương tác cần nhất quán tức thời (giữ tồn + trừ ngân sách KM, kiểm tra tín dụng) KHÔNG đi qua đây
mà gọi hàm trong contracts.py của phân hệ kia (mục 3.2.11).
"""
from typing import TypedDict


class DongHang(TypedDict):
    ma_sp: str
    so_luong: int


class DongGiao(TypedDict):
    ma_sp: str
    ma_lo: str
    so_luong: int
    don_gia: int          # giá net sau KM của dòng đơn (lấy từ PH1)


# ---- PH1 phát ---------------------------------------------------------------
DON_DA_TAO = "ph1.don_hang.da_tao"
"""{ma_don, ma_diem_ban, ma_npp, nguon, ma_goi_y?} -> PH4 (ghi nhận gợi ý được chấp nhận)."""

DON_DA_DUYET = "ph1.don_hang.da_duyet"
"""{ma_don, ma_npp, ma_kho, ma_diem_ban, ngay_giao, dong: [DongHang]} -> PH2 lập phiếu xuất FEFO (Bảng 2.4 #7)."""

DON_DA_HUY = "ph1.don_hang.da_huy"
"""{ma_don, ma_diem_ban, ly_do} -> thông tin cho PH4 (tồn và hạn mức đã được nhả đồng bộ trong giao dịch hủy)."""

DON_BO_SUNG_DA_CHOT = "ph1.don_bo_sung.da_chot"
"""{ma_don_bs, ma_npp, ma_kho, phien_ban, dong: [{ma_sp, so_luong}]} -> Integration ghi tệp cho ERP (Bảng 2.4 #13)."""

# ---- PH2 phát ---------------------------------------------------------------
THIEU_HANG_KHI_SOAN = "ph2.don_hang.thieu_hang"
"""{ma_don, ma_sp, so_luong_thieu, ly_do} -> PH1 cắt dòng, tính lại tiền, trả hạn mức phần chênh."""

DON_CHO_GIAO = "ph2.don_hang.cho_giao"
"""{ma_don, ma_phieu} -> PH1 cập nhật trạng thái."""

DON_DA_GIAO = "ph2.don_hang.da_giao"
"""{ma_don, ma_diem_ban, ma_npp, hinh_thuc_tt, gia_tri, dong: [DongGiao]} -> PH3 ghi phải thu, PH4 cộng điểm, PH1 trạng thái."""

LO_DA_KHOA = "ph2.lo.da_khoa"
"""{ma_lo, ma_sp, ly_do, kho_thieu: [{ma_kho, ma_sp, thieu}]} -> PH1 báo đơn bị ảnh hưởng, PH4 thông báo."""

THU_HOI_DA_NHAN = "ph2.thu_hoi.da_nhan"
"""{ma_vu, ma_nhiem_vu, ma_diem_ban, ma_npp, ma_lo, ma_sp, so_luong} -> PH3 cấn trừ theo số kho thực nhận (BR2.10)."""

DE_XUAT_BO_SUNG = "ph2.nc2.de_xuat_bo_sung"
"""{ma_npp, ma_kho, ngay, dong: [{ma_sp, so_luong, du_bao_ngay, ton_kha_dung, hang_dang_ve, ton_muc_tieu}]} -> PH1 CN5."""

DE_XUAT_KM_XA_LO = "ph2.nc2.de_xuat_km_xa_lo"
"""{ma_npp, ma_kho, ma_sp, ma_lo, so_luong_du, ngay_den_muc_do} -> PH1 CN1 (chương trình xả lô, duyệt trong ngày)."""

# ---- PH3 phát ---------------------------------------------------------------
NGOAI_LE_DA_QUYET = "ph3.ngoai_le.da_quyet"
"""{ma_yc, ma_don, duyet: bool, ly_do} -> PH1 tiếp tục duyệt hoặc hủy đơn."""

CAN_TRU_DA_XAC_NHAN = "ph3.can_tru.da_xac_nhan"
"""{ma_phieu, ma_diem_ban, gia_tri} -> PH4 trừ điểm (BR13)."""

NHIEM_VU_THU_NO = "ph3.thu_no.nhiem_vu"
"""{ma_diem_ban, ma_npp, so_hoa_don, so_tien, han_tra} -> PH4 gắn vào tuyến NVBH."""

SO_DA_KHOA = "ph3.so.da_khoa"
"""{ma_npp, ngay, but_toan: [...]} -> Integration ghi bút toán vào phần mềm kế toán NPP."""

# ---- PH4 phát ---------------------------------------------------------------
KET_QUA_THU_NO = "ph4.thu_no.ket_qua"
"""{ma_luot_ghe, ma_nvbh, ma_diem_ban, so_hoa_don, so_tien_thu, hen_tra} -> PH3."""

DIEM_BAN_KICH_HOAT = "ph4.diem_ban.kich_hoat"
"""{ma_diem_ban, ma_npp} -> PH3 tạo hồ sơ tín dụng mặc định 'trả khi nhận hàng'."""
