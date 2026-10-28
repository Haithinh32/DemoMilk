from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import clock
from app.db import tx
from app.ph0_platform.identity import User, current_user
from app.ph4_sales import dashboard, field

router = APIRouter(prefix="/ph4", tags=["PH4 – Bán hàng, Điểm bán, Phân tích"])


@router.get("/route/today")
def route_today(user: User = Depends(current_user)):
    with tx() as s:
        return field.route_today(s, user)


class VisitIn(BaseModel):
    ma_luot_ghe: str
    ma_diem_ban: str
    thoi_gian_may: str
    lat: float
    lng: float
    so_lan_thu: int = 1
    ly_do_xa: str | None = None
    anh: list[dict] = []
    het_hang: list[str] = []
    trung_bay_dat: bool | None = None
    thu_no: list[dict] = []


@router.post("/visits")
def sync_visits(body: list[VisitIn], user: User = Depends(current_user)):
    """Đồng bộ một lô lượt ghé (ngoại tuyến). Mỗi lượt xử lý riêng để một lượt lỗi không chặn lượt khác."""
    out = []
    for v in body:
        try:
            with tx() as s:
                out.append(field.sync_visit(s, user, v.model_dump()))
        except Exception as e:  # noqa: BLE001
            out.append({"ma_luot_ghe": v.ma_luot_ghe, "loi": getattr(e, "code", "LOI"),
                        "thong_bao": getattr(e, "message", str(e)), "data": getattr(e, "data", {})})
    return out


@router.get("/points/{ma_diem_ban}")
def points(ma_diem_ban: str, user: User = Depends(current_user)):
    with tx() as s:
        return field.points(s, user, ma_diem_ban)


@router.get("/dashboard")
def get_dashboard(ngay: date | None = None, ma_npp: str | None = None, user: User = Depends(current_user)):
    with tx() as s:
        return dashboard.dashboard(s, user, ngay, ma_npp)


@router.get("/dashboard/drill")
def drill(cap: str = "npp", tu: date | None = None, den: date | None = None, ma_npp: str | None = None,
          user: User = Depends(current_user)):
    den = den or clock.today()
    tu = tu or den.replace(day=1)
    with tx() as s:
        return dashboard.drill_down(s, user, cap, tu, den, ma_npp)
