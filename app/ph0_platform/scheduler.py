"""Bộ lập lịch: đăng ký tác vụ định kỳ của các phân hệ.

Tác vụ có every_seconds chạy nền (quét quá hạn BR-06). Tác vụ theo giờ trong ngày (5h quét hạn lô,
23h dự báo, 23h khóa sổ, 1h nạp kho dữ liệu) được gọi qua POST /ph0/scheduler/run/{ten} trong demo,
thay cho cron. Sau mỗi tác vụ, bus giao các sự kiện tác vụ vừa phát.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.ph0_platform import events

log = logging.getLogger("csm.scheduler")


@dataclass
class Job:
    ten: str
    mo_ta: str
    lich: str
    fn: Callable[..., object]
    every_seconds: int | None = None


JOBS: dict[str, Job] = {}


def job(ten: str, mo_ta: str, lich: str, every_seconds: int | None = None):
    def deco(fn):
        JOBS[ten] = Job(ten, mo_ta, lich, fn, every_seconds)
        return fn
    return deco


def run(ten: str, **kwargs):
    result = JOBS[ten].fn(**kwargs)
    events.dispatch_pending()
    return result


_stop = threading.Event()


def start_background() -> None:
    last: dict[str, float] = {}

    def loop():
        while not _stop.wait(5):
            for j in JOBS.values():
                if j.every_seconds and time.monotonic() - last.get(j.ten, 0) >= j.every_seconds:
                    last[j.ten] = time.monotonic()
                    try:
                        run(j.ten)
                    except Exception:  # noqa: BLE001
                        log.exception("Tác vụ %s lỗi", j.ten)
            events.dispatch_pending()

    threading.Thread(target=loop, name="csm-scheduler", daemon=True).start()


def stop_background() -> None:
    _stop.set()
