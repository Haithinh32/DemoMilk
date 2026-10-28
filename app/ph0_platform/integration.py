"""Integration: ERP (trao đổi tệp, mục 2.7.6), ngân hàng (VietQR, báo có), HĐĐT, phần mềm kế toán NPP.

Thư mục trao đổi chia ba ngăn cho_xu_ly / da_xu_ly / loi. Mỗi tệp mang mã chứng từ + số phiên bản
(chống nhập trùng) và dòng cuối là mã SHA-256 của nội dung (toàn vẹn).
"""
import csv
import hashlib
import hmac
import io
import shutil
from pathlib import Path

from app import clock, config

KENH_ERP_RA = "erp_ra"            # hệ thống -> ERP (đơn bổ sung NPP đã chốt)
KENH_ERP_VAO = "erp_vao"          # ERP -> hệ thống (phiếu xuất nhà máy)
KENH_KE_TOAN_NPP = "ke_toan_npp"  # bút toán sau khóa sổ


def exchange_dir(kenh: str, ngan: str = "cho_xu_ly") -> Path:
    p = config.DATA_DIR / "exchange" / kenh / ngan
    p.mkdir(parents=True, exist_ok=True)
    return p


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_exchange_file(kenh: str, ma_chung_tu: str, phien_ban: int, rows: list[dict]) -> Path:
    path = exchange_dir(kenh) / f"{ma_chung_tu}_v{phien_ban}.csv"
    if path.exists() or (exchange_dir(kenh, "da_xu_ly") / path.name).exists():
        return path  # đã ghi phiên bản này: không ghi lại
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    body = buf.getvalue()
    path.write_text(body + f"#sha256={_checksum(body)}\n", encoding="utf-8")
    return path


def read_exchange_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    body, _, tail = text.rpartition("#sha256=")
    if tail.strip() != _checksum(body):
        raise ValueError(f"Sai mã toàn vẹn: {path.name}")
    return list(csv.DictReader(io.StringIO(body)))


def move(path: Path, kenh: str, ngan: str) -> None:
    shutil.move(str(path), exchange_dir(kenh, ngan) / path.name)


# ---- Ngân hàng ----------------------------------------------------------------

def vietqr(so_tai_khoan: str, so_hoa_don: str, so_tien: int) -> dict:
    """QR động điền sẵn số tiền và mã hóa đơn trong nội dung chuyển khoản (Bảng 3.41)."""
    noi_dung = f"CSM {so_hoa_don}"
    payload = f"VIETQR|{so_tai_khoan}|{so_tien}|{noi_dung}"
    return {"qr": payload, "so_tai_khoan": so_tai_khoan, "so_tien": so_tien, "noi_dung": noi_dung}


def sign_bank_payload(body: bytes) -> str:
    return hmac.new(config.BANK_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def verify_bank_signature(body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign_bank_payload(body), signature)


# ---- Hóa đơn điện tử (mock) -----------------------------------------------------

def issue_einvoice(so_hoa_don: str, so_tien: int) -> str:
    return f"1C{clock.today():%y}TCS-{so_hoa_don[-6:]}"
