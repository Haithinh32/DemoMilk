"""PH1 CN2 – Đặt hàng trực tuyến và CN3 – Kiểm tra và duyệt đơn (mục 3.2.6, 3.2.7).

Ranh giới giao dịch (mục 3.2.10, 3.2.11):
  GD1 place_order:  áp giá/KM -> giữ tồn cả giỏ (PH2) -> trừ ngân sách KM -> tạo đơn   (nguyên tử)
  GD2 review_order: kiểm tra tín dụng (PH3, giữ hạn mức nếu đạt) -> duyệt tự động hoặc chờ ngoại lệ
Tín dụng cố ý nằm ngoài GD1: PH3 lỗi thì đơn vẫn có hàng, ở trạng thái chờ và được thử lại.
"""
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app import clock, config
from app.db import new_id, tx
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import audit, events, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import (DIEM_BAN, GIAM_SAT, NPP, NVBH, User, check_npp, check_outlet,
                                       require_role)
from app.ph1_order.models import ChuongTrinhKM, DongDon, DonHang, DonNhap
from app.ph1_order.pricing import PricedCart, price_cart
from app.ph2_inventory import contracts as ph2
from app.ph3_credit import contracts as ph3
from app.ph4_sales import contracts as ph4

DON_TOI_THIEU = 300_000

# Trạng thái đơn
CHO_KIEM_TRA_TD = "CHO_KIEM_TRA_TD"          # đã giữ tồn, chờ kết quả PH3
CHO_DIEM_BAN_CHON = "CHO_DIEM_BAN_CHON"      # vượt hạn mức: trả ngay hay xin ngoại lệ (30 phút)
CHO_DUYET_NGOAI_LE_TD = "CHO_DUYET_NGOAI_LE_TD"  # Kế toán trưởng duyệt (4 giờ làm việc)
CHO_NPP_DUYET = "CHO_NPP_DUYET"              # ngoại lệ chính sách (24 giờ)
DA_DUYET = "DA_DUYET"
CHO_GIAO = "CHO_GIAO"
DA_GIAO = "DA_GIAO"
DA_HUY = "DA_HUY"
DANG_CHO = {CHO_KIEM_TRA_TD, CHO_DIEM_BAN_CHON, CHO_DUYET_NGOAI_LE_TD, CHO_NPP_DUYET}


def _deadline(state: str, now: datetime) -> datetime | None:
    """BR-06: mỗi trạng thái chờ một hạn riêng, tính từ lúc vào trạng thái; các hạn nối tiếp, không chồng."""
    return {CHO_KIEM_TRA_TD: now + timedelta(hours=2),
            CHO_DIEM_BAN_CHON: now + timedelta(minutes=30),
            CHO_DUYET_NGOAI_LE_TD: clock.add_working_hours(now, 4),
            CHO_NPP_DUYET: now + timedelta(hours=24)}.get(state)


def _set_state(s, d: DonHang, state: str, ly_do: str | None = None) -> None:
    d.trang_thai = state
    d.han_trang_thai = _deadline(state, clock.now())
    if ly_do:
        d.ly_do = ly_do
    ph2.set_reservation_deadline(s, d.ma_don, d.han_trang_thai)


def _delivery_date(now: datetime):
    """BR-03: đơn trước giờ chốt giao sáng hôm sau; sau giờ chốt lùi một ngày."""
    return (now + timedelta(days=1 if now.hour < config.GIO_CHOT_DON else 2)).date()


def _load(s, ma_don: str, lock: bool = False) -> DonHang:
    q = select(DonHang).where(DonHang.ma_don == ma_don)
    d = s.scalar(q.with_for_update() if lock else q)
    if d is None:
        raise NotFound("đơn hàng", ma_don)
    return d


def _authorize_ordering(s, user: User, outlet, nguon: str) -> None:
    if user.vai_tro == DIEM_BAN:
        check_outlet(user, outlet.ma_diem_ban, outlet.ma_npp)
    elif user.vai_tro == NVBH:
        check_npp(user, outlet.ma_npp, "điểm bán", outlet.ma_diem_ban)
        # Bảng 4.3: NVBH chỉ đặt hộ khi đã check-in hợp lệ tại điểm bán (kể cả đơn ngoại tuyến đồng bộ sau)
        if not ph4.has_valid_checkin(s, user.ma, outlet.ma_diem_ban, clock.today()):
            raise DomainError("CHUA_CHECK_IN", "NVBH phải check-in tại điểm bán trước khi đặt hộ", status=403)
    else:
        require_role(user, DIEM_BAN, NVBH)
    if outlet.trang_thai != "hoat_dong":
        raise DomainError("DIEM_BAN_CHUA_KICH_HOAT", "Điểm bán chưa được duyệt hoặc đã ngừng")


# ---- CN2: hiển thị -------------------------------------------------------------------------

def catalog(s, user: User, ma_diem_ban: str) -> list[dict]:
    """Tồn khả dụng từng sản phẩm; hết hàng thì khóa nút thêm, số lượng tối đa bằng tồn khả dụng."""
    outlet = ph4.get_outlet(s, ma_diem_ban)
    check_outlet(user, ma_diem_ban, outlet.ma_npp)
    avail = ph2.available_map(s, outlet.ma_kho)
    from app.ph0_platform.models import SanPham
    items = []
    for sp in s.scalars(select(SanPham).order_by(SanPham.ma_sp)):
        quote = price_cart(s, outlet, [(sp.ma_sp, max(1, avail.get(sp.ma_sp, 0)))], clock.today()).dong[0]
        items.append({"ma_sp": sp.ma_sp, "ten": sp.ten, "don_gia": quote.don_gia, "km": quote.ma_km,
                      "muc_giam": quote.muc_giam, "ton_kha_dung": avail.get(sp.ma_sp, 0),
                      "het_hang": avail.get(sp.ma_sp, 0) == 0, "so_luong_toi_da": avail.get(sp.ma_sp, 0)})
    return items


def cart_from_suggestion(s, user: User, ma_diem_ban: str) -> dict:
    """PH4 sinh gợi ý (bộ máy gợi ý); PH1 nhận như giỏ nháp và lọc lại theo tồn khi mở (BR14)."""
    outlet = ph4.get_outlet(s, ma_diem_ban)
    check_outlet(user, ma_diem_ban, outlet.ma_npp)
    g = ph4.get_suggestion(s, ma_diem_ban, clock.today())
    if g is None:
        return {"ma_goi_y": None, "dong": []}
    avail = ph2.available_map(s, outlet.ma_kho)
    dong = [{"ma_sp": d["ma_sp"], "so_luong": min(d["so_luong"], avail.get(d["ma_sp"], 0)), "ly_do": d.get("ly_do")}
            for d in g["dong"] if avail.get(d["ma_sp"], 0) > 0]
    quote = price_cart(s, outlet, [(d["ma_sp"], d["so_luong"]) for d in dong], clock.today()) if dong else None
    return {"ma_goi_y": g["ma_goi_y"], "dong": dong, "bao_gia": quote.as_dict() if quote else None}


# ---- CN2: đặt hàng (GD1) -------------------------------------------------------------------

def place_order(s, user: User, ma_diem_ban: str, dong: list[dict], khoa_chong_trung: str, nguon: str = "app",
                bo_km: list[str] | None = None, yc_chiet_khau_pct: float = 0, ma_goi_y: str | None = None) -> DonHang:
    existing = s.scalar(select(DonHang).where(DonHang.khoa_chong_trung == khoa_chong_trung))
    if existing is not None:   # app gửi lại do mạng chập chờn: trả đơn cũ, không sinh đơn thứ hai
        return existing
    outlet = ph4.get_outlet(s, ma_diem_ban)
    _authorize_ordering(s, user, outlet, nguon)
    merged: dict[str, int] = {}
    for d in dong:
        merged[d["ma_sp"]] = merged.get(d["ma_sp"], 0) + int(d["so_luong"])
    lines = sorted(merged.items())
    if not lines:
        raise DomainError("GIO_RONG", "Giỏ hàng trống")
    cart: PricedCart = price_cart(s, outlet, lines, clock.today(), set(bo_km or []))
    if cart.tong_tien < DON_TOI_THIEU:
        raise DomainError("DUOI_DON_TOI_THIEU", f"Đơn tối thiểu {DON_TOI_THIEU:,} đ", {"tong_tien": cart.tong_tien})

    ma_don = new_id("DH")
    now = clock.now()
    res = ph2.reserve_cart(s, ma_don, outlet.ma_kho, [ph2.ReserveLine(sp, q) for sp, q in lines],
                           _deadline(CHO_KIEM_TRA_TD, now), khoa_chong_trung)
    if not res.ok:
        # Không tạo đơn; trả giỏ đã cập nhật theo tồn mới để điểm bán xác nhận lại (mục 3.2.10, lớp 2)
        raise Conflict("THIEU_HANG", "Tồn vừa thay đổi, giỏ đã được điều chỉnh",
                       {"ton_kha_dung": res.thieu,
                        "gio_cap_nhat": [{"ma_sp": sp, "so_luong": min(q, res.thieu.get(sp, q))} for sp, q in lines
                                         if res.thieu.get(sp, q) > 0]})
    # BR-11: trừ ngân sách KM bằng cập nhật có điều kiện, cùng giao dịch với giữ tồn
    for ma_km, cost in cart.km_dung.items():
        r = s.execute(update(ChuongTrinhKM)
                      .where(ChuongTrinhKM.ma_km == ma_km, ChuongTrinhKM.trang_thai == "da_duyet",
                             ChuongTrinhKM.da_dung + cost <= ChuongTrinhKM.ngan_sach)
                      .values(da_dung=ChuongTrinhKM.da_dung + cost))
        if r.rowcount == 0:
            no_km = price_cart(s, outlet, lines, clock.today(), set(bo_km or []) | {ma_km})
            raise Conflict("KM_HET_NGAN_SACH", "Chương trình vừa hết ngân sách",
                           {"ma_km": ma_km, "tong_tien_khong_km": no_km.tong_tien,
                            "goi_y": "Đặt lại với bo_km=[ma_km] để xác nhận giá không KM"})
    d = DonHang(ma_don=ma_don, khoa_chong_trung=khoa_chong_trung, ma_diem_ban=ma_diem_ban, ma_npp=outlet.ma_npp,
                ma_kho=outlet.ma_kho, nguon=nguon, nguoi_tao=user.ma, ma_goi_y=ma_goi_y, trang_thai=CHO_KIEM_TRA_TD,
                han_trang_thai=_deadline(CHO_KIEM_TRA_TD, now), yc_chiet_khau_pct=yc_chiet_khau_pct,
                tong_truoc_km=cart.tong_truoc_km, tong_km=cart.tong_km, tong_tien=cart.tong_tien,
                ngay_giao=_delivery_date(now), tao_luc=now)
    s.add(d)
    s.flush()
    for i, l in enumerate(cart.dong, 1):
        s.add(DongDon(ma_don=ma_don, stt=i, ma_sp=l.ma_sp, so_luong=l.so_luong, don_gia=l.don_gia,
                      ma_bang_gia=l.ma_bang_gia, ma_km=l.ma_km, tien_km=l.tien_km, thanh_tien=l.thanh_tien))
    events.publish(s, ev.DON_DA_TAO, {"ma_don": ma_don, "ma_diem_ban": ma_diem_ban, "ma_npp": outlet.ma_npp,
                                      "nguon": nguon, "ma_goi_y": ma_goi_y})
    return d


# ---- CN3: kiểm tra và duyệt (GD2) ------------------------------------------------------------

def review_order(s, ma_don: str) -> str:
    d = _load(s, ma_don, lock=True)
    if d.trang_thai != CHO_KIEM_TRA_TD:
        return d.trang_thai
    r = ph3.check_credit(s, d.ma_don, d.ma_diem_ban, d.tong_tien)
    if r.ket_qua == ph3.DAT:
        d.hinh_thuc_tt = "cong_no"
        _apply_policy(s, d)
    elif r.ket_qua == ph3.CHI_TRA_NGAY:
        # BR-02 PH3: có nợ quá hạn hoặc chưa được mua chịu -> chỉ trả khi nhận hàng; vẫn bán được
        d.hinh_thuc_tt = "tra_ngay"
        notification.send(s, d.ma_diem_ban, "Đơn trả tiền khi nhận", f"Đơn {d.ma_don}: {r.ly_do}. Thanh toán khi nhận hàng.")
        _apply_policy(s, d)
    else:
        _set_state(s, d, CHO_DIEM_BAN_CHON, r.ly_do)
        notification.send(s, d.ma_diem_ban, "Đơn vượt hạn mức",
                          f"Đơn {d.ma_don} vượt hạn mức ({r.ly_do}). Chọn trả ngay hoặc xin ngoại lệ trong 30 phút.",
                          kenh="zalo")
    return d.trang_thai


def _apply_policy(s, d: DonHang) -> None:
    """Đơn không có ngoại lệ chính sách thì duyệt tự động; chiết khấu ngoài quy định hoặc vượt ngưỡng -> NPP."""
    if d.yc_chiet_khau_pct > 0 or d.tong_tien > config.NGUONG_GIA_TRI_DON_NPP_DUYET:
        _set_state(s, d, CHO_NPP_DUYET, "ngoai_le_chinh_sach")
        notification.send(s, d.ma_npp, "Đơn chờ NPP duyệt", f"Đơn {d.ma_don} cần duyệt trong 24 giờ.")
    else:
        _approve(s, d, auto=True)


def _approve(s, d: DonHang, auto: bool) -> None:
    d.trang_thai, d.han_trang_thai = DA_DUYET, None
    d.duyet_luc, d.tu_dong_duyet = clock.now(), auto
    ph2.set_reservation_deadline(s, d.ma_don, None)   # đơn đã duyệt giữ tồn đến khi xuất
    lines = s.scalars(select(DongDon).where(DongDon.ma_don == d.ma_don, DongDon.so_luong > 0)).all()
    events.publish(s, ev.DON_DA_DUYET, {"ma_don": d.ma_don, "ma_npp": d.ma_npp, "ma_kho": d.ma_kho,
                                        "ma_diem_ban": d.ma_diem_ban, "ngay_giao": d.ngay_giao.isoformat(),
                                        "dong": [{"ma_sp": l.ma_sp, "so_luong": l.so_luong} for l in lines]},
                   ma_su_kien=f"DUYET-{d.ma_don}")
    notification.send(s, d.ma_diem_ban, "Đơn đã duyệt", f"Đơn {d.ma_don} giao ngày {d.ngay_giao:%d/%m}.", kenh="zalo")


def credit_choice(s, user: User, ma_don: str, lua_chon: str, ly_do: str | None = None) -> str:
    d = _load(s, ma_don, lock=True)
    check_outlet(user, d.ma_diem_ban, d.ma_npp) if user.vai_tro == DIEM_BAN else check_npp(user, d.ma_npp, "đơn", ma_don)
    if d.trang_thai != CHO_DIEM_BAN_CHON:
        raise Conflict("SAI_TRANG_THAI", f"Đơn đang ở {d.trang_thai}")
    if lua_chon == "tra_ngay":
        d.hinh_thuc_tt = "tra_ngay"
        _apply_policy(s, d)
    elif lua_chon == "xin_ngoai_le":
        require_role(user, DIEM_BAN, GIAM_SAT, NVBH)
        if not ly_do:
            raise DomainError("CAN_LY_DO", "Yêu cầu ngoại lệ phải có lý do")
        han = _deadline(CHO_DUYET_NGOAI_LE_TD, clock.now())
        ph3.request_exception(s, d.ma_don, d.ma_diem_ban, d.ma_npp, d.tong_tien, ly_do, user.ma, han)
        _set_state(s, d, CHO_DUYET_NGOAI_LE_TD)
    else:
        raise DomainError("LUA_CHON_SAI", "lua_chon phải là tra_ngay hoặc xin_ngoai_le")
    return d.trang_thai


@events.subscribe(ev.NGOAI_LE_DA_QUYET, "ph1.nhan_ket_qua_ngoai_le")
def on_exception_decided(s, p: dict, _ma: str) -> None:
    d = _load(s, p["ma_don"], lock=True)
    if d.trang_thai != CHO_DUYET_NGOAI_LE_TD:
        return
    if p["duyet"]:
        d.hinh_thuc_tt = "cong_no"
        _apply_policy(s, d)
    else:
        _cancel(s, d, f"ngoai_le_tin_dung_bi_tu_choi: {p.get('ly_do') or ''}")


def npp_decide(s, user: User, ma_don: str, duyet: bool, ly_do: str | None = None) -> str:
    require_role(user, NPP)
    d = _load(s, ma_don, lock=True)
    check_npp(user, d.ma_npp, "đơn hàng", ma_don)
    if d.trang_thai != CHO_NPP_DUYET:
        raise Conflict("SAI_TRANG_THAI", f"Đơn đang ở {d.trang_thai}")
    if duyet:
        _approve(s, d, auto=False)
    else:
        if not ly_do:
            raise DomainError("CAN_LY_DO", "Từ chối phải ghi lý do")
        _cancel(s, d, f"npp_tu_choi: {ly_do}")
    audit.log(s, user.ma, "npp_duyet_don" if duyet else "npp_tu_choi_don", "don_hang", ma_don, None,
              {"ly_do": ly_do})
    return d.trang_thai


# ---- Hủy (L3) và các tác vụ hạn ------------------------------------------------------------

def _cancel(s, d: DonHang, ly_do: str) -> None:
    """Nhả tồn, hoàn ngân sách KM và trả hạn mức trong cùng một giao dịch (BR-06, BR-11, BR-05 PH3)."""
    if d.trang_thai in (CHO_GIAO, DA_GIAO):
        raise Conflict("DA_XUAT_KHO", "Đơn đã xuất kho không được hủy (BR-10); phần không nhận xử lý như hàng trả")
    if d.trang_thai == DA_HUY:
        return
    ph2.cancel_issue(s, d.ma_don)
    ph2.release_reservation(s, d.ma_don)
    for l in s.scalars(select(DongDon).where(DongDon.ma_don == d.ma_don, DongDon.ma_km.is_not(None))):
        s.execute(update(ChuongTrinhKM).where(ChuongTrinhKM.ma_km == l.ma_km)
                  .values(da_dung=ChuongTrinhKM.da_dung - l.tien_km))
    ph3.release_hold(s, d.ma_don)
    d.trang_thai, d.han_trang_thai, d.ly_do = DA_HUY, None, ly_do
    events.publish(s, ev.DON_DA_HUY, {"ma_don": d.ma_don, "ma_diem_ban": d.ma_diem_ban, "ly_do": ly_do})
    notification.send(s, d.ma_diem_ban, "Đơn đã hủy", f"Đơn {d.ma_don} đã hủy: {ly_do}", kenh="zalo")


def cancel_order(s, user: User, ma_don: str, ly_do: str) -> str:
    d = _load(s, ma_don, lock=True)
    if user.vai_tro == DIEM_BAN:
        check_outlet(user, d.ma_diem_ban, d.ma_npp)
    else:
        require_role(user, NVBH, NPP)
        check_npp(user, d.ma_npp, "đơn hàng", ma_don)
    _cancel(s, d, f"huy_boi_{user.vai_tro}: {ly_do}")
    return d.trang_thai


def expire_orders() -> list[str]:
    """Quét đơn quá hạn: chỉ hủy nếu trạng thái hiện tại vẫn đúng là trạng thái của bộ đếm (mục 3.2.2)."""
    now = clock.now()
    with tx() as s:
        ids = list(s.scalars(select(DonHang.ma_don).where(DonHang.trang_thai.in_(DANG_CHO),
                                                          DonHang.han_trang_thai < now)))
    cancelled = []
    for ma in ids:
        with tx() as s:
            d = _load(s, ma, lock=True)
            if d.trang_thai in DANG_CHO and d.han_trang_thai and d.han_trang_thai < now:
                if d.trang_thai == CHO_DUYET_NGOAI_LE_TD:
                    ph3.expire_exception(s, d.ma_don)
                _cancel(s, d, f"qua_han_{d.trang_thai.lower()}")
                cancelled.append(ma)
    return cancelled


def retry_credit_checks() -> int:
    """PH3 tạm thời không phản hồi: đơn giữ ở Chờ kiểm tra tín dụng và được thử lại, không tự duyệt mua chịu."""
    with tx() as s:
        ids = list(s.scalars(select(DonHang.ma_don).where(DonHang.trang_thai == CHO_KIEM_TRA_TD)))
    for ma in ids:
        try:
            with tx() as s:
                review_order(s, ma)
        except Exception:  # noqa: BLE001
            continue
    return len(ids)


def place_and_review(user: User, **kwargs) -> dict:
    """GD1 rồi GD2; lỗi ở GD2 không làm mất đơn đã giữ tồn."""
    from sqlalchemy.exc import IntegrityError
    try:
        with tx() as s:
            ma_don = place_order(s, user, **kwargs).ma_don
    except IntegrityError:
        # Hai request cùng khóa chống trùng chạy song song: UNIQUE chặn bản thứ hai, trả đơn của bản đầu
        with tx() as s:
            d = s.scalar(select(DonHang).where(DonHang.khoa_chong_trung == kwargs["khoa_chong_trung"]))
            if d is None:
                raise
            ma_don = d.ma_don
    try:
        with tx() as s:
            review_order(s, ma_don)
    except Exception:  # noqa: BLE001 - để retry_credit_checks thử lại
        pass
    with tx() as s:
        return order_detail(s, user, ma_don)


def order_detail(s, user: User, ma_don: str) -> dict:
    d = _load(s, ma_don)
    if user.vai_tro == DIEM_BAN:
        check_outlet(user, d.ma_diem_ban, d.ma_npp)
    else:
        check_npp(user, d.ma_npp, "đơn hàng", ma_don)
    lines = s.scalars(select(DongDon).where(DongDon.ma_don == ma_don).order_by(DongDon.stt)).all()
    return {"ma_don": d.ma_don, "ma_diem_ban": d.ma_diem_ban, "ma_npp": d.ma_npp, "trang_thai": d.trang_thai,
            "han_trang_thai": d.han_trang_thai.isoformat() if d.han_trang_thai else None,
            "hinh_thuc_tt": d.hinh_thuc_tt, "nguon": d.nguon, "tong_truoc_km": d.tong_truoc_km, "tong_km": d.tong_km,
            "tong_tien": d.tong_tien, "ngay_giao": d.ngay_giao.isoformat(), "tu_dong_duyet": d.tu_dong_duyet,
            "ly_do": d.ly_do, "giao_hang": ph2.delivery_status(s, ma_don),
            "dong": [{"ma_sp": l.ma_sp, "so_luong": l.so_luong, "don_gia": l.don_gia, "ma_bang_gia": l.ma_bang_gia,
                      "ma_km": l.ma_km, "tien_km": l.tien_km, "thanh_tien": l.thanh_tien} for l in lines]}


def list_orders(s, user: User, trang_thai: str | None = None, limit: int = 50) -> list[dict]:
    q = select(DonHang).order_by(DonHang.tao_luc.desc()).limit(min(limit, 200))
    if user.vai_tro == DIEM_BAN:
        q = q.where(DonHang.ma_diem_ban == user.ma_diem_ban)
    elif not user.cap_cong_ty:
        q = q.where(DonHang.ma_npp == user.ma_npp)
    if trang_thai:
        q = q.where(DonHang.trang_thai == trang_thai)
    return [{"ma_don": d.ma_don, "ma_diem_ban": d.ma_diem_ban, "trang_thai": d.trang_thai, "tong_tien": d.tong_tien,
             "nguon": d.nguon, "tao_luc": d.tao_luc.isoformat()} for d in s.scalars(q)]


# ---- Agent Zalo: xác nhận đơn nháp --------------------------------------------------------

def confirm_agent_draft(user: User, ma_nhap: str) -> dict:
    """Điểm bán bấm xác nhận trên Zalo: đơn nháp đi qua đúng luồng đặt hàng như đơn app."""
    with tx() as s:
        dn = s.get(DonNhap, ma_nhap)
        if dn is None or (user.vai_tro == DIEM_BAN and dn.ma_diem_ban != user.ma_diem_ban):
            raise NotFound("đơn nháp", ma_nhap)
        if dn.trang_thai == "da_dat":
            return order_detail(s, user, dn.ma_don)
        if dn.han < clock.now():
            dn.trang_thai = "het_han"
            raise Conflict("DON_NHAP_HET_HAN", "Đơn nháp quá 30 phút, vui lòng tạo lại")
        dong, ma_diem_ban = list(dn.dong), dn.ma_diem_ban
    result = place_and_review(user, ma_diem_ban=ma_diem_ban, dong=dong, khoa_chong_trung=f"AGENT-{ma_nhap}",
                              nguon="agent")
    with tx() as s:
        dn = s.get(DonNhap, ma_nhap)
        dn.trang_thai, dn.ma_don = "da_dat", result["ma_don"]
    return result


# ---- Sự kiện từ PH2 ------------------------------------------------------------------------

@events.subscribe(ev.THIEU_HANG_KHI_SOAN, "ph1.cat_dong_thieu_hang")
def on_shortage(s, p: dict, _ma: str) -> None:
    """Kho báo thiếu khi soạn: cắt dòng, tính lại tiền và KM, trả hạn mức phần chênh (L3)."""
    d = _load(s, p["ma_don"], lock=True)
    if d.trang_thai in (DA_HUY, CHO_GIAO, DA_GIAO):
        return
    line = s.scalar(select(DongDon).where(DongDon.ma_don == d.ma_don, DongDon.ma_sp == p["ma_sp"]))
    if line is None:
        return
    new_qty = max(0, line.so_luong - p["so_luong_thieu"])
    new_km = 0
    if line.ma_km:
        km = s.get(ChuongTrinhKM, line.ma_km)
        if new_qty >= km.sl_toi_thieu and line.so_luong:
            new_km = round(line.tien_km * new_qty / line.so_luong)
        s.execute(update(ChuongTrinhKM).where(ChuongTrinhKM.ma_km == line.ma_km)
                  .values(da_dung=ChuongTrinhKM.da_dung - (line.tien_km - new_km)))
        if new_km == 0:
            line.ma_km = None
    line.so_luong, line.tien_km = new_qty, new_km
    line.thanh_tien = line.don_gia * new_qty - new_km
    lines = s.scalars(select(DongDon).where(DongDon.ma_don == d.ma_don)).all()
    d.tong_truoc_km = sum(l.don_gia * l.so_luong for l in lines)
    d.tong_km = sum(l.tien_km for l in lines)
    d.tong_tien = d.tong_truoc_km - d.tong_km
    if d.tong_tien == 0:
        _cancel(s, d, "het_hang_khi_soan")
        return
    if d.hinh_thuc_tt == "cong_no":
        ph3.adjust_hold(s, d.ma_don, d.tong_tien)
    notification.send(s, d.ma_diem_ban, "Đơn được điều chỉnh",
                      f"Đơn {d.ma_don}: {p['ma_sp']} thiếu {p['so_luong_thieu']} thùng, đã cắt dòng. "
                      f"Tổng mới {d.tong_tien:,} đ.", kenh="zalo")


@events.subscribe(ev.DON_CHO_GIAO, "ph1.trang_thai_cho_giao")
def on_issued(s, p: dict, _ma: str) -> None:
    d = _load(s, p["ma_don"])
    if d.trang_thai == DA_DUYET:
        d.trang_thai = CHO_GIAO


@events.subscribe(ev.DON_DA_GIAO, "ph1.trang_thai_da_giao")
def on_delivered(s, p: dict, _ma: str) -> None:
    _load(s, p["ma_don"]).trang_thai = DA_GIAO


@events.subscribe(ev.LO_DA_KHOA, "ph1.bao_lo_khoa")
def on_lot_locked(s, p: dict, _ma: str) -> None:
    for k in p.get("kho_thieu", []):
        notification.send(s, k["ma_kho"], "Lô bị khóa làm thiếu hàng",
                          f"Lô {p['ma_lo']} bị khóa: kho {k['ma_kho']} thiếu {k['thieu']} thùng {k['ma_sp']} "
                          f"cho đơn đã giữ. Kiểm tra đơn chờ xuất.")
