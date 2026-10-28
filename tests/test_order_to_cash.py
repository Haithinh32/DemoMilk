"""Chu trình Bán hàng – Thu tiền xuyên 4 phân hệ (Hình 2.1): đặt -> giữ tồn -> tín dụng -> duyệt -> FEFO ->
giao -> phải thu -> VietQR -> gạch nợ -> khóa sổ -> bút toán; cộng điểm ở PH4."""
from app.ph0_platform import integration
from tests.conftest import H
from tests.helpers import bank_credit, deliver, order, pick_and_issue, pick_list_of


def test_order_to_cash(client):
    tok = "tok-db-01-001"
    r = order(client, tok, "DB-01-001", [("SP01", 10), ("SP02", 5)])
    assert r.status_code == 200, r.text
    o = r.json()
    # Duyệt tự động; KM SP02 5% tự áp từ bảng đã duyệt
    assert o["trang_thai"] == "DA_DUYET" and o["tu_dong_duyet"] is True
    sp02 = next(d for d in o["dong"] if d["ma_sp"] == "SP02")
    assert sp02["ma_km"] == "KM-SP02-5PCT" and sp02["tien_km"] == 65_000
    assert o["tong_tien"] == 10 * 300_000 + 5 * 260_000 - 65_000

    # PH2 nhận lệnh xuất: đề xuất lô FEFO, bỏ lô đỏ LSP01K01A (còn 2 ngày)
    pl = pick_list_of(client, "01", o["ma_don"])
    assert {d["ma_sp"]: d["ma_lo_de_xuat"] for d in pl["dong"]} == {"SP01": "LSP01K01B", "SP02": "LSP02K01B"}
    pl = pick_and_issue(client, "01", o["ma_don"])
    assert client.get(f"/ph1/orders/{o['ma_don']}", headers=H(tok)).json()["trang_thai"] == "CHO_GIAO"

    # Giao thiếu: điểm bán từ chối 2 thùng SP01 -> hàng mang về nhập lại đúng lô cũ
    deliver(client, "01", pl, {("SP01", "LSP01K01B"): 8})
    o2 = client.get(f"/ph1/orders/{o['ma_don']}", headers=H(tok)).json()
    assert o2["trang_thai"] == "DA_GIAO"
    sp01 = next(x for x in client.get("/ph1/catalog/DB-01-001", headers=H(tok)).json() if x["ma_sp"] == "SP01")
    assert sp01["ton_kha_dung"] == 180 - 10 + 2

    # PH3: phải thu theo số THỰC GIAO, hạn mức giữ đã chuyển thành dư nợ
    debt = client.get("/ph3/debt/DB-01-001", headers=H(tok)).json()
    expected = 8 * 300_000 + 5 * 247_000
    assert debt["du_no"] == expected and debt["dang_giu"] == 0
    so_hd = debt["hoa_don_mo"][0]["so_hoa_don"]
    # PH4: cộng điểm theo giá trị thực giao
    assert client.get("/ph4/points/DB-01-001", headers=H(tok)).json()["diem"] == expected // 10_000

    # VietQR: trả 2 đợt, báo có trùng chỉ gạch một lần (BR-07)
    qr = client.get(f"/ph3/qr/{so_hd}", headers=H(tok)).json()
    assert qr["noi_dung"] == f"CSM {so_hd}" and qr["so_tien"] == expected
    r1 = bank_credit(client, "1001001", 1_000_000, qr["noi_dung"], ma_gd="FT001")
    assert r1.json()["trang_thai"] == "da_gach_no"
    assert bank_credit(client, "1001001", 1_000_000, qr["noi_dung"], ma_gd="FT001").json()["trang_thai"] == "trung"
    bank_credit(client, "1001001", expected - 1_000_000, qr["noi_dung"], ma_gd="FT002")
    debt = client.get("/ph3/debt/DB-01-001", headers=H(tok)).json()
    assert debt["du_no"] == 0

    # Chữ ký sai bị từ chối
    bad = client.post("/ph3/bank/webhook", content=b'{"x":1}', headers={"X-Signature": "sai"})
    assert bad.status_code == 401

    # Khóa sổ ngày: ngân hàng + quỹ − đã ghi nhận = 0 -> khóa, ghi bút toán cho phần mềm kế toán NPP
    r = client.post("/ph3/close-day/NPP01", headers=H("tok-ktt-01"))
    assert r.json()["khoa_so"] is True and r.json()["chenh_lech"] == 0
    files = list(integration.exchange_dir(integration.KENH_KE_TOAN_NPP).glob("BT-NPP01-*.csv"))
    assert files and integration.read_exchange_file(files[0])

    # Không còn sự kiện lỗi trên bus
    assert client.get("/ph0/events?trang_thai=loi", headers=H("tok-admin")).json() == []


def test_unmatched_payment_blocks_day_close(client):
    r = bank_credit(client, "1001001", 500_000, "chuyen tien hang thang 10")
    assert r.json()["trang_thai"] == "cho_xu_ly"
    close = client.post("/ph3/close-day/NPP01", headers=H("tok-ktt-01")).json()
    assert close["khoa_so"] is False and close["giao_dich_cho_xu_ly"] == 1
    # Kế toán chỉ định hóa đơn -> đối soát khớp -> khóa được
    pending = client.get("/ph3/payments/pending", headers=H("tok-kt-01")).json()
    client.post(f"/ph3/payments/{pending[0]['ma_gd']}/assign", json={"so_hoa_don": "HD-SEED00002"},
                headers=H("tok-kt-01"))
    assert client.post("/ph3/close-day/NPP01", headers=H("tok-ktt-01")).json()["khoa_so"] is True
    # Sổ đã khóa: báo có mới của ngày đó không ghi đè; sửa phải qua bút toán điều chỉnh
    r = client.post("/ph3/adjustments/NPP01", json={"ngay": "2026-10-28", "no_tk": "131", "co_tk": "112",
                                                     "so_tien": 10_000, "ly_do": ""}, headers=H("tok-ktt-01"))
    assert r.status_code == 400


def test_cash_receipt_and_handover(client):
    from tests.helpers import full_delivery
    o, _ = full_delivery(client, "tok-db-01-001", "01", "DB-01-001", [("SP03", 2)])
    so_hd = client.get("/ph3/debt/DB-01-001", headers=H("tok-db-01-001")).json()["hoa_don_mo"][0]["so_hoa_don"]
    body = {"so_hoa_don": so_hd, "so_tien": 640_000, "ma_bien_nhan": "BN-112"}
    assert client.post("/ph3/cash", json=body, headers=H("tok-gh-01")).json()["trang_thai"] == "da_gach_no"
    assert client.post("/ph3/cash", json=body, headers=H("tok-gh-01")).json()["trang_thai"] == "trung"  # đồng bộ lại
    # NVGH nộp thiếu -> lệch, không khóa sổ được
    h = client.post("/ph3/cash-handover", json={"ma_nguoi_thu": "GH-01", "thuc_nop": 600_000},
                    headers=H("tok-tq-01")).json()
    assert h["chenh_lech"] == -40_000
    close = client.post("/ph3/close-day/NPP01", headers=H("tok-ktt-01")).json()
    assert close["khoa_so"] is False and close["chenh_lech"] == -40_000
