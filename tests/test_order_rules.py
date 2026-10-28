"""Giữ tồn nguyên tử, chống gửi trùng, ngân sách KM, kiểm soát tín dụng và các thời hạn BR-06."""
from datetime import date, timedelta

from app import clock
from tests.conftest import H, NOW
from tests.helpers import order, run_job


def _avail(client, tok, db, sp):
    return next(x for x in client.get(f"/ph1/catalog/{db}", headers=H(tok)).json() if x["ma_sp"] == sp)["ton_kha_dung"]


def test_last_cases_and_idempotency(client):
    # K02 còn 10 thùng SP01 bán được (lô đỏ 5 thùng không tính)
    assert _avail(client, "tok-db-02-001", "DB-02-001", "SP01") == 10
    a = order(client, "tok-db-02-001", "DB-02-001", [("SP01", 6)], khoa="khoa-A-0001")
    assert a.status_code == 200 and a.json()["trang_thai"] == "DA_DUYET"
    # Gửi lại cùng khóa (mạng chập chờn): cùng đơn, không giữ thêm
    again = order(client, "tok-db-02-001", "DB-02-001", [("SP01", 6)], khoa="khoa-A-0001")
    assert again.json()["ma_don"] == a.json()["ma_don"]
    # Người đến sau: không tạo đơn, nhận giỏ đã cập nhật
    b = order(client, "tok-db-02-002", "DB-02-002", [("SP01", 6), ("SP03", 2)])
    assert b.status_code == 409 and b.json()["error"]["code"] == "THIEU_HANG"
    assert b.json()["error"]["data"]["ton_kha_dung"] == {"SP01": 4}
    # Cả giỏ hoàn tác: SP03 cũng không bị giữ
    assert _avail(client, "tok-db-02-002", "DB-02-002", "SP03") == 120
    assert _avail(client, "tok-db-02-002", "DB-02-002", "SP01") == 4
    assert len(client.get("/ph1/orders", headers=H("tok-db-02-002")).json()) == 0


def test_promo_budget_never_overspent(client):
    r = client.post("/ph1/promotions", json={"ten": "SP05 giảm 10%", "ma_sp": "SP05", "muc_giam": 0.1,
                                             "tu_ngay": str(NOW.date()), "den_ngay": str(NOW.date() + timedelta(days=7)),
                                             "ngan_sach": 100_000}, headers=H("tok-pkd"))
    ma_km = r.json()["ma_km"]
    assert client.post(f"/ph1/promotions/{ma_km}/approve", headers=H("tok-pkd")).status_code == 403  # BR-13
    assert client.post(f"/ph1/promotions/{ma_km}/approve", headers=H("tok-gdkd")).json()["trang_thai"] == "da_duyet"
    first = order(client, "tok-db-01-001", "DB-01-001", [("SP05", 2)])
    assert first.json()["tong_km"] == 70_000
    second = order(client, "tok-db-01-002", "DB-01-002", [("SP05", 2)])
    assert second.status_code == 409 and second.json()["error"]["code"] == "KM_HET_NGAN_SACH"
    assert second.json()["error"]["data"]["tong_tien_khong_km"] == 700_000
    ok = order(client, "tok-db-01-002", "DB-01-002", [("SP05", 2)], bo_km=[ma_km])
    assert ok.status_code == 200 and ok.json()["tong_km"] == 0
    # Hủy đơn đầu: hoàn ngân sách cùng lúc với nhả tồn
    client.post(f"/ph1/orders/{first.json()['ma_don']}/cancel", json={"ly_do": "đặt nhầm"}, headers=H("tok-db-01-001"))
    third = order(client, "tok-db-01-003", "DB-01-003", [("SP05", 1)])
    assert third.json()["tong_km"] == 35_000


def test_over_limit_exception_approved(client):
    r = order(client, "tok-db-01-003", "DB-01-003", [("SP03", 10)])    # hạn mức 2 triệu
    o = r.json()
    assert o["trang_thai"] == "CHO_DIEM_BAN_CHON"
    r = client.post(f"/ph1/orders/{o['ma_don']}/credit-choice", json={"lua_chon": "xin_ngoai_le",
                                                                      "ly_do": "khách quen, mùa cưới"},
                    headers=H("tok-db-01-003"))
    assert r.json()["trang_thai"] == "CHO_DUYET_NGOAI_LE_TD"
    yc = client.get("/ph3/exceptions", headers=H("tok-ktt-01")).json()[0]
    assert client.get("/ph3/exceptions", headers=H("tok-ktt-02")).json() == []   # NPP khác không thấy
    client.post(f"/ph3/exceptions/{yc['ma_yc']}/decide", json={"duyet": True}, headers=H("tok-ktt-01"))
    o = client.get(f"/ph1/orders/{o['ma_don']}", headers=H("tok-db-01-003")).json()
    assert o["trang_thai"] == "DA_DUYET" and o["hinh_thuc_tt"] == "cong_no"
    assert client.get("/ph3/debt/DB-01-003", headers=H("tok-db-01-003")).json()["dang_giu"] == 3_200_000


def test_over_limit_timeout_releases_stock(client):
    before = _avail(client, "tok-db-01-003", "DB-01-003", "SP03")
    o = order(client, "tok-db-01-003", "DB-01-003", [("SP03", 10)]).json()
    assert _avail(client, "tok-db-01-003", "DB-01-003", "SP03") == before - 10
    clock.advance(minutes=31)
    run_job(client, "ph1.quet_don_qua_han")
    o = client.get(f"/ph1/orders/{o['ma_don']}", headers=H("tok-db-01-003")).json()
    assert o["trang_thai"] == "DA_HUY" and "qua_han_cho_diem_ban_chon" in o["ly_do"]
    assert _avail(client, "tok-db-01-003", "DB-01-003", "SP03") == before


def test_exception_deadline_is_working_hours(client):
    clock.set_now(NOW.replace(hour=15))     # 15h thứ Tư -> 4 giờ làm việc = 10h thứ Năm
    o = order(client, "tok-db-01-003", "DB-01-003", [("SP03", 10)]).json()
    o = client.post(f"/ph1/orders/{o['ma_don']}/credit-choice", json={"lua_chon": "xin_ngoai_le", "ly_do": "x"},
                    headers=H("tok-db-01-003")).json()
    assert o["han_trang_thai"].startswith("2026-10-29T10:00")


def test_overdue_outlet_must_pay_on_delivery(client):
    o = order(client, "tok-db-01-002", "DB-01-002", [("SP03", 2)]).json()
    assert o["trang_thai"] == "DA_DUYET" and o["hinh_thuc_tt"] == "tra_ngay"


def test_policy_exception_goes_to_npp(client):
    o = order(client, "tok-db-01-001", "DB-01-001", [("SP03", 2)], yc_chiet_khau_pct=2).json()
    assert o["trang_thai"] == "CHO_NPP_DUYET"
    assert client.post(f"/ph1/orders/{o['ma_don']}/npp-decision", json={"duyet": True},
                       headers=H("tok-npp-02")).status_code == 404     # NPP khác: như không tồn tại
    r = client.post(f"/ph1/orders/{o['ma_don']}/npp-decision", json={"duyet": True}, headers=H("tok-npp-01"))
    assert r.json()["trang_thai"] == "DA_DUYET"
    o = client.get(f"/ph1/orders/{o['ma_don']}", headers=H("tok-npp-01")).json()
    assert o["tu_dong_duyet"] is False


def test_cutoff_moves_delivery_date(client):
    clock.set_now(NOW.replace(hour=17))
    o = order(client, "tok-db-01-001", "DB-01-001", [("SP03", 2)]).json()
    assert o["ngay_giao"] == str(NOW.date() + timedelta(days=2))


def test_nvbh_must_check_in_before_ordering(client):
    r = order(client, "tok-bh-01", "DB-01-005", [("SP03", 2)], nguon="nvbh")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CHUA_CHECK_IN"


def test_data_isolation_between_npps(client):
    o = order(client, "tok-db-01-001", "DB-01-001", [("SP03", 2)]).json()
    for tok in ("tok-npp-02", "tok-db-01-002", "tok-kt-02"):
        assert client.get(f"/ph1/orders/{o['ma_don']}", headers=H(tok)).status_code == 404
    assert client.get("/ph3/debt/DB-01-001", headers=H("tok-npp-02")).status_code == 404
    assert client.get("/ph2/stock/K01", headers=H("tok-npp-02")).status_code == 404
    assert all(x["ma_diem_ban"].startswith("DB-02") for x in client.get("/ph1/orders", headers=H("tok-npp-02")).json())
