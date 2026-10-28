"""Identity: xác thực, vai trò và phạm vi dữ liệu (mục 4.5).

Prototype dùng token tĩnh trong header Authorization: Bearer <token> thay cho OTP + JWT.
Phạm vi NPP luôn lấy từ token, không tin tham số client gửi lên (Bảng 4.4, tầng ứng dụng).
"""
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.db import tx
from app.errors import DomainError, Forbidden, NotFound
from app.ph0_platform.models import NguoiDung

# Vai trò (Bảng 4.3)
DIEM_BAN = "diem_ban"
NVBH = "nvbh"
GIAM_SAT = "giam_sat"
NPP = "npp"
THU_KHO = "thu_kho"
NVGH = "nvgh"
KE_TOAN = "ke_toan"
KE_TOAN_TRUONG = "ke_toan_truong"
THU_QUY = "thu_quy"
PKD = "pkd"
GDKD = "gdkd"
QA = "qa"
BDH = "bdh"
ADMIN = "admin"
HE_THONG = "he_thong"

VAI_TRO_CONG_TY = {PKD, GDKD, QA, BDH, ADMIN, HE_THONG}


@dataclass(frozen=True)
class User:
    ma: str
    ten: str
    vai_tro: str
    ma_npp: str | None
    ma_diem_ban: str | None

    @property
    def cap_cong_ty(self) -> bool:
        return self.vai_tro in VAI_TRO_CONG_TY


SYSTEM = User("HE_THONG", "Hệ thống", HE_THONG, None, None)


def _to_user(nd: NguoiDung) -> User:
    return User(nd.ma_nguoi_dung, nd.ten, nd.vai_tro, nd.ma_npp, nd.ma_diem_ban)


# auto_error=False để tự trả lỗi theo định dạng chung; khai báo này cũng bật nút Authorize trên /docs
_bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if cred is None:
        raise DomainError("CHUA_DANG_NHAP", "Thiếu token đăng nhập", status=401)
    token = cred.credentials.strip()
    with tx() as s:
        nd = s.scalar(select(NguoiDung).where(NguoiDung.token == token))
        if nd is None:
            raise DomainError("TOKEN_SAI", "Token không hợp lệ", status=401)
        return _to_user(nd)


def user_by_zalo(s, zalo_id: str) -> User | None:
    nd = s.scalar(select(NguoiDung).where(NguoiDung.zalo_id == zalo_id))
    return _to_user(nd) if nd else None


def require_role(user: User, *roles: str) -> None:
    if user.vai_tro not in roles and user.vai_tro not in (ADMIN, HE_THONG):
        raise Forbidden(f"Vai trò {user.vai_tro} không được phép (cần: {', '.join(roles)})")


def check_npp(user: User, ma_npp: str, what: str = "dữ liệu", ma: str = "") -> None:
    """NPP chỉ thấy dữ liệu khu vực mình (NFR6). Trả 404 thay vì 403 để không lộ sự tồn tại của bản ghi."""
    if user.cap_cong_ty:
        return
    if user.ma_npp != ma_npp:
        raise NotFound(what, ma)


def check_outlet(user: User, ma_diem_ban: str, ma_npp: str) -> None:
    check_npp(user, ma_npp, "điểm bán", ma_diem_ban)
    if user.vai_tro == DIEM_BAN and user.ma_diem_ban != ma_diem_ban:
        raise NotFound("điểm bán", ma_diem_ban)
