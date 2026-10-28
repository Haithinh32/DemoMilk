"""PH2 CN5 – Khóa lô, truy xuất và thu hồi (mục 3.3.9)."""
import time
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from app import clock
from app.db import new_id
from app.errors import Conflict, DomainError, NotFound
from app.ph0_platform import audit, events, notification
from app.ph0_platform import event_catalog as ev
from app.ph0_platform.identity import QA, THU_KHO, User, check_npp, require_role
from app.ph2_inventory import contracts as stock
from app.ph2_inventory.models import (DongGiao, DongPhieuXuat, Kho, LoHang, NhapKho, NhatKyTruyXuat, NhiemVuThuHoi,
                                      PhieuXuat, TonKhoLo, TonKhoSP, VuThuHoi)
from app.ph2_inventory.service import _free_lots, _shortage


def lock_lot(s, user: User, ma_lo: str, ly_do: str) -> dict:
    """Khóa có hiệu lực ngay ở mọi kho: chặn đề xuất, xuất, điều chuyển (BR2.8)."""
    require_role(user, QA)
    lo = s.get(LoHang, ma_lo)
    if lo is None:
        raise NotFound("lô", ma_lo)
    if lo.trang_thai == "khoa":
        return {"ma_lo": ma_lo, "trang_thai": "khoa", "lap_lai": True}
    kho_list = list(s.scalars(select(TonKhoLo.ma_kho).where(TonKhoLo.ma_lo == ma_lo, TonKhoLo.khu == "ban")))
    for ma_kho in sorted(kho_list):
        stock.lock_stock_rows(s, ma_kho, [lo.ma_sp])
    lo.trang_thai, lo.ly_do_khoa = "khoa", ly_do
    s.flush()
    audit.log(s, user.ma, "khoa_lo", "lo_hang", ma_lo, {"trang_thai": "binh_thuong"}, {"trang_thai": "khoa",
                                                                                        "ly_do": ly_do})
    # Phiếu đang soạn có dòng đề xuất lô này (chưa quét): chuyển sang lô khác cùng sản phẩm, hết thì báo PH1.
    chuyen = 0
    open_lines = s.execute(select(DongPhieuXuat, PhieuXuat)
                           .join(PhieuXuat, PhieuXuat.ma_phieu == DongPhieuXuat.ma_phieu)
                           .where(PhieuXuat.trang_thai == "cho_soan",
                                  func.coalesce(DongPhieuXuat.ma_lo_quet, DongPhieuXuat.ma_lo_de_xuat) == ma_lo)).all()
    for line, phieu in open_lines:
        need = line.so_luong
        candidates = _free_lots(s, phieu.ma_kho, line.ma_sp, exclude_line_id=line.id)
        s.delete(line)
        s.flush()
        for alt, free in candidates:
            take = min(need, free)
            s.add(DongPhieuXuat(ma_phieu=phieu.ma_phieu, ma_sp=line.ma_sp, ma_lo_de_xuat=alt.ma_lo, so_luong=take))
            need -= take
            chuyen += take
            if need == 0:
                break
        if need > 0:
            _shortage(s, phieu.ma_don, line.ma_sp, need, "lo_bi_qa_khoa")
    # Kho mà tổng đã giữ nay vượt tồn bán được: báo PH1 (lượt giữ theo sản phẩm nên phần lớn tự chuyển lô)
    kho_thieu = []
    for ma_kho in kho_list:
        sellable = stock._sellable_qty(s, ma_kho, [lo.ma_sp], clock.today())[lo.ma_sp]
        row = s.get(TonKhoSP, (ma_kho, lo.ma_sp))
        if row.da_giu > sellable:
            kho_thieu.append({"ma_kho": ma_kho, "ma_sp": lo.ma_sp, "thieu": row.da_giu - sellable})
    events.publish(s, ev.LO_DA_KHOA, {"ma_lo": ma_lo, "ma_sp": lo.ma_sp, "ly_do": ly_do, "kho_thieu": kho_thieu})
    return {"ma_lo": ma_lo, "trang_thai": "khoa", "dong_phieu_chuyen_lo": chuyen, "kho_thieu": kho_thieu}


def unlock_lot(s, user: User, ma_lo: str, ket_qua_kiem_nghiem: str) -> dict:
    require_role(user, QA)
    lo = s.get(LoHang, ma_lo)
    if lo is None:
        raise NotFound("lô", ma_lo)
    if s.scalar(select(VuThuHoi).where(VuThuHoi.ma_lo == ma_lo, VuThuHoi.trang_thai == "mo")):
        raise Conflict("DANG_THU_HOI", "Lô đang có vụ thu hồi mở, không mở khóa được")
    lo.trang_thai, lo.ket_qua_kiem_nghiem = "binh_thuong", ket_qua_kiem_nghiem
    audit.log(s, user.ma, "mo_khoa_lo", "lo_hang", ma_lo, {"trang_thai": "khoa"},
              {"trang_thai": "binh_thuong", "ket_qua": ket_qua_kiem_nghiem})
    return {"ma_lo": ma_lo, "trang_thai": lo.trang_thai}


def trace_forward(s, user: User, ma_lo: str) -> dict:
    """Truy xuôi: nhà máy -> kho NPP -> từng điểm bán, kèm số đã giao và còn tồn (KPI8 ≤ 5 phút)."""
    t0 = time.perf_counter()
    lo = s.get(LoHang, ma_lo)
    if lo is None:
        raise NotFound("lô", ma_lo)
    q_nhap = select(NhapKho.ma_kho, NhapKho.nguon, func.sum(NhapKho.so_luong)).where(NhapKho.ma_lo == ma_lo) \
        .group_by(NhapKho.ma_kho, NhapKho.nguon)
    q_ton = select(TonKhoLo.ma_kho, TonKhoLo.khu, TonKhoLo.so_luong).where(TonKhoLo.ma_lo == ma_lo)
    q_giao = select(DongGiao.ma_npp, DongGiao.ma_kho, DongGiao.ma_diem_ban, func.sum(DongGiao.so_luong),
                    func.min(DongGiao.ngay), func.max(DongGiao.ngay)) \
        .where(DongGiao.ma_lo == ma_lo).group_by(DongGiao.ma_npp, DongGiao.ma_kho, DongGiao.ma_diem_ban)
    npp_cua_kho = dict(s.execute(select(Kho.ma_kho, Kho.ma_npp)).all())
    if not user.cap_cong_ty:  # NPP chỉ thấy phần của mình
        q_giao = q_giao.where(DongGiao.ma_npp == user.ma_npp)
    kho = defaultdict(lambda: {"nhap": {}, "ton_ban": 0, "ton_hong": 0})
    for ma_kho, nguon, q in s.execute(q_nhap).all():
        if user.cap_cong_ty or npp_cua_kho.get(ma_kho) == user.ma_npp:
            kho[ma_kho]["nhap"][nguon] = int(q)
    for ma_kho, khu, q in s.execute(q_ton).all():
        if user.cap_cong_ty or npp_cua_kho.get(ma_kho) == user.ma_npp:
            kho[ma_kho]["ton_ban" if khu == "ban" else "ton_hong"] = q
    diem_ban = [{"ma_npp": n, "ma_kho": k, "ma_diem_ban": d, "so_luong": int(q), "tu_ngay": str(a), "den_ngay": str(b)}
                for n, k, d, q, a, b in s.execute(q_giao).all()]
    ms = (time.perf_counter() - t0) * 1000
    s.add(NhatKyTruyXuat(ma_lo=ma_lo, thoi_gian_ms=ms))
    return {"ma_lo": ma_lo, "ma_sp": lo.ma_sp, "nsx": str(lo.nsx), "hsd": str(lo.hsd), "trang_thai": lo.trang_thai,
            "kho": dict(kho), "diem_ban": diem_ban, "tong_da_giao": sum(d["so_luong"] for d in diem_ban),
            "thoi_gian_truy_xuat_ms": round(ms, 2)}


def trace_backward(s, user: User, ma_diem_ban: str) -> dict:
    from app.ph4_sales import contracts as ph4
    outlet = ph4.get_outlet(s, ma_diem_ban)
    check_npp(user, outlet.ma_npp, "điểm bán", ma_diem_ban)
    return {"ma_diem_ban": ma_diem_ban, "lo_da_nhan": stock.lots_delivered_to(s, ma_diem_ban)}


def open_recall(s, user: User, ma_lo: str, ly_do: str) -> dict:
    """QA kết luận lô lỗi: tạo vụ thu hồi, sinh nhiệm vụ thu hồi theo từng điểm bán đã nhận lô."""
    require_role(user, QA)
    lo = s.get(LoHang, ma_lo)
    if lo is None:
        raise NotFound("lô", ma_lo)
    if lo.trang_thai != "khoa":
        raise Conflict("LO_CHUA_KHOA", "Phải khóa lô trước khi thu hồi")
    if s.scalar(select(VuThuHoi).where(VuThuHoi.ma_lo == ma_lo, VuThuHoi.trang_thai == "mo")):
        raise Conflict("DA_CO_VU", "Lô đã có vụ thu hồi đang mở")
    vu = VuThuHoi(ma_vu=new_id("TH"), ma_lo=ma_lo, ly_do=ly_do)
    s.add(vu)
    s.flush()
    rows = s.execute(select(DongGiao.ma_diem_ban, DongGiao.ma_npp, DongGiao.ma_kho, func.sum(DongGiao.so_luong))
                     .where(DongGiao.ma_lo == ma_lo)
                     .group_by(DongGiao.ma_diem_ban, DongGiao.ma_npp, DongGiao.ma_kho)).all()
    for db, npp, kho, q in rows:
        s.add(NhiemVuThuHoi(ma_nhiem_vu=f"{vu.ma_vu}-{db}", ma_vu=vu.ma_vu, ma_diem_ban=db, ma_npp=npp, ma_kho=kho,
                            ma_sp=lo.ma_sp, so_luong_da_giao=int(q)))
        notification.send(s, db, "Thu hồi sản phẩm",
                          f"Lô {ma_lo} bị thu hồi. NVGH sẽ thu lại khi ghé; vui lòng ngừng bán lô này.", kenh="zalo")
    audit.log(s, user.ma, "mo_vu_thu_hoi", "vu_thu_hoi", vu.ma_vu, None, {"ma_lo": ma_lo, "so_diem_ban": len(rows)})
    return {"ma_vu": vu.ma_vu, "so_nhiem_vu": len(rows)}


def receive_recall(s, user: User, ma_nhiem_vu: str, so_luong_thuc_nhan: int) -> dict:
    """Thủ kho nhập khu hàng hỏng theo số thực nhận; số này là căn cứ để PH3 cấn trừ (BR2.10)."""
    require_role(user, THU_KHO)
    nv = s.get(NhiemVuThuHoi, ma_nhiem_vu)
    if nv is None:
        raise NotFound("nhiệm vụ thu hồi", ma_nhiem_vu)
    check_npp(user, nv.ma_npp, "nhiệm vụ thu hồi", ma_nhiem_vu)
    if nv.trang_thai == "da_nhan":
        raise Conflict("DA_NHAN", "Nhiệm vụ đã nhập kho")
    if not 0 <= so_luong_thuc_nhan <= nv.so_luong_da_giao:
        raise DomainError("SO_LUONG_SAI", "Số thực nhận phải trong khoảng 0 – số đã giao")
    vu = s.get(VuThuHoi, nv.ma_vu)
    ton = s.get(TonKhoLo, (vu.ma_lo, nv.ma_kho, "hong"))
    if ton is None:
        s.add(TonKhoLo(ma_lo=vu.ma_lo, ma_kho=nv.ma_kho, khu="hong", so_luong=so_luong_thuc_nhan))
    else:
        ton.so_luong += so_luong_thuc_nhan
    s.add(NhapKho(ma_lo=vu.ma_lo, ma_kho=nv.ma_kho, so_luong=so_luong_thuc_nhan, ngay=clock.today(), nguon="thu_hoi"))
    nv.so_luong_thu, nv.trang_thai, nv.nhan_luc = so_luong_thuc_nhan, "da_nhan", clock.now()
    if so_luong_thuc_nhan > 0:
        events.publish(s, ev.THU_HOI_DA_NHAN, {
            "ma_vu": vu.ma_vu, "ma_nhiem_vu": nv.ma_nhiem_vu, "ma_diem_ban": nv.ma_diem_ban, "ma_npp": nv.ma_npp,
            "ma_lo": vu.ma_lo, "ma_sp": nv.ma_sp, "so_luong": so_luong_thuc_nhan}, ma_su_kien=f"THN-{nv.ma_nhiem_vu}")
    return {"ma_nhiem_vu": ma_nhiem_vu, "so_luong_thu": so_luong_thuc_nhan}


def close_recall(s, user: User, ma_vu: str) -> dict:
    require_role(user, QA)
    vu = s.get(VuThuHoi, ma_vu)
    if vu is None:
        raise NotFound("vụ thu hồi", ma_vu)
    tasks = s.scalars(select(NhiemVuThuHoi).where(NhiemVuThuHoi.ma_vu == ma_vu)).all()
    da_giao = sum(t.so_luong_da_giao for t in tasks)
    han_48h = vu.mo_luc + timedelta(hours=48)
    thu_48h = sum(t.so_luong_thu or 0 for t in tasks if t.nhan_luc and t.nhan_luc <= han_48h)
    vu.ty_le_thu_48h = (thu_48h / da_giao) if da_giao else 1.0
    vu.trang_thai, vu.dong_luc = "dong", clock.now()
    return {"ma_vu": ma_vu, "ty_le_thu_48h": vu.ty_le_thu_48h,
            "chua_thu": [t.ma_diem_ban for t in tasks if t.trang_thai != "da_nhan"]}
