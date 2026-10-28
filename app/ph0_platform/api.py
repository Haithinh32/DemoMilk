from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app import clock
from app.db import tx
from app.ph0_platform import agent, events, scheduler
from app.ph0_platform.identity import ADMIN, BDH, User, current_user, require_role
from app.ph0_platform.models import NguoiDung, NhatKy, NhatKyAgent, SanPham, SuKien, ThongBao

router = APIRouter(prefix="/ph0", tags=["PH0 – Nền tảng chung"])


@router.get("/me")
def me(user: User = Depends(current_user)):
    with tx() as s:
        zalo_id = s.scalar(select(NguoiDung.zalo_id).where(NguoiDung.ma_nguoi_dung == user.ma))
    return {**asdict(user), "zalo_id": zalo_id}


@router.get("/events")
def list_events(trang_thai: str | None = None, loai: str | None = None, limit: int = 100,
                user: User = Depends(current_user)):
    require_role(user, ADMIN, BDH)
    with tx() as s:
        q = select(SuKien).order_by(SuKien.seq.desc()).limit(min(limit, 500))
        if trang_thai:
            q = q.where(SuKien.trang_thai == trang_thai)
        if loai:
            q = q.where(SuKien.loai == loai)
        return [{"ma_su_kien": e.ma_su_kien, "loai": e.loai, "trang_thai": e.trang_thai, "so_lan_thu": e.so_lan_thu,
                 "loi": e.loi, "tao_luc": e.tao_luc, "payload": e.payload} for e in s.scalars(q)]


@router.post("/events/dispatch")
def dispatch(user: User = Depends(current_user)):
    require_role(user, ADMIN)
    return {"da_giao": events.dispatch_pending()}


@router.get("/scheduler/jobs")
def jobs(user: User = Depends(current_user)):
    return [{"ten": j.ten, "mo_ta": j.mo_ta, "lich": j.lich} for j in scheduler.JOBS.values()]


@router.post("/scheduler/run/{ten}")
def run_job(ten: str, body: dict | None = None, user: User = Depends(current_user)):
    require_role(user, ADMIN)
    return scheduler.run(ten, **(body or {}))


class ClockIn(BaseModel):
    dat_gio: datetime | None = None
    cong_phut: int | None = None


@router.get("/products")
def products(user: User = Depends(current_user)):
    with tx() as s:
        return [{"ma_sp": p.ma_sp, "ten": p.ten, "nhom_nhiet": p.nhom_nhiet, "so_ngay_han": p.so_ngay_han}
                for p in s.scalars(select(SanPham).order_by(SanPham.ma_sp))]


@router.get("/clock")
def get_clock():
    return {"now": clock.now()}


@router.post("/clock")
def set_clock(body: ClockIn, user: User = Depends(current_user)):
    """Chỉ cho demo: tua thời gian để thấy các hạn BR-06 hoạt động."""
    require_role(user, ADMIN)
    if body.dat_gio:
        clock.set_now(body.dat_gio)
    if body.cong_phut:
        clock.advance(minutes=body.cong_phut)
    return {"now": clock.now()}


@router.get("/notifications")
def notifications(nguoi_nhan: str | None = None, limit: int = 50, user: User = Depends(current_user)):
    with tx() as s:
        target = nguoi_nhan if user.vai_tro in (ADMIN, BDH) else (user.ma_diem_ban or user.ma_npp or user.ma)
        q = select(ThongBao).order_by(ThongBao.id.desc()).limit(min(limit, 200))
        if target:
            q = q.where(ThongBao.nguoi_nhan == target)
        return [{"luc": t.luc, "kenh": t.kenh, "nguoi_nhan": t.nguoi_nhan, "tieu_de": t.tieu_de, "noi_dung": t.noi_dung}
                for t in s.scalars(q)]


@router.get("/audit")
def audit_log(doi_tuong: str | None = None, limit: int = 100, user: User = Depends(current_user)):
    require_role(user, ADMIN, BDH)
    with tx() as s:
        q = select(NhatKy).order_by(NhatKy.id.desc()).limit(min(limit, 500))
        if doi_tuong:
            q = q.where(NhatKy.doi_tuong == doi_tuong)
        return [{"luc": n.luc, "ai": n.ma_nguoi_dung, "hanh_dong": n.hanh_dong, "doi_tuong": n.doi_tuong,
                 "ma": n.ma_doi_tuong, "cu": n.gia_tri_cu, "moi": n.gia_tri_moi} for n in s.scalars(q)]


class ZaloMessage(BaseModel):
    zalo_id: str
    tin_nhan: str


@router.post("/agent/zalo")
def zalo_webhook(body: ZaloMessage):
    """Webhook Zalo OA (mock). Thực tế xác thực chữ ký của Zalo trước khi xử lý."""
    return agent.chat(body.zalo_id, body.tin_nhan)


@router.post("/agent/tools/{ten}")
def agent_tool(ten: str, body: dict, zalo_id: str):
    """Gọi thẳng một công cụ của agent (không qua LLM) để kiểm thử phạm vi quyền."""
    return agent.execute_tool(zalo_id, ten, body)


@router.get("/agent/log")
def agent_log(limit: int = 50, user: User = Depends(current_user)):
    require_role(user, ADMIN)
    with tx() as s:
        return [{"luc": a.luc, "zalo_id": a.zalo_id, "ma_diem_ban": a.ma_diem_ban, "cong_cu": a.cong_cu,
                 "dau_vao": a.dau_vao, "thanh_cong": a.thanh_cong}
                for a in s.scalars(select(NhatKyAgent).order_by(NhatKyAgent.id.desc()).limit(min(limit, 200)))]
