"""Mỗi test chạy trên một bản sao CSDL mẫu (SQLite) với đồng hồ cố định 09:00 thứ Tư 28/10/2026."""
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="csm_test_"))
os.environ["CSM_DATA_DIR"] = str(_TMP)

from app import clock, config, db, seed  # noqa: E402
from app import wiring  # noqa: E402,F401

NOW = datetime(2026, 10, 28, 9, 0)


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def template_db():
    clock.set_now(NOW)
    path = _TMP / "template.db"
    db.init_engine(f"sqlite:///{path.as_posix()}")
    db.create_all()
    seed.seed(NOW.date())
    db.engine.dispose()
    shutil.copytree(_TMP / "exchange", _TMP / "exchange_template")
    return path


@pytest.fixture
def client(template_db, tmp_path):
    clock.set_now(NOW)
    path = tmp_path / "t.db"
    shutil.copy(template_db, path)
    config.DATA_DIR = tmp_path
    shutil.copytree(_TMP / "exchange_template", tmp_path / "exchange")
    db.init_engine(f"sqlite:///{path.as_posix()}")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.engine.dispose()
