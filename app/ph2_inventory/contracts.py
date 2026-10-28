"""Hợp đồng công khai của PH2 – các phân hệ khác chỉ được gọi PH2 qua file này.

Các hàm nhận Session của bên gọi và KHÔNG commit: bên gọi quyết định ranh giới giao dịch.
Nhờ đó PH1 giữ tồn (PH2) và trừ ngân sách KM (PH1) trong cùng một giao dịch (mục 3.2.11).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app import clock, config
from app.db import new_id
from app.errors import DomainError
from app.ph2_inventory.models import DongGiao, HangDangVe, Kho, LoHang, LuotGiuTon, PhieuXuat, TonKhoLo, TonKhoSP


@dataclass
class ReserveLine:
    ma_sp: str
    so_luong: int


@dataclass
class ReserveResult:
    ok: bool
    thieu: dict[str, int] = field(default_factory=dict)   # ma_sp -> tồn khả dụng hiện tại
    lap_lai: bool = False                                 # khóa chống trùng đã dùng: trả kết quả cũ


def sellable_cutoff(today: date) -> date:
    """Lô có HSD trước ngày này là lô đỏ (còn < 3 ngày), không bán cho điểm bán (BR-04, BR2.4)."""
    return today + timedelta(days=config.SO_NGAY_LO_DO)


def _sellable_qty(s, ma_kho: str, ma_sps: list[str], today: date) -> dict[str, int]:
    q = (select(LoHang.ma_sp, func.coalesce(func.sum(TonKhoLo.so_luong), 0))
         .join(LoHang, LoHang.ma_lo == TonKhoLo.ma_lo)
         .where(TonKhoLo.ma_kho == ma_kho, TonKhoLo.khu == "ban", LoHang.trang_thai == "binh_thuong",
                LoHang.hsd >= sellable_cutoff(today), LoHang.ma_sp.in_(ma_sps))
         .group_by(LoHang.ma_sp))
    out = {sp: 0 for sp in ma_sps}
    out.update({sp: int(qty) for sp, qty in s.execute(q).all()})
    return out


def available_map(s, ma_kho: str, ma_sps: list[str] | None = None) -> dict[str, int]:
    """Tồn khả dụng = tồn thực − đã giữ − lô đỏ − lô khóa (BR-04). Hàng đang về không được cộng."""
    rows = s.scalars(select(TonKhoSP).where(TonKhoSP.ma_kho == ma_kho)).all()
    if ma_sps is not None:
        rows = [r for r in rows if r.ma_sp in ma_sps]
    sellable = _sellable_qty(s, ma_kho, [r.ma_sp for r in rows], clock.today())
    return {r.ma_sp: max(0, sellable[r.ma_sp] - r.da_giu) for r in rows}


def lock_stock_rows(s, ma_kho: str, ma_sps) -> dict[str, TonKhoSP]:
    """Khóa dòng tồn theo thứ tự mã sản phẩm cố định để hai giỏ không chờ nhau (deadlock, Bảng 3.27)."""
    rows = {}
    for sp in sorted(set(ma_sps)):
        row = s.scalar(select(TonKhoSP).where(TonKhoSP.ma_kho == ma_kho, TonKhoSP.ma_sp == sp).with_for_update())
        if row is not None:
            rows[sp] = row
    return rows


def reserve_cart(s, ma_don: str, ma_kho: str, lines: list[ReserveLine], han_giu: datetime | None,
                 khoa_chong_trung: str) -> ReserveResult:
    """Giữ tồn cả giỏ: đủ mọi dòng thì giữ hết, thiếu một dòng thì không giữ dòng nào (BR-05, BR2.5)."""
    if s.scalar(select(LuotGiuTon).where(LuotGiuTon.khoa_chong_trung == khoa_chong_trung).limit(1)):
        return ReserveResult(ok=True, lap_lai=True)
    need: dict[str, int] = defaultdict(int)
    for ln in lines:
        if ln.so_luong <= 0:
            raise DomainError("SO_LUONG_SAI", f"Số lượng {ln.ma_sp} phải lớn hơn 0")
        need[ln.ma_sp] += ln.so_luong
    rows = lock_stock_rows(s, ma_kho, need)
    sellable = _sellable_qty(s, ma_kho, list(need), clock.today())
    avail = {sp: (sellable[sp] - rows[sp].da_giu) if sp in rows else 0 for sp in need}
    thieu = {sp: max(0, avail[sp]) for sp, q in need.items() if q > avail[sp]}
    if thieu:
        return ReserveResult(ok=False, thieu=thieu)
    for sp in sorted(need):
        rows[sp].da_giu += need[sp]
        s.add(LuotGiuTon(ma_luot=new_id("GT"), khoa_chong_trung=khoa_chong_trung, ma_don=ma_don, ma_kho=ma_kho,
                         ma_sp=sp, so_luong=need[sp], han_giu=han_giu))
    s.flush()
    # Ràng buộc tổng giữ (lớp phòng thủ): kiểm tra lại sau khi ghi, lỗi ứng dụng cũng không giữ vượt được.
    for sp in need:
        if rows[sp].da_giu > sellable[sp]:
            raise DomainError("VI_PHAM_RANG_BUOC_GIU", f"Tổng giữ vượt tồn bán được cho {sp}", status=500)
    return ReserveResult(ok=True)


def _active(s, ma_don: str, ma_sp: str | None = None):
    q = select(LuotGiuTon).where(LuotGiuTon.ma_don == ma_don, LuotGiuTon.trang_thai == "dang_giu")
    if ma_sp:
        q = q.where(LuotGiuTon.ma_sp == ma_sp)
    return s.scalars(q.order_by(LuotGiuTon.ma_sp)).all()


def set_reservation_deadline(s, ma_don: str, han_giu: datetime | None) -> None:
    """PH1 đặt hạn giữ theo trạng thái đơn (BR-06). None = giữ đến khi xuất kho."""
    for r in _active(s, ma_don):
        r.han_giu = han_giu


def release_reservation(s, ma_don: str) -> int:
    """Nhả toàn bộ lượt giữ của đơn (đơn hủy, từ chối, quá hạn). Trả về tổng số thùng đã nhả."""
    giu = _active(s, ma_don)
    if not giu:
        return 0
    rows = lock_stock_rows(s, giu[0].ma_kho, [g.ma_sp for g in giu])
    total = 0
    for g in giu:
        rows[g.ma_sp].da_giu -= g.so_luong
        total += g.so_luong
        g.trang_thai = "da_nha"
    return total


def adjust_reservation(s, ma_don: str, ma_sp: str, so_luong_moi: int) -> None:
    """Tính lại lượt giữ một dòng (cắt dòng khi thiếu hàng, sửa đơn). Chỉ cho giảm."""
    giu = _active(s, ma_don, ma_sp)
    if not giu:
        return
    g = giu[0]
    if so_luong_moi > g.so_luong:
        raise DomainError("KHONG_TANG_DUOC", "Tăng số lượng phải đặt lại để giữ tồn mới")
    row = lock_stock_rows(s, g.ma_kho, [ma_sp])[ma_sp]
    row.da_giu -= g.so_luong - so_luong_moi
    g.so_luong = so_luong_moi
    if so_luong_moi == 0:
        g.trang_thai = "da_nha"


def cancel_issue(s, ma_don: str) -> None:
    """PH1 hủy đơn đã duyệt nhưng chưa xuất: hủy phiếu đang soạn. Đã xuất thì không hủy được (BR-10)."""
    p = s.scalar(select(PhieuXuat).where(PhieuXuat.ma_don == ma_don))
    if p is None or p.trang_thai == "huy":
        return
    if p.trang_thai != "cho_soan":
        raise DomainError("DA_XUAT_KHO", "Phiếu đã xuất kho, không hủy được", status=409)
    p.trang_thai = "huy"


def reserved_qty(s, ma_don: str) -> dict[str, int]:
    return {g.ma_sp: g.so_luong for g in _active(s, ma_don)}


def kho_of_npp(s, ma_npp: str) -> list[str]:
    return list(s.scalars(select(Kho.ma_kho).where(Kho.ma_npp == ma_npp)))


def incoming_qty(s, ma_kho: str) -> dict[str, int]:
    rows = s.execute(select(HangDangVe.ma_sp, func.sum(HangDangVe.so_luong))
                     .where(HangDangVe.ma_kho == ma_kho, HangDangVe.trang_thai == "dang_ve")
                     .group_by(HangDangVe.ma_sp)).all()
    return {sp: int(q) for sp, q in rows}


def delivered_qty(s, ma_diem_ban: str, ma_lo: str) -> int:
    """Số đã giao lô này cho điểm bán – PH3 dùng kiểm tra hàng trả (BR-04 PH3)."""
    return int(s.scalar(select(func.coalesce(func.sum(DongGiao.so_luong), 0))
                        .where(DongGiao.ma_diem_ban == ma_diem_ban, DongGiao.ma_lo == ma_lo)))


def lots_delivered_to(s, ma_diem_ban: str) -> list[dict]:
    rows = s.execute(select(DongGiao.ma_lo, DongGiao.ma_sp, func.sum(DongGiao.so_luong), func.max(DongGiao.ngay))
                     .where(DongGiao.ma_diem_ban == ma_diem_ban)
                     .group_by(DongGiao.ma_lo, DongGiao.ma_sp)).all()
    return [{"ma_lo": lo, "ma_sp": sp, "so_luong": int(q), "ngay_giao_gan_nhat": str(d)} for lo, sp, q, d in rows]


def list_deliveries(s, ngay: date) -> list[dict]:
    """Dữ liệu giao hàng một ngày cho kho dữ liệu PH4 (Bảng 2.4 #14–16)."""
    rows = s.scalars(select(DongGiao).where(DongGiao.ngay == ngay)).all()
    return [{"ma_don": r.ma_don, "ma_diem_ban": r.ma_diem_ban, "ma_npp": r.ma_npp, "ma_kho": r.ma_kho,
             "ma_sp": r.ma_sp, "so_luong": r.so_luong, "don_gia": r.don_gia} for r in rows]


def delivery_status(s, ma_don: str) -> dict | None:
    p = s.scalar(select(PhieuXuat).where(PhieuXuat.ma_don == ma_don))
    return None if p is None else {"trang_thai": p.trang_thai, "ngay_giao": str(p.ngay_giao)}


def kpi_snapshot(s, ngay: date, ma_npp: str | None) -> dict:
    from app.ph2_inventory.models import DongPhieuXuat, NhatKyTruyXuat
    q = select(DongPhieuXuat).join(PhieuXuat, PhieuXuat.ma_phieu == DongPhieuXuat.ma_phieu) \
        .where(DongPhieuXuat.ma_lo_quet.is_not(None))
    if ma_npp:
        q = q.where(PhieuXuat.ma_npp == ma_npp)
    lines = s.scalars(q).all()
    fefo = None if not lines else 1 - sum(1 for l in lines if l.canh_bao_fefo) / len(lines)
    # Tỷ lệ tồn cận hạn: tồn lô vàng/đỏ trên tổng tồn bán
    q2 = select(TonKhoLo, LoHang).join(LoHang, LoHang.ma_lo == TonKhoLo.ma_lo).join(Kho, Kho.ma_kho == TonKhoLo.ma_kho) \
        .where(TonKhoLo.khu == "ban", TonKhoLo.so_luong > 0)
    if ma_npp:
        q2 = q2.where(Kho.ma_npp == ma_npp)
    tong = can_han = 0
    for ton, lo in s.execute(q2).all():
        tong += ton.so_luong
        if (lo.hsd - ngay).days < config.SO_NGAY_LO_DO + 2:
            can_han += ton.so_luong
    tx_ms = s.scalar(select(func.max(NhatKyTruyXuat.thoi_gian_ms)))
    return {"ty_le_tuan_thu_fefo": fefo, "ty_le_ton_can_han": (can_han / tong) if tong else None,
            "tg_truy_xuat_lo_ms_max": tx_ms}
