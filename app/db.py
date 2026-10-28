"""Một cơ sở dữ liệu dùng chung cho mọi phân hệ (modular monolith, mục 2.4).

PostgreSQL khi chạy thật (khóa dòng SELECT ... FOR UPDATE); SQLite cho demo nhanh và kiểm thử
(SQLite tuần tự hóa mọi lệnh ghi nên vẫn không bán vượt, nhưng không chứng minh được khóa dòng).
"""
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def init_engine(url: str | None = None):
    global engine
    url = url or config.DATABASE_URL
    kwargs = {}
    if url.startswith("sqlite"):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    SessionLocal.configure(bind=engine)
    return engine


def create_all():
    import app.models_registry  # noqa: F401  (nạp mọi bảng của các phân hệ)
    Base.metadata.create_all(engine)


def drop_all():
    import app.models_registry  # noqa: F401
    Base.metadata.drop_all(engine)


@contextmanager
def tx():
    """Một giao dịch: commit khi thoát bình thường, rollback khi có lỗi."""
    s: Session = SessionLocal()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def is_postgres() -> bool:
    return engine is not None and engine.dialect.name == "postgresql"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"
