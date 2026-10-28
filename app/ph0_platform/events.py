"""Bus sự kiện trong tiến trình theo mẫu outbox/inbox.

- publish() ghi sự kiện vào bảng su_kien TRONG giao dịch của bên phát: thay đổi nghiệp vụ và sự kiện
  cùng commit hoặc cùng rollback, nên không có sự kiện "ma" hay thay đổi bị mất sự kiện.
- dispatch_pending() giao sự kiện cho từng bên nhận, mỗi bên nhận một giao dịch riêng; bên nhận ghi
  (ben_nhan, ma_su_kien) vào hộp thư đến trong cùng giao dịch đó nên gửi lại không bị xử lý hai lần.
- Bên nhận lỗi: sự kiện giữ trạng thái "cho" và được thử lại; quá MAX_LAN_THU thì chuyển "loi"
  để quản trị xem ở /ph0/events. Lỗi ở một bên nhận không chặn bên nhận khác.

Khi tách service (NFR9), thay dispatch_pending bằng một relay đẩy bảng su_kien lên message broker;
hợp đồng sự kiện (event_catalog.py) giữ nguyên.
"""
import logging
import threading
import time
from collections import defaultdict
from typing import Callable

from sqlalchemy import select

from app.db import new_id, tx
from app.ph0_platform.models import SuKien, SuKienDaXuLy

log = logging.getLogger("csm.events")

MAX_LAN_THU = 5
Handler = Callable[[object, dict, str], None]
_handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
_dispatch_lock = threading.Lock()


def subscribe(loai: str, ben_nhan: str):
    def deco(fn: Handler) -> Handler:
        _handlers[loai].append((ben_nhan, fn))
        return fn
    return deco


def publish(s, loai: str, payload: dict, ma_su_kien: str | None = None) -> str:
    """Ghi sự kiện vào outbox trong giao dịch hiện tại. Cùng ma_su_kien thì chỉ ghi một lần."""
    ma = ma_su_kien or new_id("EV")
    if ma_su_kien and s.get(SuKien, ma) is not None:
        return ma
    s.add(SuKien(ma_su_kien=ma, loai=loai, payload=payload, seq=time.monotonic_ns()))
    s.flush()
    return ma


def _deliver(ma: str) -> None:
    with tx() as s:
        ev = s.get(SuKien, ma)
        loai, payload = ev.loai, dict(ev.payload)
    errors = []
    for ben_nhan, fn in _handlers.get(loai, []):
        try:
            with tx() as s:
                done = s.scalar(select(SuKienDaXuLy).where(SuKienDaXuLy.ben_nhan == ben_nhan,
                                                           SuKienDaXuLy.ma_su_kien == ma))
                if done is None:
                    fn(s, payload, ma)
                    s.add(SuKienDaXuLy(ben_nhan=ben_nhan, ma_su_kien=ma))
        except Exception as e:  # noqa: BLE001 - một bên nhận lỗi không chặn bên khác
            log.exception("Bên nhận %s lỗi với sự kiện %s (%s)", ben_nhan, ma, loai)
            errors.append(f"{ben_nhan}: {e!r}")
    with tx() as s:
        ev = s.get(SuKien, ma)
        if not errors:
            ev.trang_thai, ev.loi = "xong", None
        else:
            ev.so_lan_thu += 1
            ev.loi = "; ".join(errors)
            if ev.so_lan_thu >= MAX_LAN_THU:
                ev.trang_thai = "loi"


def dispatch_pending(max_rounds: int = 50) -> int:
    """Giao mọi sự kiện đang chờ, kể cả sự kiện do bên nhận phát thêm. Trả về số sự kiện đã giao."""
    delivered = 0
    with _dispatch_lock:
        seen_failing: set[str] = set()
        for _ in range(max_rounds):
            with tx() as s:
                ids = s.scalars(select(SuKien.ma_su_kien).where(SuKien.trang_thai == "cho")
                                .order_by(SuKien.seq)).all()
            ids = [i for i in ids if i not in seen_failing]
            if not ids:
                break
            for ma in ids:
                _deliver(ma)
                delivered += 1
                with tx() as s:
                    if s.get(SuKien, ma).trang_thai != "xong":
                        seen_failing.add(ma)  # thử lại ở lượt dispatch sau, không quay vòng ngay
    return delivered
