"""Dịch vụ Integration: trao đổi tệp với ERP theo hai chiều (mục 2.7.6, Bảng 4.7)."""
from datetime import date

from sqlalchemy import select

from app.db import tx
from app.ph0_platform import events, integration
from app.ph0_platform import event_catalog as ev


@events.subscribe(ev.DON_BO_SUNG_DA_CHOT, "ph0.integration.erp_don_bo_sung")
def write_replenishment_file(s, p: dict, _ma: str) -> None:
    rows = [{"ma_don_bs": p["ma_don_bs"], "ma_npp": p["ma_npp"], "ma_kho": p["ma_kho"], "ma_sp": d["ma_sp"],
             "so_luong": d["so_luong"]} for d in p["dong"]]
    integration.write_exchange_file(integration.KENH_ERP_RA, p["ma_don_bs"], p["phien_ban"], rows)


def scan_erp_inbound() -> dict:
    """Quét 15 phút/lần: phiếu xuất nhà máy (mã lô, NSX, HSD) -> hàng đang về của PH2. Lỗi thì chuyển ngăn 'loi'."""
    from app.ph2_inventory.models import HangDangVe, LoHang

    ok, bad = 0, 0
    for path in sorted(integration.exchange_dir(integration.KENH_ERP_VAO).glob("*.csv")):
        try:
            rows = integration.read_exchange_file(path)
            with tx() as s:
                for r in rows:
                    if s.get(LoHang, r["ma_lo"]) is None:   # BR2.1: lô lấy từ phiếu xuất nhà máy, không nhập tay
                        s.add(LoHang(ma_lo=r["ma_lo"], ma_sp=r["ma_sp"], nsx=date.fromisoformat(r["nsx"]),
                                     hsd=date.fromisoformat(r["hsd"])))
                        s.flush()
                    exists = s.scalar(select(HangDangVe).where(HangDangVe.ma_phieu_erp == r["ma_phieu_erp"],
                                                               HangDangVe.ma_lo == r["ma_lo"]))
                    if exists is None:
                        s.add(HangDangVe(ma_phieu_erp=r["ma_phieu_erp"], ma_kho=r["ma_kho"], ma_sp=r["ma_sp"],
                                         ma_lo=r["ma_lo"], nsx=date.fromisoformat(r["nsx"]),
                                         hsd=date.fromisoformat(r["hsd"]), so_luong=int(r["so_luong"]),
                                         ngay_ve_du_kien=date.fromisoformat(r["ngay_ve"])))
            integration.move(path, integration.KENH_ERP_VAO, "da_xu_ly")
            ok += 1
        except Exception:  # noqa: BLE001
            integration.move(path, integration.KENH_ERP_VAO, "loi")
            bad += 1
    return {"da_xu_ly": ok, "loi": bad}
