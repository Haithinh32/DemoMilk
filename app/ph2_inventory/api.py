from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.db import tx
from app.ph0_platform.identity import User, check_npp, current_user
from app.ph2_inventory import contracts, recall, service
from app.ph2_inventory.models import DeXuatDieuChuyen, Kho, NhiemVuThuHoi, PhieuXuat

router = APIRouter(prefix="/ph2", tags=["PH2 – Kho theo lô, Giao hàng"])


@router.get("/stock/{ma_kho}")
def stock(ma_kho: str, user: User = Depends(current_user)):
    """Tra cứu tồn khả dụng theo kho (tiện ích của CN2)."""
    with tx() as s:
        kho = s.get(Kho, ma_kho)
        check_npp(user, kho.ma_npp if kho else "", "kho", ma_kho)
        return {"ma_kho": ma_kho, "ton_kha_dung": contracts.available_map(s, ma_kho),
                "hang_dang_ve": contracts.incoming_qty(s, ma_kho)}


@router.get("/pick-lists")
def pick_lists(trang_thai: str = "cho_soan", user: User = Depends(current_user)):
    with tx() as s:
        q = select(PhieuXuat).where(PhieuXuat.trang_thai == trang_thai)
        if not user.cap_cong_ty:
            q = q.where(PhieuXuat.ma_npp == user.ma_npp)
        return [{"ma_phieu": p.ma_phieu, "ma_don": p.ma_don, "ma_diem_ban": p.ma_diem_ban,
                 "ngay_giao": str(p.ngay_giao)} for p in s.scalars(q)]


@router.get("/pick-lists/{ma_phieu}")
def pick_list(ma_phieu: str, user: User = Depends(current_user)):
    with tx() as s:
        return service.pick_list(s, user, ma_phieu)


class ScanIn(BaseModel):
    dong_id: int
    ma_lo_quet: str
    ly_do: str | None = None


@router.post("/pick-lists/{ma_phieu}/scan")
def scan(ma_phieu: str, body: ScanIn, user: User = Depends(current_user)):
    with tx() as s:
        return service.scan_lot(s, user, ma_phieu, body.dong_id, body.ma_lo_quet, body.ly_do)


class ShortIn(BaseModel):
    dong_id: int
    so_luong_thieu: int
    ly_do: str


@router.post("/pick-lists/{ma_phieu}/shortage")
def shortage(ma_phieu: str, body: ShortIn, user: User = Depends(current_user)):
    with tx() as s:
        service.report_pick_shortage(s, user, ma_phieu, body.dong_id, body.so_luong_thieu, body.ly_do)
    return {"ok": True}


@router.post("/pick-lists/{ma_phieu}/confirm-issue")
def confirm_issue(ma_phieu: str, user: User = Depends(current_user)):
    with tx() as s:
        return service.confirm_issue(s, user, ma_phieu)


class DeliveryLine(BaseModel):
    ma_sp: str
    ma_lo: str
    so_luong: int


class DeliveryIn(BaseModel):
    ma_su_kien: str
    dong: list[DeliveryLine]
    bang_chung: dict


@router.post("/deliveries/{ma_phieu}/confirm")
def confirm_delivery(ma_phieu: str, body: DeliveryIn, user: User = Depends(current_user)):
    with tx() as s:
        return service.confirm_delivery(s, user, ma_phieu, [d.model_dump() for d in body.dong], body.bang_chung,
                                        body.ma_su_kien)


# ---- CN5 ----------------------------------------------------------------------------------

class LockIn(BaseModel):
    ly_do: str


@router.post("/lots/{ma_lo}/lock")
def lock(ma_lo: str, body: LockIn, user: User = Depends(current_user)):
    with tx() as s:
        return recall.lock_lot(s, user, ma_lo, body.ly_do)


class UnlockIn(BaseModel):
    ket_qua_kiem_nghiem: str


@router.post("/lots/{ma_lo}/unlock")
def unlock(ma_lo: str, body: UnlockIn, user: User = Depends(current_user)):
    with tx() as s:
        return recall.unlock_lot(s, user, ma_lo, body.ket_qua_kiem_nghiem)


@router.get("/lots/{ma_lo}/trace")
def trace(ma_lo: str, user: User = Depends(current_user)):
    with tx() as s:
        return recall.trace_forward(s, user, ma_lo)


@router.get("/outlets/{ma_diem_ban}/lots")
def trace_back(ma_diem_ban: str, user: User = Depends(current_user)):
    with tx() as s:
        return recall.trace_backward(s, user, ma_diem_ban)


@router.post("/lots/{ma_lo}/recall")
def open_recall(ma_lo: str, body: LockIn, user: User = Depends(current_user)):
    with tx() as s:
        return recall.open_recall(s, user, ma_lo, body.ly_do)


@router.get("/recalls/{ma_vu}/tasks")
def recall_tasks(ma_vu: str, user: User = Depends(current_user)):
    with tx() as s:
        q = select(NhiemVuThuHoi).where(NhiemVuThuHoi.ma_vu == ma_vu)
        if not user.cap_cong_ty:
            q = q.where(NhiemVuThuHoi.ma_npp == user.ma_npp)
        return [{"ma_nhiem_vu": t.ma_nhiem_vu, "ma_diem_ban": t.ma_diem_ban, "so_luong_da_giao": t.so_luong_da_giao,
                 "so_luong_thu": t.so_luong_thu, "trang_thai": t.trang_thai} for t in s.scalars(q)]


class ReceiveIn(BaseModel):
    so_luong_thuc_nhan: int


@router.post("/recall-tasks/{ma_nhiem_vu}/receive")
def receive(ma_nhiem_vu: str, body: ReceiveIn, user: User = Depends(current_user)):
    with tx() as s:
        return recall.receive_recall(s, user, ma_nhiem_vu, body.so_luong_thuc_nhan)


@router.post("/recalls/{ma_vu}/close")
def close(ma_vu: str, user: User = Depends(current_user)):
    with tx() as s:
        return recall.close_recall(s, user, ma_vu)


@router.get("/nc2/transfers")
def transfers(user: User = Depends(current_user)):
    with tx() as s:
        return [{"ma_lo": t.ma_lo, "ma_sp": t.ma_sp, "tu_kho": t.tu_kho, "den_kho": t.den_kho, "so_luong": t.so_luong,
                 "gia_tri_cuu": t.gia_tri_cuu, "chi_phi_cho": t.chi_phi_cho, "trang_thai": t.trang_thai}
                for t in s.scalars(select(DeXuatDieuChuyen).order_by(DeXuatDieuChuyen.id.desc()).limit(100))]
