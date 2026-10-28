"""Cấu hình chung, đọc từ biến môi trường."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CSM_DATA_DIR", BASE_DIR / "data"))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'csm.db').as_posix()}")

# Bộ lập lịch chạy nền (quét quá hạn mỗi phút). Tắt trong kiểm thử.
SCHEDULER_ENABLED = os.getenv("CSM_SCHEDULER", "off") == "on"

# Bí mật ký webhook ngân hàng (HMAC-SHA256). Thực tế lấy từ kho bí mật.
BANK_WEBHOOK_SECRET = os.getenv("CSM_BANK_SECRET", "demo-bank-secret")

# Agent Zalo OA
AGENT_MODEL = os.getenv("CSM_AGENT_MODEL", "claude-opus-5-5")

# Tham số nghiệp vụ (giả định cho thí điểm)
GIO_CHOT_DON = 16                    # PH1 BR-03
NGUONG_GIA_TRI_DON_NPP_DUYET = 20_000_000   # PH1 CN3: vượt ngưỡng thì NPP duyệt
SO_NGAY_LO_DO = 3                    # BR-04, BR2.4: còn < 3 ngày là lô đỏ
NHIET_DO_NHAN = (2.0, 6.0)           # BR2.2
BAN_KINH_CHECKIN_M = 100             # PH4 BR6
DIEM_MOI_VND = 10_000                # 1 điểm thưởng / 10.000 đ thực giao
