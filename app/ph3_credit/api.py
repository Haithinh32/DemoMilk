import json
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.db import tx
from app.errors import DomainError
from app.ph0_platform import integration
from app.ph0_platform.identity import DIEM_BAN, User, check_npp, check_outlet, current_user
from app.ph3_credit import contracts, ledger, scoring_nc1
from app.ph3_credit.models import DiemTinDung, GiaoDichTT, HanMuc, YeuCauNgoaiLe
from app.ph4_sales import contracts as ph4

router = APIRouter(prefix="/ph3", tags=["PH3 – Công nợ, Thanh toán"])


@router.get("/debt/{ma_diem_ban}")
def debt(ma_diem_ban: str, user: User = Depends(current_user)):
    with tx() as s:
        o = ph4.get_outlet(s, ma_diem_ban)
        check_outlet(user, ma_diem_ban, o.ma_npp)
        return contracts.debt_summary(s, ma_diem_ban)


@router.get("/qr/{so_hoa_don}")
def qr(so_hoa_don: str, user: User = Depends(current_user)):
    with tx() as s:
        from app.ph3_credit.models import KhoanPhaiThu
        inv = s.get(KhoanPhaiThu, so_hoa_don)
        if inv is None:
            raise DomainError("KHONG_TIM_THAY", "Không có hóa đơn", status=404)
        check_outlet(user, inv.ma_diem_ban, inv.ma_npp)
        return contracts.create_qr(s, inv.ma_diem_ban, so_hoa_don)


@router.get("/exceptions")
def exceptions(user: User = Depends(current_user)):
    with tx() as s:
        q = select(YeuCauNgoaiLe).where(YeuCauNgoaiLe.trang_thai == "cho")
        if not user.cap_cong_ty:
            q = q.where(YeuCauNgoaiLe.ma_npp == user.ma_npp)
        return [{"ma_yc": y.ma_yc, "ma_don": y.ma_don, "ma_diem_ban": y.ma_diem_ban, "so_tien": y.so_tien,
                 "ly_do": y.ly_do, "han": y.han} for y in s.scalars(q)]


class DecideIn(BaseModel):
    duyet: bool
    ly_do: str | None = None


@router.post("/exceptions/{ma_yc}/decide")
def decide(ma_yc: str, body: DecideIn, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.decide_exception(s, user, ma_yc, body.duyet, body.ly_do)


@router.post("/bank/webhook")
async def bank_webhook(request: Request, x_signature: str | None = Header(default=None)):
    """Báo có từ ngân hàng qua cổng có WAF; kiểm tra chữ ký HMAC trước khi gạch nợ."""
    raw = await request.body()
    if not integration.verify_bank_signature(raw, x_signature):
        raise DomainError("SAI_CHU_KY", "Chữ ký webhook không hợp lệ", status=401)
    body = json.loads(raw)
    from starlette.concurrency import run_in_threadpool

    def _run():
        with tx() as s:
            return ledger.receive_bank_credit(s, body)
    return await run_in_threadpool(_run)


class SimTransferIn(BaseModel):
    so_tai_khoan: str
    so_tien: int
    noi_dung: str


@router.post("/bank/simulate")
def bank_simulate(body: SimTransferIn, user: User = Depends(current_user)):
    """CHỈ CHO DEMO: đóng vai ngân hàng chuyển khoản, xử lý như một báo có qua webhook."""
    import uuid
    with tx() as s:
        return ledger.receive_bank_credit(s, {"ma_gd_ngan_hang": f"FT-SIM-{uuid.uuid4().hex[:10].upper()}",
                                              **body.model_dump()})


@router.get("/payments/pending")
def pending(user: User = Depends(current_user)):
    with tx() as s:
        q = select(GiaoDichTT).where(GiaoDichTT.trang_thai == "cho_xu_ly")
        if not user.cap_cong_ty:
            q = q.where(GiaoDichTT.ma_npp == user.ma_npp)
        return [{"ma_gd": g.ma_gd, "so_tien": g.so_tien, "noi_dung": g.noi_dung, "ngay": str(g.ngay)}
                for g in s.scalars(q)]


class AssignIn(BaseModel):
    so_hoa_don: str


@router.post("/payments/{ma_gd}/assign")
def assign(ma_gd: str, body: AssignIn, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.assign_pending(s, user, ma_gd, body.so_hoa_don)


class CashIn(BaseModel):
    so_hoa_don: str
    so_tien: int
    ma_bien_nhan: str


@router.post("/cash")
def cash(body: CashIn, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.record_cash(s, user, body.so_hoa_don, body.so_tien, body.ma_bien_nhan)


class HandoverIn(BaseModel):
    ma_nguoi_thu: str
    thuc_nop: int


@router.post("/cash-handover")
def handover(body: HandoverIn, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.cash_handover(s, user, body.ma_nguoi_thu, body.thuc_nop)


@router.get("/reconcile/{ma_npp}")
def reconcile(ma_npp: str, ngay: date | None = None, user: User = Depends(current_user)):
    from app import clock
    with tx() as s:
        check_npp(user, ma_npp)
        return ledger.reconcile(s, ma_npp, ngay or clock.today())


@router.post("/close-day/{ma_npp}")
def close_day(ma_npp: str, ngay: date | None = None, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.close_day(s, user, ma_npp, ngay)


class AdjustIn(BaseModel):
    ngay: date
    no_tk: str
    co_tk: str
    so_tien: int
    ly_do: str


@router.post("/adjustments/{ma_npp}")
def adjust(ma_npp: str, body: AdjustIn, user: User = Depends(current_user)):
    with tx() as s:
        return ledger.adjustment_entry(s, user, ma_npp, **body.model_dump())


@router.get("/nc1/scores")
def scores(user: User = Depends(current_user)):
    with tx() as s:
        q = select(DiemTinDung).order_by(DiemTinDung.ky.desc(), DiemTinDung.xac_suat.desc()).limit(500)
        if not user.cap_cong_ty:
            q = q.where(DiemTinDung.ma_npp == user.ma_npp)
        return [{"id": d.id, "ma_diem_ban": d.ma_diem_ban, "ky": str(d.ky), "xac_suat": d.xac_suat, "hang": d.hang,
                 "han_muc_hien_tai": d.han_muc_hien_tai, "han_muc_de_xuat": d.han_muc_de_xuat, "ly_do": d.ly_do,
                 "trang_thai": d.trang_thai} for d in s.scalars(q)]


class ScoreDecideIn(BaseModel):
    han_muc_chot: int | None = None
    ly_do: str | None = None


@router.post("/nc1/scores/{id_}/decide")
def score_decide(id_: int, body: ScoreDecideIn, user: User = Depends(current_user)):
    with tx() as s:
        return scoring_nc1.decide(s, user, id_, body.han_muc_chot, body.ly_do)
