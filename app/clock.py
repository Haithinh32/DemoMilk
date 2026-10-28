"""Đồng hồ hệ thống có thể điều khiển, để demo và kiểm thử các thời hạn (BR-06).

Mọi module lấy thời gian qua đây, không gọi datetime.now() trực tiếp.
"""
from datetime import date, datetime, timedelta

_fixed: datetime | None = None

GIO_LAM_BAT_DAU = 8
GIO_LAM_KET_THUC = 17


def now() -> datetime:
    return _fixed if _fixed is not None else datetime.now().replace(microsecond=0)


def today() -> date:
    return now().date()


def set_now(dt: datetime | None) -> None:
    global _fixed
    _fixed = dt


def advance(**kwargs) -> datetime:
    set_now(now() + timedelta(**kwargs))
    return now()


def add_working_hours(start: datetime, hours: float) -> datetime:
    """Cộng giờ làm việc (8h–17h, thứ Hai–thứ Bảy). Dùng cho hạn duyệt ngoại lệ tín dụng 4 giờ làm việc."""
    remaining = timedelta(hours=hours)
    t = start
    while remaining > timedelta(0):
        if t.weekday() == 6 or t.hour >= GIO_LAM_KET_THUC:
            t = (t + timedelta(days=1)).replace(hour=GIO_LAM_BAT_DAU, minute=0, second=0)
            continue
        if t.hour < GIO_LAM_BAT_DAU:
            t = t.replace(hour=GIO_LAM_BAT_DAU, minute=0, second=0)
        end_of_day = t.replace(hour=GIO_LAM_KET_THUC, minute=0, second=0)
        step = min(remaining, end_of_day - t)
        t += step
        remaining -= step
    return t
