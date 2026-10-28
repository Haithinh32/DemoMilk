"""Đăng ký tác vụ định kỳ của mọi phân hệ vào Bộ lập lịch (PH0)."""
from datetime import date

from sqlalchemy import select

from app import clock
from app.db import tx
from app.ph0_platform.identity import SYSTEM
from app.ph0_platform.integration_handlers import scan_erp_inbound
from app.ph0_platform.models import NPP
from app.ph0_platform.scheduler import job
from app.ph1_order import service as ph1
from app.ph2_inventory import forecast_nc2
from app.ph2_inventory import service as ph2
from app.ph3_credit import ledger, scoring_nc1
from app.ph4_sales import dashboard, suggest_nc1


def _d(ngay: str | None) -> date | None:
    return date.fromisoformat(ngay) if ngay else None


job("ph1.quet_don_qua_han", "Hủy đơn quá hạn trạng thái chờ, nhả tồn/hạn mức/ngân sách (BR-06)", "mỗi phút", 60)(
    lambda: {"da_huy": ph1.expire_orders()})
job("ph1.thu_lai_tin_dung", "Thử lại kiểm tra tín dụng khi PH3 chưa phản hồi", "mỗi phút", 60)(
    lambda: {"so_don": ph1.retry_credit_checks()})
job("ph2.nha_luot_giu_qua_han", "Lưới an toàn: nhả lượt giữ quá hạn", "mỗi phút", 60)(
    lambda: {"so_don": ph2.expire_reservations()})
job("ph0.quet_tep_erp", "Nhận phiếu xuất nhà máy từ ERP qua thư mục trao đổi", "15 phút", 900)(scan_erp_inbound)
job("ph2.nc2_du_bao_bo_sung", "NC2: dự báo 14 ngày và đơn đề xuất bổ sung", "23h hằng ngày")(
    lambda ngay=None: forecast_nc2.run(_d(ngay)))
job("ph2.nc2_lo_vang", "NC2: phân bổ lô vàng (điều chuyển / xả lô)", "5h hằng ngày")(
    lambda ngay=None: forecast_nc2.plan_yellow_lots(_d(ngay)))
job("ph3.quet_no_qua_han", "Nhắc nợ trước hạn, giao nhiệm vụ thu nợ cho PH4", "7h hằng ngày")(
    lambda: {"nhiem_vu": ledger.scan_overdue()})


@job("ph3.khoa_so_ngay", "Đối soát 3 nguồn và khóa sổ từng NPP", "23h hằng ngày")
def _close_all(ngay: str | None = None):
    out = []
    with tx() as s:
        npps = list(s.scalars(select(NPP.ma_npp)))
    for ma in npps:
        with tx() as s:
            out.append(ledger.close_day(s, SYSTEM, ma, _d(ngay) or clock.today()))
    return out


job("ph3.nc1_cham_diem", "NC1: chấm điểm tín dụng và đề xuất hạn mức", "đầu tháng")(
    lambda ky=None: scoring_nc1.train_and_score(_d(ky)))
job("ph4.nap_kho_du_lieu", "Nạp dữ liệu ngày vào kho dữ liệu + kiểm tra chất lượng", "1h hằng ngày, đơn theo giờ")(
    lambda ngay=None: dashboard.load_warehouse(_d(ngay)))
job("ph4.tinh_kpi", "Tính KPI 4 phân hệ, cảnh báo vượt ngưỡng", "sau khi nạp")(
    lambda ngay=None: dashboard.compute_kpis(_d(ngay)))
job("ph4.nc1_goi_y_don", "NC1: sinh đơn gợi ý cho từng điểm bán", "hằng đêm")(
    lambda ngay=None: suggest_nc1.generate(_d(ngay)))
