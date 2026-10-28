"""PH2 CN2 – Giữ tồn và xuất kho FEFO (phần xuất kho), cộng bản tối thiểu của CN4 (xác nhận giao)
vì sự kiện "Đã giao" là đầu vào bắt buộc của PH3 CN3 và PH4."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select

from app import clock
from app.db import new_id
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import events, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import NVGH, THU_KHO, User, check_npp, require_role
from app.ph1_order import contracts as ph1
from app.ph2_inventory import contracts as stock
from app.ph2_inventory.models import (DongGiao, DongPhieuXuat, LoHang, LuotGiuTon, NhapKho, PhieuXuat, TonKhoLo,
                                      XacNhanGiao)

LY_DO_DOI_LO = {"vi_tri_kho_lay", "bao_bi_mop", "lo_de_xuat_khong_thay", "khac"}


def _free_lots(s, ma_kho: str, ma_sp: str, exclude_line_id: int | None = None):
    """Lô bán được theo FEFO và số còn trống (tồn thực − phần đã đề xuất cho phiếu đang soạn)."""
    cutoff = stock.sellable_cutoff(clock.today())
    lots = s.execute(select(LoHang, TonKhoLo.so_luong)
                     .join(TonKhoLo, TonKhoLo.ma_lo == LoHang.ma_lo)
                     .where(TonKhoLo.ma_kho == ma_kho, TonKhoLo.khu == "ban", LoHang.ma_sp == ma_sp,
                            LoHang.trang_thai == "binh_thuong", LoHang.hsd >= cutoff, TonKhoLo.so_luong > 0)
                     .order_by(LoHang.hsd, LoHang.ma_lo)).all()
    lot_expr = func.coalesce(DongPhieuXuat.ma_lo_quet, DongPhieuXuat.ma_lo_de_xuat)
    pending = select(lot_expr, func.sum(DongPhieuXuat.so_luong)) \
        .join(PhieuXuat, PhieuXuat.ma_phieu == DongPhieuXuat.ma_phieu) \
        .where(PhieuXuat.ma_kho == ma_kho, PhieuXuat.trang_thai == "cho_soan", DongPhieuXuat.ma_sp == ma_sp)
    if exclude_line_id is not None:
        pending = pending.where(DongPhieuXuat.id != exclude_line_id)
    used = dict(s.execute(pending.group_by(lot_expr)).all())
    return [(lo, qty - int(used.get(lo.ma_lo, 0))) for lo, qty in lots if qty - int(used.get(lo.ma_lo, 0)) > 0]


def _shortage(s, ma_don: str, ma_sp: str, thieu: int, ly_do: str) -> None:
    giu = stock.reserved_qty(s, ma_don).get(ma_sp, 0)
    stock.adjust_reservation(s, ma_don, ma_sp, max(0, giu - thieu))
    events.publish(s, ev.THIEU_HANG_KHI_SOAN, {"ma_don": ma_don, "ma_sp": ma_sp, "so_luong_thieu": thieu,
                                               "ly_do": ly_do})


@events.subscribe(ev.DON_DA_DUYET, "ph2.lap_phieu_xuat")
def on_order_approved(s, p: dict, ma_su_kien: str) -> None:
    """Nhận lệnh xuất kho của đơn đã duyệt, đề xuất lô FEFO, loại lô đỏ và lô khóa (BR2.4, BR2.8)."""
    if s.scalar(select(PhieuXuat).where(PhieuXuat.ma_don == p["ma_don"])):
        return
    phieu = PhieuXuat(ma_phieu=new_id("PX"), ma_don=p["ma_don"], ma_kho=p["ma_kho"], ma_npp=p["ma_npp"],
                      ma_diem_ban=p["ma_diem_ban"], ngay_giao=datetime.fromisoformat(p["ngay_giao"]).date(),
                      trang_thai="cho_soan")
    s.add(phieu)
    s.flush()
    stock.lock_stock_rows(s, p["ma_kho"], [d["ma_sp"] for d in p["dong"]])
    for d in sorted(p["dong"], key=lambda x: x["ma_sp"]):
        need = d["so_luong"]
        for lo, free in _free_lots(s, p["ma_kho"], d["ma_sp"]):
            take = min(need, free)
            s.add(DongPhieuXuat(ma_phieu=phieu.ma_phieu, ma_sp=d["ma_sp"], ma_lo_de_xuat=lo.ma_lo, so_luong=take))
            s.flush()
            need -= take
            if need == 0:
                break
        if need > 0:
            _shortage(s, p["ma_don"], d["ma_sp"], need, "lo_bi_khoa_hoac_xuong_do_sau_khi_giu")


def pick_list(s, user: User, ma_phieu: str) -> dict:
    p = s.get(PhieuXuat, ma_phieu)
    if p is None:
        raise NotFound("phiếu xuất", ma_phieu)
    check_npp(user, p.ma_npp, "phiếu xuất", ma_phieu)
    lines = s.scalars(select(DongPhieuXuat).where(DongPhieuXuat.ma_phieu == ma_phieu)).all()
    return {"ma_phieu": p.ma_phieu, "ma_don": p.ma_don, "trang_thai": p.trang_thai, "ma_kho": p.ma_kho,
            "dong": [{"id": l.id, "ma_sp": l.ma_sp, "ma_lo_de_xuat": l.ma_lo_de_xuat, "so_luong": l.so_luong,
                      "ma_lo_quet": l.ma_lo_quet, "doi_lo": l.doi_lo, "canh_bao_fefo": l.canh_bao_fefo}
                     for l in lines]}


def scan_lot(s, user: User, ma_phieu: str, dong_id: int, ma_lo_quet: str, ly_do: str | None = None) -> dict:
    """Quét lô khi soạn (BR2.3): sai lô bị chặn, đổi lô phải có lý do và được tính vào tuân thủ FEFO."""
    require_role(user, THU_KHO)
    p = s.get(PhieuXuat, ma_phieu)
    if p is None:
        raise NotFound("phiếu xuất", ma_phieu)
    check_npp(user, p.ma_npp, "phiếu xuất", ma_phieu)
    line = s.get(DongPhieuXuat, dong_id)
    if line is None or line.ma_phieu != ma_phieu or p.trang_thai != "cho_soan":
        raise NotFound("dòng phiếu xuất", str(dong_id))
    free = {lo.ma_lo: (lo, q) for lo, q in _free_lots(s, p.ma_kho, line.ma_sp, exclude_line_id=line.id)}
    if ma_lo_quet not in free or free[ma_lo_quet][1] < line.so_luong:
        raise Conflict("LO_KHONG_HOP_LE", "Lô quét không cùng sản phẩm/kho, hết hạn bán, bị khóa hoặc không đủ số lượng",
                       {"ma_lo_quet": ma_lo_quet})
    canh_bao = False
    if ma_lo_quet != line.ma_lo_de_xuat:
        if ly_do not in LY_DO_DOI_LO:
            raise DomainError("CAN_LY_DO_DOI_LO", "Đổi lô phải chọn lý do", {"danh_muc": sorted(LY_DO_DOI_LO)})
        de_xuat = s.get(LoHang, line.ma_lo_de_xuat)
        canh_bao = free[ma_lo_quet][0].hsd > de_xuat.hsd
        line.doi_lo, line.ly_do_doi = True, ly_do
    line.ma_lo_quet, line.canh_bao_fefo, line.quet_boi = ma_lo_quet, canh_bao, user.ma
    return {"id": line.id, "ma_lo_quet": ma_lo_quet, "canh_bao_fefo": canh_bao,
            "thong_bao": "Lô quét có hạn dùng xa hơn lô đề xuất – lô cũ hơn sẽ bị để lại" if canh_bao else None}


def report_pick_shortage(s, user: User, ma_phieu: str, dong_id: int, so_luong_thieu: int, ly_do: str) -> None:
    """Thủ kho báo thiếu khi soạn (hư hỏng, lệch kiểm kê): PH1 cắt dòng hoặc thay thế (L3)."""
    require_role(user, THU_KHO)
    p = s.get(PhieuXuat, ma_phieu)
    line = s.get(DongPhieuXuat, dong_id)
    if p is None or line is None or line.ma_phieu != ma_phieu:
        raise NotFound("dòng phiếu xuất", str(dong_id))
    check_npp(user, p.ma_npp, "phiếu xuất", ma_phieu)
    thieu = min(so_luong_thieu, line.so_luong)
    line.so_luong -= thieu
    if line.so_luong == 0:
        s.delete(line)
    _shortage(s, p.ma_don, line.ma_sp, thieu, ly_do)


def confirm_issue(s, user: User, ma_phieu: str) -> dict:
    """Xác nhận xuất: trừ tồn thực theo lô đã quét, đóng lượt giữ, đơn sang 'Chờ giao'."""
    require_role(user, THU_KHO)
    p = s.get(PhieuXuat, ma_phieu)
    if p is None:
        raise NotFound("phiếu xuất", ma_phieu)
    check_npp(user, p.ma_npp, "phiếu xuất", ma_phieu)
    if p.trang_thai != "cho_soan":
        raise Conflict("SAI_TRANG_THAI", f"Phiếu đang ở trạng thái {p.trang_thai}")
    lines = s.scalars(select(DongPhieuXuat).where(DongPhieuXuat.ma_phieu == ma_phieu)).all()
    if any(l.ma_lo_quet is None for l in lines):
        raise Conflict("CHUA_QUET_DU", "Còn dòng chưa quét lô")
    rows = stock.lock_stock_rows(s, p.ma_kho, [l.ma_sp for l in lines])
    for l in lines:
        ton = s.get(TonKhoLo, (l.ma_lo_quet, p.ma_kho, "ban"))
        if ton is None or ton.so_luong < l.so_luong:
            raise Conflict("TON_LO_KHONG_DU", f"Lô {l.ma_lo_quet} không đủ tồn thực")
        ton.so_luong -= l.so_luong
    for g in s.scalars(select(LuotGiuTon).where(LuotGiuTon.ma_don == p.ma_don,
                                                LuotGiuTon.trang_thai == "dang_giu")).all():
        rows[g.ma_sp].da_giu -= g.so_luong
        g.trang_thai = "da_xuat"
    p.trang_thai, p.xuat_luc = "da_xuat", clock.now()
    events.publish(s, ev.DON_CHO_GIAO, {"ma_don": p.ma_don, "ma_phieu": p.ma_phieu})
    return {"ma_phieu": p.ma_phieu, "trang_thai": p.trang_thai}


def confirm_delivery(s, user: User, ma_phieu: str, dong: list[dict], bang_chung: dict, ma_su_kien: str) -> dict:
    """Xác nhận giao (CN4 tối thiểu): BR2.7 – cần ảnh hoặc chữ ký và lô thực giao; mã sự kiện chống ghi trùng."""
    require_role(user, NVGH)
    if s.get(XacNhanGiao, ma_su_kien) is not None:
        return {"ma_su_kien": ma_su_kien, "lap_lai": True}
    p = s.get(PhieuXuat, ma_phieu)
    if p is None:
        raise NotFound("phiếu xuất", ma_phieu)
    check_npp(user, p.ma_npp, "phiếu xuất", ma_phieu)
    if p.trang_thai != "da_xuat":
        raise Conflict("SAI_TRANG_THAI", f"Phiếu đang ở trạng thái {p.trang_thai}")
    if not (bang_chung.get("anh_url") or bang_chung.get("chu_ky")):
        raise DomainError("THIEU_BANG_CHUNG", "Đơn chỉ 'Đã giao' khi có ảnh hoặc chữ ký (BR2.7)")
    issued: dict[tuple[str, str], int] = defaultdict(int)
    for l in s.scalars(select(DongPhieuXuat).where(DongPhieuXuat.ma_phieu == ma_phieu)).all():
        issued[(l.ma_sp, l.ma_lo_quet)] += l.so_luong
    delivered: dict[tuple[str, str], int] = defaultdict(int)
    for d in dong:
        key = (d["ma_sp"], d["ma_lo"])
        if key not in issued:
            raise DomainError("LO_KHONG_THUOC_PHIEU", f"Lô {d['ma_lo']} không có trong phiếu xuất")
        delivered[key] += d["so_luong"]
        if delivered[key] > issued[key] or d["so_luong"] < 0:
            raise DomainError("GIAO_VUOT", f"Số giao lô {d['ma_lo']} vượt số đã xuất")
    s.add(XacNhanGiao(ma_su_kien=ma_su_kien, ma_phieu=ma_phieu, ma_don=p.ma_don, ma_nvgh=user.ma,
                      bang_chung=bang_chung))
    s.flush()
    prices = ph1.order_line_prices(s, p.ma_don)
    out_lines = []
    for (sp, lo), q in issued.items():
        giao = delivered.get((sp, lo), 0)
        if giao < q:  # hàng mang về nhập lại đúng lô cũ
            ton = s.get(TonKhoLo, (lo, p.ma_kho, "ban"))
            ton.so_luong += q - giao
            s.add(NhapKho(ma_lo=lo, ma_kho=p.ma_kho, so_luong=q - giao, ngay=clock.today(), nguon="tra_lai"))
        if giao > 0:
            s.add(DongGiao(ma_su_kien=ma_su_kien, ma_don=p.ma_don, ma_diem_ban=p.ma_diem_ban, ma_npp=p.ma_npp,
                           ma_kho=p.ma_kho, ma_sp=sp, ma_lo=lo, so_luong=giao, don_gia=prices[sp],
                           ngay=clock.today()))
            out_lines.append({"ma_sp": sp, "ma_lo": lo, "so_luong": giao, "don_gia": prices[sp]})
    p.trang_thai = "da_giao"
    info = ph1.order_info(s, p.ma_don)
    events.publish(s, ev.DON_DA_GIAO, {
        "ma_don": p.ma_don, "ma_diem_ban": p.ma_diem_ban, "ma_npp": p.ma_npp,
        "hinh_thuc_tt": info["hinh_thuc_tt"], "gia_tri": sum(l["so_luong"] * l["don_gia"] for l in out_lines),
        "dong": out_lines}, ma_su_kien=f"GIAO-{ma_su_kien}")
    notification.send(s, p.ma_diem_ban, "Đơn đã giao", f"Đơn {p.ma_don} đã được giao.", kenh="zalo")
    return {"ma_su_kien": ma_su_kien, "ma_don": p.ma_don, "dong": out_lines}


def expire_reservations(grace_minutes: int = 5) -> int:
    """Lưới an toàn: nhả lượt giữ quá hạn mà PH1 chưa xử lý (PH1 quét trước, theo trạng thái đơn)."""
    from datetime import timedelta
    from app.db import tx
    cutoff = clock.now() - timedelta(minutes=grace_minutes)
    with tx() as s:
        dons = set(s.scalars(select(LuotGiuTon.ma_don).where(LuotGiuTon.trang_thai == "dang_giu",
                                                             LuotGiuTon.han_giu.is_not(None),
                                                             LuotGiuTon.han_giu < cutoff)))
        for ma_don in dons:
            stock.release_reservation(s, ma_don)
        return len(dons)
