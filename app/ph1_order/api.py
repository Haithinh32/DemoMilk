from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db import tx
from app.ph0_platform.identity import User, current_user
from app.ph1_order import promo, promo_nc1, service

router = APIRouter(prefix="/ph1", tags=["PH1 – Đặt hàng B2B, Giá – KM"])


class Line(BaseModel):
    ma_sp: str
    so_luong: int = Field(gt=0)


class OrderIn(BaseModel):
    ma_diem_ban: str
    dong: list[Line]
    khoa_chong_trung: str = Field(min_length=8, description="Mỗi lần bấm Đặt hàng một khóa; gửi lại dùng lại khóa")
    nguon: str = "app"
    bo_km: list[str] = []
    yc_chiet_khau_pct: float = 0
    ma_goi_y: str | None = None


@router.get("/catalog/{ma_diem_ban}")
def catalog(ma_diem_ban: str, user: User = Depends(current_user)):
    with tx() as s:
        return service.catalog(s, user, ma_diem_ban)


@router.get("/cart/from-suggestion/{ma_diem_ban}")
def cart_from_suggestion(ma_diem_ban: str, user: User = Depends(current_user)):
    with tx() as s:
        return service.cart_from_suggestion(s, user, ma_diem_ban)


@router.post("/orders")
def place_order(body: OrderIn, user: User = Depends(current_user)):
    return service.place_and_review(user, **body.model_dump())


@router.get("/orders")
def list_orders(trang_thai: str | None = None, user: User = Depends(current_user)):
    with tx() as s:
        return service.list_orders(s, user, trang_thai)


@router.get("/orders/{ma_don}")
def get_order(ma_don: str, user: User = Depends(current_user)):
    with tx() as s:
        return service.order_detail(s, user, ma_don)


class ChoiceIn(BaseModel):
    lua_chon: str
    ly_do: str | None = None


@router.post("/orders/{ma_don}/credit-choice")
def credit_choice(ma_don: str, body: ChoiceIn, user: User = Depends(current_user)):
    with tx() as s:
        service.credit_choice(s, user, ma_don, body.lua_chon, body.ly_do)
    with tx() as s:
        return service.order_detail(s, user, ma_don)


class DecisionIn(BaseModel):
    duyet: bool
    ly_do: str | None = None


@router.post("/orders/{ma_don}/npp-decision")
def npp_decision(ma_don: str, body: DecisionIn, user: User = Depends(current_user)):
    with tx() as s:
        return {"trang_thai": service.npp_decide(s, user, ma_don, body.duyet, body.ly_do)}


class CancelIn(BaseModel):
    ly_do: str


@router.post("/orders/{ma_don}/cancel")
def cancel(ma_don: str, body: CancelIn, user: User = Depends(current_user)):
    with tx() as s:
        return {"trang_thai": service.cancel_order(s, user, ma_don, body.ly_do)}


@router.post("/agent-drafts/{ma_nhap}/confirm")
def confirm_draft(ma_nhap: str, user: User = Depends(current_user)):
    return service.confirm_agent_draft(user, ma_nhap)


# ---- CN1 tối thiểu + NC1 ------------------------------------------------------------------

class PromoIn(BaseModel):
    ten: str
    ma_sp: str
    muc_giam: float
    sl_toi_thieu: int = 1
    vung_ap_dung: list[str] | None = None
    tu_ngay: date
    den_ngay: date
    ngan_sach: int


@router.post("/promotions")
def create_promo(body: PromoIn, user: User = Depends(current_user)):
    with tx() as s:
        return {"ma_km": promo.create_promo(s, user, body.model_dump()).ma_km}


@router.post("/promotions/{ma_km}/approve")
def approve_promo(ma_km: str, user: User = Depends(current_user)):
    with tx() as s:
        km = promo.approve_promo(s, user, ma_km)
        return {"ma_km": km.ma_km, "trang_thai": km.trang_thai}


class ProposeIn(BaseModel):
    ma_sp: str
    tu_ngay: date
    den_ngay: date
    ngan_sach: int
    cac_muc_giam: list[float] = [0.05, 0.1, 0.15]


@router.post("/nc1/propose")
def nc1_propose(body: ProposeIn, user: User = Depends(current_user)):
    with tx() as s:
        return promo_nc1.propose(s, user, **body.model_dump())


class ChooseIn(BaseModel):
    chi_so: int
    ly_do: str | None = None


@router.post("/nc1/{ma_pa}/create-program")
def nc1_create(ma_pa: str, body: ChooseIn, user: User = Depends(current_user)):
    with tx() as s:
        return {"ma_km": promo_nc1.create_program(s, user, ma_pa, body.chi_so, body.ly_do).ma_km}


@router.get("/nc1/evaluate/{ma_km}")
def nc1_evaluate(ma_km: str, user: User = Depends(current_user)):
    with tx() as s:
        return promo_nc1.evaluate(s, ma_km)


class ReplenishIn(BaseModel):
    dieu_chinh: dict[str, dict] = {}


@router.post("/replenishment/{ma_don_bs}/submit")
def submit_replenishment(ma_don_bs: str, body: ReplenishIn, user: User = Depends(current_user)):
    with tx() as s:
        d = promo.submit_replenishment(s, user, ma_don_bs, body.dieu_chinh)
        return {"ma_don_bs": d.ma_don_bs, "trang_thai": d.trang_thai, "dong": d.dong}


@router.post("/replenishment/{ma_don_bs}/confirm")
def confirm_replenishment(ma_don_bs: str, user: User = Depends(current_user)):
    with tx() as s:
        d = promo.confirm_replenishment(s, user, ma_don_bs)
        return {"ma_don_bs": d.ma_don_bs, "trang_thai": d.trang_thai}
