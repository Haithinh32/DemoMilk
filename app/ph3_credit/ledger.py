"""PH3 CN3 – Đối soát và ghi sổ (mục 3.4.7, 3.4.10), cùng các mắt xích tối thiểu nó cần:
ghi phải thu khi Đã giao và thu tiền mặt (CN2), cấn trừ thu hồi (CN4), nhắc nợ quá hạn (CN5),
duyệt ngoại lệ tín dụng (CN1).

Mỗi đồng tiền ghi đúng một lần: UNIQUE(ma_gd_ngan_hang), UNIQUE(ma_bien_nhan), UNIQUE(ma_tham_chieu) cấn trừ.
Sổ ngày chỉ khóa khi ngân hàng + quỹ thực nộp − số đã ghi nhận = 0 (BR-08).
"""
import re
from datetime import date, timedelta

from sqlalchemy import func, select

from app import clock
from app.db import new_id
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import audit, events, integration, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import KE_TOAN, KE_TOAN_TRUONG, NVGH, THU_QUY, User, check_npp, require_role
from app.ph0_platform.models import NPP
from app.ph2_inventory import contracts as ph2
from app.ph3_credit import contracts as credit
from app.ph3_credit.models import (ButToan, DongPhaiThu, GiaoDichTT, HanMuc, KhoanPhaiThu, NopQuy, PhanBoTT,
                                   PhieuCanTru, SoDoiSoat, SoDuCo, YeuCauNgoaiLe)

MA_HD_RE = re.compile(r"CSM\s+(HD-[A-Z0-9]+)")


# ---- CN1: duyệt ngoại lệ ------------------------------------------------------------------

def decide_exception(s, user: User, ma_yc: str, duyet: bool, ly_do: str | None = None) -> dict:
    require_role(user, KE_TOAN_TRUONG)
    yc = s.get(YeuCauNgoaiLe, ma_yc)
    if yc is None:
        raise NotFound("yêu cầu ngoại lệ", ma_yc)
    check_npp(user, yc.ma_npp, "yêu cầu ngoại lệ", ma_yc)
    if yc.trang_thai != "cho":
        raise Conflict("SAI_TRANG_THAI", f"Yêu cầu đang {yc.trang_thai}")
    if yc.han < clock.now():
        yc.trang_thai = "het_han"
        raise Conflict("QUA_HAN", "Quá 4 giờ làm việc, yêu cầu coi như bị từ chối")
    yc.trang_thai, yc.nguoi_duyet, yc.quyet_luc = ("duyet" if duyet else "tu_choi"), user.ma, clock.now()
    if duyet:
        hm = s.scalar(select(HanMuc).where(HanMuc.ma_diem_ban == yc.ma_diem_ban).with_for_update())
        credit._hold(s, hm, yc.ma_don, yc.so_tien, ngoai_le=True)
    audit.log(s, user.ma, "quyet_ngoai_le_tin_dung", "yeu_cau_ngoai_le", ma_yc, None,
              {"duyet": duyet, "ly_do": ly_do, "so_tien": yc.so_tien})
    events.publish(s, ev.NGOAI_LE_DA_QUYET, {"ma_yc": ma_yc, "ma_don": yc.ma_don, "duyet": duyet, "ly_do": ly_do})
    return {"ma_yc": ma_yc, "trang_thai": yc.trang_thai}


# ---- CN2 tối thiểu: phải thu khi Đã giao ----------------------------------------------------

@events.subscribe(ev.DON_DA_GIAO, "ph3.ghi_phai_thu")
def on_delivered(s, p: dict, _ma: str) -> None:
    """Xuất HĐĐT và tạo phải thu theo số THỰC GIAO; hạn mức đã giữ chuyển thành dư nợ."""
    if s.scalar(select(KhoanPhaiThu).where(KhoanPhaiThu.ma_don == p["ma_don"])):
        return
    credit.convert_hold_to_debt(s, p["ma_don"])
    if p["gia_tri"] <= 0:
        return
    hm = s.get(HanMuc, p["ma_diem_ban"])
    today = clock.today()
    cong_no = p["hinh_thuc_tt"] == "cong_no" and hm is not None and hm.mua_chiu
    so_hd = new_id("HD")
    inv = KhoanPhaiThu(so_hoa_don=so_hd, ma_don=p["ma_don"], ma_diem_ban=p["ma_diem_ban"], ma_npp=p["ma_npp"],
                       so_hddt=integration.issue_einvoice(so_hd, p["gia_tri"]), so_tien=p["gia_tri"], ngay=today,
                       han_tra=today + timedelta(days=hm.ky_han_ngay if cong_no else 0),
                       hinh_thuc_tt=p["hinh_thuc_tt"])
    s.add(inv)
    s.flush()
    for d in p["dong"]:
        s.add(DongPhaiThu(so_hoa_don=so_hd, ma_sp=d["ma_sp"], ma_lo=d["ma_lo"], so_luong=d["so_luong"],
                          don_gia=d["don_gia"]))
    qr = credit.create_qr(s, p["ma_diem_ban"], so_hd)
    notification.send(s, p["ma_diem_ban"], "Hóa đơn mới",
                      f"Hóa đơn {so_hd}: {p['gia_tri']:,} đ, hạn {inv.han_tra:%d/%m}. Quét QR: {qr['noi_dung']}",
                      kenh="zalo")


# ---- Phân bổ thanh toán ---------------------------------------------------------------------

def _ensure_day_open(s, ma_npp: str, ngay: date) -> None:
    so = s.get(SoDoiSoat, (ma_npp, ngay))
    if so is not None and so.khoa_so:
        raise Conflict("SO_DA_KHOA", f"Sổ ngày {ngay} đã khóa; sửa phải lập bút toán điều chỉnh có lý do (BR-08)")


def _allocate(s, gd: GiaoDichTT, ma_diem_ban: str, uu_tien: str | None = None) -> list[dict]:
    """Phân bổ vào hóa đơn chỉ định trước, phần dư vào hóa đơn cũ nhất còn nợ, còn dư thì ghi số dư có."""
    _ensure_day_open(s, gd.ma_npp, gd.ngay)
    invoices = s.scalars(select(KhoanPhaiThu).where(KhoanPhaiThu.ma_diem_ban == ma_diem_ban,
                                                    KhoanPhaiThu.trang_thai != "da_tra")
                         .order_by(KhoanPhaiThu.ngay, KhoanPhaiThu.so_hoa_don).with_for_update()).all()
    invoices.sort(key=lambda i: i.so_hoa_don != uu_tien)
    remaining, out = gd.so_tien, []
    for inv in invoices:
        if remaining <= 0:
            break
        amt = min(remaining, inv.con_lai)
        existing = s.get(PhanBoTT, (gd.ma_gd, inv.so_hoa_don))
        if existing:
            existing.so_tien += amt
        else:
            s.add(PhanBoTT(ma_gd=gd.ma_gd, so_hoa_don=inv.so_hoa_don, so_tien=amt, ngay=gd.ngay))
        inv.da_tra += amt
        inv.trang_thai = "da_tra" if inv.con_lai == 0 else "tra_mot_phan"
        remaining -= amt
        out.append({"so_hoa_don": inv.so_hoa_don, "so_tien": amt, "con_lai": inv.con_lai})
    if remaining > 0:
        s.add(SoDuCo(ma_gd=gd.ma_gd, ma_diem_ban=ma_diem_ban, ma_npp=gd.ma_npp, so_tien=remaining, ngay=gd.ngay))
        out.append({"so_du_co": remaining})
    gd.ma_diem_ban, gd.trang_thai = ma_diem_ban, "da_ghi_nhan"
    s.flush()
    return out


def receive_bank_credit(s, body: dict) -> dict:
    """Webhook báo có: gạch nợ theo mã hóa đơn trong nội dung; mỗi mã giao dịch ngân hàng chỉ một lần (BR-07)."""
    if s.scalar(select(GiaoDichTT).where(GiaoDichTT.ma_gd_ngan_hang == body["ma_gd_ngan_hang"])):
        return {"trang_thai": "trung", "ma_gd_ngan_hang": body["ma_gd_ngan_hang"]}
    npp = s.scalar(select(NPP).where(NPP.so_tai_khoan == body["so_tai_khoan"]))
    if npp is None:
        raise DomainError("TAI_KHOAN_LA", "Tài khoản nhận không thuộc NPP nào")
    gd = GiaoDichTT(ma_gd=new_id("GD"), loai="VIETQR", ma_gd_ngan_hang=body["ma_gd_ngan_hang"], ma_npp=npp.ma_npp,
                    so_tien=int(body["so_tien"]), noi_dung=body.get("noi_dung", ""), ngay=clock.today(),
                    trang_thai="cho_xu_ly")
    s.add(gd)
    s.flush()
    m = MA_HD_RE.search(gd.noi_dung.upper())
    inv = s.get(KhoanPhaiThu, m.group(1)) if m else None
    if inv is None or inv.ma_npp != npp.ma_npp:
        notification.send(s, f"KT-{npp.ma_npp}", "Giao dịch chờ xử lý",
                          f"Báo có {gd.so_tien:,} đ không khớp hóa đơn: '{gd.noi_dung}'")
        return {"trang_thai": "cho_xu_ly", "ma_gd": gd.ma_gd}
    gd.gach_tu_dong = True
    phan_bo = _allocate(s, gd, inv.ma_diem_ban, inv.so_hoa_don)
    return {"trang_thai": "da_gach_no", "ma_gd": gd.ma_gd, "phan_bo": phan_bo}


def assign_pending(s, user: User, ma_gd: str, so_hoa_don: str) -> dict:
    """Kế toán chỉ định hóa đơn cho khoản báo có sai cú pháp."""
    require_role(user, KE_TOAN, KE_TOAN_TRUONG)
    gd = s.get(GiaoDichTT, ma_gd)
    inv = s.get(KhoanPhaiThu, so_hoa_don)
    if gd is None or inv is None:
        raise NotFound("giao dịch/hóa đơn", f"{ma_gd}/{so_hoa_don}")
    check_npp(user, gd.ma_npp, "giao dịch", ma_gd)
    if gd.trang_thai != "cho_xu_ly" or inv.ma_npp != gd.ma_npp:
        raise Conflict("KHONG_HOP_LE", "Giao dịch đã xử lý hoặc hóa đơn khác NPP")
    out = _allocate(s, gd, inv.ma_diem_ban, so_hoa_don)
    audit.log(s, user.ma, "chi_dinh_hoa_don", "giao_dich_tt", ma_gd, None, {"so_hoa_don": so_hoa_don})
    return {"ma_gd": ma_gd, "phan_bo": out}


def record_cash(s, user: User, so_hoa_don: str, so_tien: int, ma_bien_nhan: str) -> dict:
    """NVGH thu tiền mặt (ghi trên máy khi mất sóng; mã biên nhận do app sinh nên đồng bộ lại không trùng)."""
    require_role(user, NVGH)
    old = s.scalar(select(GiaoDichTT).where(GiaoDichTT.ma_bien_nhan == ma_bien_nhan))
    if old is not None:
        return {"trang_thai": "trung", "ma_gd": old.ma_gd}
    inv = s.get(KhoanPhaiThu, so_hoa_don)
    if inv is None:
        raise NotFound("hóa đơn", so_hoa_don)
    check_npp(user, inv.ma_npp, "hóa đơn", so_hoa_don)
    gd = GiaoDichTT(ma_gd=new_id("GD"), loai="TIEN_MAT", ma_bien_nhan=ma_bien_nhan, ma_npp=inv.ma_npp,
                    so_tien=so_tien, noi_dung=f"Tiền mặt {so_hoa_don}", ngay=clock.today(), trang_thai="cho_xu_ly",
                    ma_nguoi_thu=user.ma, gach_tu_dong=True)
    s.add(gd)
    s.flush()
    out = _allocate(s, gd, inv.ma_diem_ban, so_hoa_don)
    notification.send(s, inv.ma_diem_ban, "Biên nhận tiền mặt",
                      f"Đã nhận {so_tien:,} đ cho {so_hoa_don}, biên nhận {ma_bien_nhan}.", kenh="zalo")
    return {"trang_thai": "da_gach_no", "ma_gd": gd.ma_gd, "phan_bo": out}


def cash_handover(s, user: User, ma_nguoi_thu: str, thuc_nop: int, ngay: date | None = None) -> dict:
    """Thủ quỹ nhận tiền cuối ca, đối chiếu với tổng biên nhận đã phát hành (BR-03)."""
    require_role(user, THU_QUY)
    ngay = ngay or clock.today()
    tong = int(s.scalar(select(func.coalesce(func.sum(GiaoDichTT.so_tien), 0))
                        .where(GiaoDichTT.loai == "TIEN_MAT", GiaoDichTT.ma_nguoi_thu == ma_nguoi_thu,
                               GiaoDichTT.ngay == ngay, GiaoDichTT.ma_npp == user.ma_npp)))
    nq = NopQuy(ma_npp=user.ma_npp, ma_nvgh=ma_nguoi_thu, ngay=ngay, tong_bien_nhan=tong, thuc_nop=thuc_nop,
                chenh_lech=thuc_nop - tong, thu_quy=user.ma)
    s.add(nq)
    s.flush()
    return {"tong_bien_nhan": tong, "thuc_nop": thuc_nop, "chenh_lech": nq.chenh_lech}


# ---- Đối soát 3 nguồn và khóa sổ ------------------------------------------------------------

def reconcile(s, ma_npp: str, ngay: date) -> dict:
    day_txn = select(GiaoDichTT.ma_gd).where(GiaoDichTT.ma_npp == ma_npp, GiaoDichTT.ngay == ngay,
                                             GiaoDichTT.loai.in_(["VIETQR", "TIEN_MAT"]))
    bank = int(s.scalar(select(func.coalesce(func.sum(GiaoDichTT.so_tien), 0))
                        .where(GiaoDichTT.ma_npp == ma_npp, GiaoDichTT.ngay == ngay, GiaoDichTT.loai == "VIETQR")))
    quy = int(s.scalar(select(func.coalesce(func.sum(NopQuy.thuc_nop), 0))
                       .where(NopQuy.ma_npp == ma_npp, NopQuy.ngay == ngay)))
    phan_bo = int(s.scalar(select(func.coalesce(func.sum(PhanBoTT.so_tien), 0)).where(PhanBoTT.ma_gd.in_(day_txn))))
    du_co = int(s.scalar(select(func.coalesce(func.sum(SoDuCo.so_tien), 0)).where(SoDuCo.ma_gd.in_(day_txn))))
    cho = int(s.scalar(select(func.count()).select_from(GiaoDichTT)
                       .where(GiaoDichTT.ma_npp == ma_npp, GiaoDichTT.ngay == ngay,
                              GiaoDichTT.trang_thai == "cho_xu_ly")))
    ghi_nhan = phan_bo + du_co
    return {"ma_npp": ma_npp, "ngay": str(ngay), "ngan_hang": bank, "quy_thuc_nop": quy, "da_ghi_nhan": ghi_nhan,
            "chenh_lech": bank + quy - ghi_nhan, "giao_dich_cho_xu_ly": cho}


def close_day(s, user: User, ma_npp: str, ngay: date | None = None) -> dict:
    ngay = ngay or clock.today()
    check_npp(user, ma_npp, "NPP", ma_npp)
    r = reconcile(s, ma_npp, ngay)
    so = s.get(SoDoiSoat, (ma_npp, ngay))
    if so is not None and so.khoa_so:
        return {**r, "khoa_so": True, "lap_lai": True}
    if so is None:
        so = SoDoiSoat(ma_npp=ma_npp, ngay=ngay, ngan_hang=0, quy=0, ghi_nhan=0, chenh_lech=0)
        s.add(so)
    so.ngan_hang, so.quy, so.ghi_nhan = r["ngan_hang"], r["quy_thuc_nop"], r["da_ghi_nhan"]
    so.chenh_lech, so.cho_xu_ly = r["chenh_lech"], r["giao_dich_cho_xu_ly"]
    if r["chenh_lech"] != 0 or r["giao_dich_cho_xu_ly"]:
        notification.send(s, f"KT-{ma_npp}", "Đối soát lệch",
                          f"Ngày {ngay}: chênh lệch {r['chenh_lech']:,} đ, {r['giao_dich_cho_xu_ly']} giao dịch chờ.")
        return {**r, "khoa_so": False}
    entries = _journal(s, ma_npp, ngay)
    so.khoa_so, so.khoa_luc, so.khoa_boi = True, clock.now(), user.ma
    events.publish(s, ev.SO_DA_KHOA, {"ma_npp": ma_npp, "ngay": str(ngay), "but_toan": entries},
                   ma_su_kien=f"KHOASO-{ma_npp}-{ngay}")
    return {**r, "khoa_so": True, "so_but_toan": len(entries)}


def _journal(s, ma_npp: str, ngay: date) -> list[dict]:
    """Bút toán doanh thu và thu tiền cho phần mềm kế toán NPP (ERP công ty chỉ nhận bán cho NPP)."""
    out = []
    for inv in s.scalars(select(KhoanPhaiThu).where(KhoanPhaiThu.ma_npp == ma_npp, KhoanPhaiThu.ngay == ngay)):
        out.append(("131", "511", inv.so_tien, f"Doanh thu {inv.so_hoa_don}", inv.so_hoa_don))
    tk = {"VIETQR": "112", "TIEN_MAT": "111", "CAN_TRU": "5213"}
    rows = s.execute(select(GiaoDichTT.loai, PhanBoTT.so_hoa_don, PhanBoTT.so_tien, GiaoDichTT.ma_gd)
                     .join(GiaoDichTT, GiaoDichTT.ma_gd == PhanBoTT.ma_gd)
                     .where(GiaoDichTT.ma_npp == ma_npp, GiaoDichTT.ngay == ngay)).all()
    for loai, so_hd, amt, ma_gd in rows:
        out.append((tk[loai], "131", amt, f"Thu {so_hd} ({loai})", ma_gd))
    for no, co, amt, dg, ct in out:
        s.add(ButToan(ma_npp=ma_npp, ngay=ngay, no_tk=no, co_tk=co, so_tien=amt, dien_giai=dg, chung_tu=ct))
    return [{"no": no, "co": co, "so_tien": amt, "dien_giai": dg, "chung_tu": ct} for no, co, amt, dg, ct in out]


def adjustment_entry(s, user: User, ma_npp: str, ngay: date, no_tk: str, co_tk: str, so_tien: int,
                     ly_do: str) -> dict:
    """Sổ đã khóa không sửa: chỉ lập bút toán điều chỉnh có người, lý do (BR-08, NFR5)."""
    require_role(user, KE_TOAN_TRUONG)
    check_npp(user, ma_npp, "NPP", ma_npp)
    if not ly_do:
        raise DomainError("CAN_LY_DO", "Bút toán điều chỉnh phải có lý do")
    bt = ButToan(ma_npp=ma_npp, ngay=ngay, no_tk=no_tk, co_tk=co_tk, so_tien=so_tien, dien_giai="Điều chỉnh",
                 chung_tu=new_id("DC"), dieu_chinh=True, ly_do=ly_do, nguoi_lap=user.ma)
    s.add(bt)
    audit.log(s, user.ma, "but_toan_dieu_chinh", "but_toan", bt.chung_tu, None,
              {"ngay": str(ngay), "no": no_tk, "co": co_tk, "so_tien": so_tien, "ly_do": ly_do})
    return {"chung_tu": bt.chung_tu}


@events.subscribe(ev.SO_DA_KHOA, "ph0.integration.ke_toan_npp")
def export_journal(s, p: dict, _ma: str) -> None:
    rows = [{"ngay": p["ngay"], **e} for e in p["but_toan"]]
    integration.write_exchange_file(integration.KENH_KE_TOAN_NPP, f"BT-{p['ma_npp']}-{p['ngay']}", 1, rows)


def monthly_statement(s, user: User, ma_diem_ban: str) -> dict:
    """Sao kê công nợ: điểm bán xác nhận Đồng ý / Khiếu nại trên app (ngoài luồng chính CN3)."""
    return credit.debt_summary(s, ma_diem_ban)


# ---- CN4 tối thiểu: cấn trừ theo số kho thực nhận của vụ thu hồi -----------------------------

@events.subscribe(ev.THU_HOI_DA_NHAN, "ph3.can_tru_thu_hoi")
def on_recall_received(s, p: dict, _ma: str) -> None:
    if s.scalar(select(PhieuCanTru).where(PhieuCanTru.ma_tham_chieu == p["ma_nhiem_vu"])):
        return
    if p["so_luong"] > ph2.delivered_qty(s, p["ma_diem_ban"], p["ma_lo"]):   # BR-04 PH3
        raise DomainError("TRA_VUOT_DA_GIAO", "Số trả vượt số đã giao lô này cho điểm bán")
    price = s.scalar(select(DongPhaiThu.don_gia).join(KhoanPhaiThu, KhoanPhaiThu.so_hoa_don == DongPhaiThu.so_hoa_don)
                     .where(KhoanPhaiThu.ma_diem_ban == p["ma_diem_ban"], DongPhaiThu.ma_lo == p["ma_lo"])
                     .order_by(KhoanPhaiThu.ngay.desc()).limit(1)) or 0
    gia_tri = price * p["so_luong"]
    phieu = PhieuCanTru(ma_phieu=new_id("CT"), nguon="thu_hoi", ma_tham_chieu=p["ma_nhiem_vu"],
                        ma_diem_ban=p["ma_diem_ban"], ma_npp=p["ma_npp"], ma_lo=p["ma_lo"], ma_sp=p["ma_sp"],
                        so_luong=p["so_luong"], gia_tri=gia_tri, ngay=clock.today())
    s.add(phieu)
    if gia_tri > 0:
        gd = GiaoDichTT(ma_gd=new_id("GD"), loai="CAN_TRU", ma_npp=p["ma_npp"], so_tien=gia_tri,
                        noi_dung=f"Cấn trừ thu hồi {p['ma_vu']}", ngay=clock.today(), trang_thai="cho_xu_ly")
        s.add(gd)
        s.flush()
        hd_lo = s.scalar(select(DongPhaiThu.so_hoa_don).join(KhoanPhaiThu)
                         .where(KhoanPhaiThu.ma_diem_ban == p["ma_diem_ban"], DongPhaiThu.ma_lo == p["ma_lo"],
                                KhoanPhaiThu.trang_thai != "da_tra").limit(1))
        _allocate(s, gd, p["ma_diem_ban"], hd_lo)
    events.publish(s, ev.CAN_TRU_DA_XAC_NHAN, {"ma_phieu": phieu.ma_phieu, "ma_diem_ban": p["ma_diem_ban"],
                                               "gia_tri": gia_tri}, ma_su_kien=f"CT-{p['ma_nhiem_vu']}")


# ---- CN5 tối thiểu: nhắc nợ, giao nhiệm vụ thu nợ, nhận kết quả từ PH4 ---------------------------

def scan_overdue() -> int:
    from app.db import tx
    today = clock.today()
    n = 0
    with tx() as s:
        for inv in s.scalars(select(KhoanPhaiThu).where(KhoanPhaiThu.trang_thai != "da_tra")):
            if inv.han_tra == today + timedelta(days=1):
                notification.send(s, inv.ma_diem_ban, "Nhắc nợ",
                                  f"Hóa đơn {inv.so_hoa_don} còn {inv.con_lai:,} đ đến hạn ngày mai.", kenh="zalo")
            elif inv.han_tra < today:
                events.publish(s, ev.NHIEM_VU_THU_NO, {"ma_diem_ban": inv.ma_diem_ban, "ma_npp": inv.ma_npp,
                                                       "so_hoa_don": inv.so_hoa_don, "so_tien": inv.con_lai,
                                                       "han_tra": str(inv.han_tra)},
                               ma_su_kien=f"TN-{inv.so_hoa_don}")
                n += 1
    return n


@events.subscribe(ev.KET_QUA_THU_NO, "ph3.nhan_ket_qua_thu_no")
def on_collection_result(s, p: dict, _ma: str) -> None:
    if not p.get("so_tien_thu"):
        return
    ma_bn = f"LG-{p['ma_luot_ghe']}-{p['so_hoa_don']}"
    if s.scalar(select(GiaoDichTT).where(GiaoDichTT.ma_bien_nhan == ma_bn)):
        return
    inv = s.get(KhoanPhaiThu, p["so_hoa_don"])
    gd = GiaoDichTT(ma_gd=new_id("GD"), loai="TIEN_MAT", ma_bien_nhan=ma_bn, ma_npp=inv.ma_npp,
                    so_tien=int(p["so_tien_thu"]), noi_dung=f"NVBH thu nợ {inv.so_hoa_don}", ngay=clock.today(),
                    trang_thai="cho_xu_ly", ma_nguoi_thu=p["ma_nvbh"], gach_tu_dong=True)
    s.add(gd)
    s.flush()
    _allocate(s, gd, inv.ma_diem_ban, inv.so_hoa_don)


@events.subscribe(ev.DIEM_BAN_KICH_HOAT, "ph3.ho_so_tin_dung_mac_dinh")
def on_outlet_activated(s, p: dict, _ma: str) -> None:
    credit.init_profile(s, p["ma_diem_ban"], p["ma_npp"])
