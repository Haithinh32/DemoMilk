"""Kịch bản demo xuyên 4 phân hệ, gọi qua HTTP như các app thật (không cần chạy server).

python -m scripts.demo
In từng bước: phân hệ nào làm gì, sự kiện nào đi qua bus. Dữ liệu lịch sử là MÔ PHỎNG.
"""
import json
import os
import sys
import uuid
from datetime import datetime

os.environ.setdefault("CSM_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "demo"))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app import clock, db, seed  # noqa: E402
from app.main import app  # noqa: E402
from app.ph0_platform import integration  # noqa: E402


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def step(title, data=None):
    print(f"\n=== {title}")
    if data is not None:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str)[:1500])


def main():
    clock.set_now(datetime(2026, 10, 28, 9, 0))
    db.init_engine(os.getenv("CSM_DEMO_DB_URL")
                   or f"sqlite:///{os.path.abspath(os.environ['CSM_DATA_DIR'])}/demo.db".replace("\\", "/"))
    seed.reset_and_seed()
    c = TestClient(app)
    run = lambda ten, **kw: c.post(f"/ph0/scheduler/run/{ten}", json=kw or None, headers=H("tok-admin")).json()

    step("PH4 NC1 – sinh đơn gợi ý hằng đêm", run("ph4.nc1_goi_y_don"))
    cart = c.get("/ph1/cart/from-suggestion/DB-01-001", headers=H("tok-db-01-001")).json()
    step("PH1 – điểm bán mở đơn gợi ý (đã lọc theo tồn khả dụng PH2)", cart["dong"])

    o = c.post("/ph1/orders", headers=H("tok-db-01-001"), json={
        "ma_diem_ban": "DB-01-001", "khoa_chong_trung": uuid.uuid4().hex, "nguon": "goi_y", "ma_goi_y": cart["ma_goi_y"],
        "dong": [{"ma_sp": "SP01", "so_luong": 10}, {"ma_sp": "SP02", "so_luong": 5}]}).json()
    step("PH1 CN2+CN3 – giữ tồn cả giỏ (PH2) -> kiểm tra tín dụng (PH3) -> duyệt tự động",
         {k: o[k] for k in ("ma_don", "trang_thai", "tu_dong_duyet", "tong_tien", "ngay_giao")})

    last = c.post("/ph1/orders", headers=H("tok-db-02-001"), json={
        "ma_diem_ban": "DB-02-001", "khoa_chong_trung": uuid.uuid4().hex, "dong": [{"ma_sp": "SP01", "so_luong": 12}]})
    step("PH1/PH2 – đặt quá tồn khả dụng: không tạo đơn, trả giỏ đã điều chỉnh", last.json())

    pl = next(p for p in c.get("/ph2/pick-lists", headers=H("tok-tk-01")).json() if p["ma_don"] == o["ma_don"])
    pl = c.get(f"/ph2/pick-lists/{pl['ma_phieu']}", headers=H("tok-tk-01")).json()
    step("PH2 CN2 – nhận lệnh xuất qua bus, đề xuất lô FEFO (bỏ lô đỏ)", pl["dong"])
    for d in pl["dong"]:
        c.post(f"/ph2/pick-lists/{pl['ma_phieu']}/scan", json={"dong_id": d["id"], "ma_lo_quet": d["ma_lo_de_xuat"]},
               headers=H("tok-tk-01"))
    c.post(f"/ph2/pick-lists/{pl['ma_phieu']}/confirm-issue", headers=H("tok-tk-01"))
    c.post(f"/ph2/deliveries/{pl['ma_phieu']}/confirm", headers=H("tok-gh-01"), json={
        "ma_su_kien": "EVT-DEMO-1", "bang_chung": {"anh_url": "s3://giao/demo.jpg"},
        "dong": [{"ma_sp": d["ma_sp"], "ma_lo": d["ma_lo_de_xuat"], "so_luong": d["so_luong"]} for d in pl["dong"]]})
    debt = c.get("/ph3/debt/DB-01-001", headers=H("tok-db-01-001")).json()
    step("Sự kiện 'Đã giao' -> PH3 ghi phải thu + PH4 cộng điểm",
         {"cong_no": debt, "diem": c.get("/ph4/points/DB-01-001", headers=H("tok-db-01-001")).json()})

    so_hd = debt["hoa_don_mo"][0]["so_hoa_don"]
    qr = c.get(f"/ph3/qr/{so_hd}", headers=H("tok-db-01-001")).json()
    body = json.dumps({"ma_gd_ngan_hang": "FT-DEMO-1", "so_tai_khoan": qr["so_tai_khoan"], "so_tien": qr["so_tien"],
                       "noi_dung": qr["noi_dung"]}).encode()
    hdr = {"X-Signature": integration.sign_bank_payload(body), "Content-Type": "application/json"}
    step("PH3 CN3 – báo có VietQR, gạch nợ tự động", c.post("/ph3/bank/webhook", content=body, headers=hdr).json())
    step("PH3 CN3 – báo có trùng (lỗi mạng ngân hàng) bị bỏ qua",
         c.post("/ph3/bank/webhook", content=body, headers=hdr).json())
    step("PH3 CN3 – đối soát 3 nguồn và khóa sổ, ghi bút toán cho NPP",
         c.post("/ph3/close-day/NPP01", headers=H("tok-ktt-01")).json())

    step("PH2 CN5 – QA khóa lô, truy xuôi đến điểm bán",
         c.post("/ph2/lots/LSP01K01B/lock", json={"ly_do": "khiếu nại vị chua"}, headers=H("tok-qa")).json())
    step("Truy xuất lô", c.get("/ph2/lots/LSP01K01B/trace", headers=H("tok-qa")).json())

    step("PH2 NC2 – dự báo & đơn đề xuất bổ sung", run("ph2.nc2_du_bao_bo_sung"))
    step("PH1 NC1 – đề xuất KM SP03 trong ngân sách 5 triệu",
         [{k: v for k, v in o.items() if k != "don_vi"} for o in c.post("/ph1/nc1/propose", headers=H("tok-pkd"), json={
             "ma_sp": "SP03", "tu_ngay": "2026-11-02", "den_ngay": "2026-11-15", "ngan_sach": 5_000_000}).json()["phuong_an"]])
    step("PH3 NC1 – chấm điểm tín dụng", run("ph3.nc1_cham_diem"))
    run("ph4.nap_kho_du_lieu")
    run("ph4.tinh_kpi")
    d = c.get("/ph4/dashboard", headers=H("tok-bdh")).json()
    step("PH4 CN5 – dashboard KPI 4 phân hệ", {"chi_so_chinh": d["chi_so_chinh"],
                                               "vuot_nguong": [k["ma_kpi"] for k in d["kpi"] if k["vuot_nguong"]]})
    ev = c.get("/ph0/events?limit=500", headers=H("tok-admin")).json()
    step("PH0 – sự kiện đã đi qua bus", sorted({e["loai"] for e in ev}))


if __name__ == "__main__":
    main()
