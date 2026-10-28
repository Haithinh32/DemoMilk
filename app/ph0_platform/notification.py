"""Notification: app, Zalo ZNS, SMS. Prototype chỉ ghi vào bảng thong_bao; Zalo lỗi thì chuyển SMS (Bảng 4.6)."""
from app.ph0_platform.models import ThongBao

zalo_available = True  # kiểm thử có thể tắt để thấy chuyển sang SMS


def send(s, nguoi_nhan: str, tieu_de: str, noi_dung: str, kenh: str = "app") -> None:
    if kenh == "zalo" and not zalo_available:
        kenh = "sms"
    s.add(ThongBao(kenh=kenh, nguoi_nhan=nguoi_nhan, tieu_de=tieu_de, noi_dung=noi_dung))
