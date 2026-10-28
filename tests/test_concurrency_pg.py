"""NFR2 trên PostgreSQL thật: nhiều điểm bán đặt cùng lúc những thùng cuối cùng -> không bán vượt.

Chạy:  docker compose up -d db
       CSM_PG_URL=postgresql+psycopg://csm:csm@localhost:5432/csm python -m pytest tests/test_concurrency_pg.py
Bị bỏ qua khi không có CSM_PG_URL (SQLite tuần tự hóa ghi nên không chứng minh được khóa dòng).
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import clock, db, seed
from app.errors import Conflict
from app.ph0_platform.identity import DIEM_BAN, User
from tests.conftest import NOW

PG_URL = os.getenv("CSM_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="cần CSM_PG_URL trỏ tới PostgreSQL")


def test_parallel_orders_never_oversell():
    from app.ph1_order import service
    from app.ph2_inventory import contracts as ph2
    clock.set_now(NOW)
    db.init_engine(PG_URL)
    seed.reset_and_seed(NOW.date())
    with db.tx() as s:
        assert ph2.available_map(s, "K02", ["SP01"])["SP01"] == 10

    def attempt(i: int) -> str:
        u = User(f"U-{i}", "test", DIEM_BAN, "NPP02", f"DB-02-{i:03d}")
        try:
            with db.tx() as s:
                service.place_order(s, u, f"DB-02-{i:03d}", [{"ma_sp": "SP01", "so_luong": 2}], uuid.uuid4().hex)
            return "ok"
        except Conflict:
            return "thieu"

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(1, 31)))
    assert results.count("ok") == 5 and results.count("thieu") == 25
    with db.tx() as s:
        from app.ph2_inventory.models import TonKhoSP
        assert s.get(TonKhoSP, ("K02", "SP01")).da_giu == 10
        assert ph2.available_map(s, "K02", ["SP01"])["SP01"] == 0
