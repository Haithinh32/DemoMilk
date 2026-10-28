"""Hợp đồng công khai của PH3 – CN1 Hạn mức và kiểm soát tín dụng (mục 3.4.5).

PH1 gọi check_credit SAU khi đã giữ đủ tồn, trong giao dịch riêng (GD2).
"""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select

from app import clock
from app.db import new_id
from app.errors import NotFound
from app.ph0_platform import integration, notification
from app.ph0_platform.models import NPP
from app.ph3_credit.models import GiuHanMuc, HanMuc, KhoanPhaiThu, YeuCauNgoaiLe

DAT = "DAT"
CHI_TRA_NGAY = "CHI_TRA_NGAY"
VUOT_HAN_MUC = "VUOT_HAN_MUC"


@dataclass
class CreditResult:
    ket_qua: str
    ly_do: str = ""
    han_muc: int = 0
    nghia_vu: int = 0


def outstanding(s, ma_diem_ban: str) -> int:
    return int(s.scalar(select(func.coalesce(func.sum(KhoanPhaiThu.so_tien - KhoanPhaiThu.da_tra), 0))
                        .where(KhoanPhaiThu.ma_diem_ban == ma_diem_ban, KhoanPhaiThu.trang_thai != "da_tra")))


def overdue(s, ma_diem_ban: str, today: date | None = None) -> int:
    today = today or clock.today()
    return int(s.scalar(select(func.coalesce(func.sum(KhoanPhaiThu.so_tien - KhoanPhaiThu.da_tra), 0))
                        .where(KhoanPhaiThu.ma_diem_ban == ma_diem_ban, KhoanPhaiThu.trang_thai != "da_tra",
                               KhoanPhaiThu.han_tra < today)))


def check_credit(s, ma_don: str, ma_diem_ban: str, so_tien: int) -> CreditResult:
    """Nợ quá hạn chặn cứng (BR-02); sau đó nợ chưa thu + đơn chưa giao + đơn mới ≤ hạn mức (BR-01)."""
    hold = s.get(GiuHanMuc, ma_don)
    if hold is not None and hold.trang_thai == "dang_giu":
        return CreditResult(DAT, "da_giu_truoc_do")
    hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == ma_diem_ban).with_for_update())
    if hm is None or not hm.mua_chiu:
        return CreditResult(CHI_TRA_NGAY, "điểm bán chưa được mua chịu")
    qh = overdue(s, ma_diem_ban)
    if qh > 0:
        return CreditResult(CHI_TRA_NGAY, f"có nợ quá hạn {qh:,} đ", hm.han_muc)
    nghia_vu = outstanding(s, ma_diem_ban) + hm.dang_giu + so_tien
    if nghia_vu > hm.han_muc:
        return CreditResult(VUOT_HAN_MUC, f"tổng nghĩa vụ {nghia_vu:,} đ > hạn mức {hm.han_muc:,} đ",
                            hm.han_muc, nghia_vu)
    _hold(s, hm, ma_don, so_tien, ngoai_le=False)
    return CreditResult(DAT, "trong_han_muc", hm.han_muc, nghia_vu)


def _hold(s, hm: HanMuc, ma_don: str, so_tien: int, ngoai_le: bool) -> None:
    s.merge(GiuHanMuc(ma_don=ma_don, ma_diem_ban=hm.ma_diem_ban, so_tien=so_tien, ngoai_le=ngoai_le,
                      trang_thai="dang_giu", tao_luc=clock.now()))
    hm.dang_giu += so_tien


def release_hold(s, ma_don: str) -> None:
    """BR-05: PH1 hủy đơn thì nhả hạn mức đã giữ."""
    hold = s.get(GiuHanMuc, ma_don)
    if hold is None or hold.trang_thai != "dang_giu":
        return
    hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == hold.ma_diem_ban).with_for_update())
    hm.dang_giu -= hold.so_tien
    hold.trang_thai = "da_nha"


def adjust_hold(s, ma_don: str, so_tien_moi: int) -> None:
    """BR-05: PH1 sửa đơn (cắt dòng) thì tính lại phần hạn mức giữ."""
    hold = s.get(GiuHanMuc, ma_don)
    if hold is None or hold.trang_thai != "dang_giu":
        return
    hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == hold.ma_diem_ban).with_for_update())
    hm.dang_giu += so_tien_moi - hold.so_tien
    hold.so_tien = so_tien_moi


def convert_hold_to_debt(s, ma_don: str) -> None:
    """Giao xong: phần giữ chuyển thành dư nợ (khoản phải thu); phần chênh do giao thiếu tự nhả."""
    hold = s.get(GiuHanMuc, ma_don)
    if hold is None or hold.trang_thai != "dang_giu":
        return
    hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == hold.ma_diem_ban).with_for_update())
    hm.dang_giu -= hold.so_tien
    hold.trang_thai = "thanh_no"


def request_exception(s, ma_don: str, ma_diem_ban: str, ma_npp: str, so_tien: int, ly_do: str,
                      nguoi_de_xuat: str, han: datetime) -> str:
    yc = YeuCauNgoaiLe(ma_yc=new_id("NL"), ma_don=ma_don, ma_diem_ban=ma_diem_ban, ma_npp=ma_npp, so_tien=so_tien,
                       ly_do=ly_do, nguoi_de_xuat=nguoi_de_xuat, han=han)
    s.add(yc)
    notification.send(s, f"KTT-{ma_npp}", "Yêu cầu ngoại lệ tín dụng",
                      f"Đơn {ma_don} ({so_tien:,} đ) xin vượt hạn mức: {ly_do}. Hạn duyệt {han:%H:%M %d/%m}.")
    return yc.ma_yc


def expire_exception(s, ma_don: str) -> None:
    yc = s.scalar(select(YeuCauNgoaiLe).where(YeuCauNgoaiLe.ma_don == ma_don))
    if yc is not None and yc.trang_thai == "cho":
        yc.trang_thai = "het_han"


def init_profile(s, ma_diem_ban: str, ma_npp: str) -> None:
    """Điểm bán mới: mặc định trả tiền khi nhận hàng."""
    if s.get(HanMuc, ma_diem_ban) is None:
        s.add(HanMuc(ma_diem_ban=ma_diem_ban, ma_npp=ma_npp, mua_chiu=False, han_muc=0, ky_han_ngay=0))


def debt_summary(s, ma_diem_ban: str) -> dict:
    hm = s.get(HanMuc, ma_diem_ban)
    if hm is None:
        raise NotFound("hồ sơ tín dụng", ma_diem_ban)
    invoices = s.scalars(select(KhoanPhaiThu).where(KhoanPhaiThu.ma_diem_ban == ma_diem_ban,
                                                    KhoanPhaiThu.trang_thai != "da_tra")
                         .order_by(KhoanPhaiThu.han_tra)).all()
    du_no = sum(i.con_lai for i in invoices)
    return {"ma_diem_ban": ma_diem_ban, "mua_chiu": hm.mua_chiu, "han_muc": hm.han_muc, "ky_han_ngay": hm.ky_han_ngay,
            "du_no": du_no, "qua_han": overdue(s, ma_diem_ban), "dang_giu": hm.dang_giu,
            "han_muc_con_lai": max(0, hm.han_muc - du_no - hm.dang_giu) if hm.mua_chiu else 0,
            "hoa_don_mo": [{"so_hoa_don": i.so_hoa_don, "con_lai": i.con_lai, "han_tra": str(i.han_tra),
                            "trang_thai": i.trang_thai} for i in invoices]}


def create_qr(s, ma_diem_ban: str, so_hoa_don: str) -> dict:
    inv = s.get(KhoanPhaiThu, so_hoa_don)
    if inv is None or inv.ma_diem_ban != ma_diem_ban:
        raise NotFound("hóa đơn", so_hoa_don)
    npp = s.get(NPP, inv.ma_npp)
    return integration.vietqr(npp.so_tai_khoan, so_hoa_don, inv.con_lai)


def kpi_snapshot(s, ngay: date, ma_npp: str | None) -> dict:
    from app.ph3_credit.models import GiaoDichTT, SoDoiSoat
    q = select(KhoanPhaiThu).where(KhoanPhaiThu.trang_thai != "da_tra")
    gq = select(GiaoDichTT).where(GiaoDichTT.loai == "VIETQR")
    sq = select(SoDoiSoat).where(SoDoiSoat.ngay == ngay)
    if ma_npp:
        q, gq, sq = q.where(KhoanPhaiThu.ma_npp == ma_npp), gq.where(GiaoDichTT.ma_npp == ma_npp), \
            sq.where(SoDoiSoat.ma_npp == ma_npp)
    inv = s.scalars(q).all()
    tong = sum(i.con_lai for i in inv)
    qua_han = sum(i.con_lai for i in inv if i.han_tra < ngay)
    gds = s.scalars(gq).all()
    so = s.scalars(sq).all()
    return {"ty_le_no_qua_han": (qua_han / tong) if tong else 0.0,
            "ty_le_gach_no_tu_dong": (sum(1 for g in gds if g.gach_tu_dong) / len(gds)) if gds else None,
            "so_npp_da_khoa_so": sum(1 for x in so if x.khoa_so), "chenh_lech_doi_soat": sum(x.chenh_lech for x in so)}
