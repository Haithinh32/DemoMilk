"""Nạp mọi bảng để Base.metadata biết đủ (một CSDL dùng chung)."""
from app.ph0_platform import models as _ph0  # noqa: F401
from app.ph1_order import models as _ph1  # noqa: F401
from app.ph2_inventory import models as _ph2  # noqa: F401
from app.ph3_credit import models as _ph3  # noqa: F401
from app.ph4_sales import models as _ph4  # noqa: F401
