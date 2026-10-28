"""Lỗi nghiệp vụ dùng chung; API trả về dạng {"error": {"code", "message", "data"}}."""


class DomainError(Exception):
    status = 400

    def __init__(self, code: str, message: str, data: dict | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        if status is not None:
            self.status = status


class NotFound(DomainError):
    status = 404

    def __init__(self, what: str, ma: str):
        super().__init__("KHONG_TIM_THAY", f"Không tìm thấy {what} {ma}", {"ma": ma})


class Forbidden(DomainError):
    status = 403

    def __init__(self, message: str = "Không có quyền thực hiện thao tác này"):
        super().__init__("KHONG_CO_QUYEN", message)


class Conflict(DomainError):
    status = 409
