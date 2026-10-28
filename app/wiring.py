"""Nạp mọi module có bên nhận sự kiện (@events.subscribe) và tác vụ định kỳ, để bus biết đủ bên nhận."""
from app.ph0_platform import integration_handlers  # noqa: F401
from app.ph1_order import promo, service  # noqa: F401
from app.ph2_inventory import recall, service as ph2_service  # noqa: F401
from app.ph3_credit import ledger  # noqa: F401
from app.ph4_sales import field  # noqa: F401
from app import jobs  # noqa: F401
