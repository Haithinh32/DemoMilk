"""Cao Sơn Milk – TMĐT B2B và Quản lý phân phối: bản mẫu modular monolith.

Chạy:  uvicorn app.main:app --reload     (tài liệu API: http://127.0.0.1:8000/docs)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app import config, db
from app import wiring  # noqa: F401
from app.errors import DomainError
from app.ph0_platform import events, scheduler
from app.ph0_platform.api import router as ph0_router
from app.ph1_order.api import router as ph1_router
from app.ph2_inventory.api import router as ph2_router
from app.ph3_credit.api import router as ph3_router
from app.ph4_sales.api import router as ph4_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if db.engine is None:
        db.init_engine()
        db.create_all()
    if config.SCHEDULER_ENABLED:
        scheduler.start_background()
    yield
    scheduler.stop_background()


app = FastAPI(title="Cao Sơn Milk – B2B & DMS (prototype)", version="0.1.0", lifespan=lifespan)
for r in (ph0_router, ph1_router, ph2_router, ph3_router, ph4_router):
    app.include_router(r)


@app.exception_handler(DomainError)
async def domain_error_handler(_req: Request, e: DomainError):
    return JSONResponse(status_code=e.status, content={"error": {"code": e.code, "message": e.message, "data": e.data}})


@app.middleware("http")
async def dispatch_events_after_write(request: Request, call_next):
    """Sau mỗi request ghi, giao các sự kiện vừa phát để demo thấy luồng xuyên phân hệ ngay.
    Bộ lập lịch nền cũng giao định kỳ; sự kiện nằm trong outbox nên không mất nếu bước này lỗi."""
    response = await call_next(request)
    if request.method != "GET":
        try:
            await run_in_threadpool(events.dispatch_pending)
        except Exception:  # noqa: BLE001
            logging.getLogger("csm.events").exception("dispatch sau request lỗi")
    return response


@app.get("/")
def root():
    return {"ten": "Cao Sơn Milk prototype", "tai_lieu": "/docs"}
