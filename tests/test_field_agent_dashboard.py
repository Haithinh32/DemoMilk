"""PH4 CN1 (đi tuyến, check-in, thu nợ khi ghé), agent Zalo (phạm vi công cụ), PH4 CN5 và bus sự kiện."""
from app import clock
from app.db import tx
from app.ph0_platform import events
from app.ph0_platform.models import SuKien
from tests.conftest import H, NOW
from tests.helpers import full_delivery, order, run_job


def _visit(client, tok, ma, db, lat, lng, **kw):
    v = {"ma_luot_ghe": ma, "ma_diem_ban": db, "thoi_gian_may": NOW.isoformat(), "lat": lat, "lng": lng, **kw}
    return client.post("/ph4/visits", json=[v], headers=H(tok)).json()[0]


def test_route_checkin_and_order_on_behalf(client):
    route = client.get("/ph4/route/today", headers=H("tok-bh-01")).json()
    first = route["diem_ban"][0]
    assert first["ma_diem_ban"] == "DB-01-001"
    far = _visit(client, "tok-bh-01", "LG-1", "DB-01-001", first["lat"] + 0.01, first["lng"])
    assert far["loi"] == "CHECK_IN_XA"
    photo = [{"url": "s3://a.jpg", "sha256": "abc", "thoi_gian": NOW.isoformat()}]
    ok = _visit(client, "tok-bh-01", "LG-2", "DB-01-001", first["lat"], first["lng"], anh=photo, het_hang=["SP01"])
    assert ok["trang_thai"] == "hop_le" and ok["dung_tuyen"] is True
    assert _visit(client, "tok-bh-01", "LG-2", "DB-01-001", first["lat"], first["lng"])["lap_lai"] is True
    # Dùng lại ảnh cũ ở điểm bán khác -> nghi vấn, chuyển giám sát
    db2 = route["diem_ban"][1]
    sus = _visit(client, "tok-bh-01", "LG-3", db2["ma_diem_ban"], db2["lat"], db2["lng"], anh=photo)
    assert sus["trang_thai"] == "nghi_van" and "anh_trung_luot_ghe_khac" in sus["ly_do"]
    # Đã check-in thì NVBH đặt hộ được (đơn nguồn nvbh)
    r = order(client, "tok-bh-01", "DB-01-001", [("SP03", 2)], nguon="nvbh")
    assert r.status_code == 200 and r.json()["nguon"] == "nvbh"


def test_collection_task_flows_ph3_to_ph4_and_back(client):
    run_job(client, "ph3.quet_no_qua_han")
    from app.ph4_sales.models import DiemBan
    with tx() as s:
        d = s.get(DiemBan, "DB-01-002")
        lat, lng = d.lat, d.lng
    v = _visit(client, "tok-bh-01", "LG-TN", "DB-01-002", lat, lng,
               thu_no=[{"ma_nhiem_vu": "TN-HD-SEED00002", "so_tien_thu": 2_000_000}])
    assert v["trang_thai"] == "hop_le"
    debt = client.get("/ph3/debt/DB-01-002", headers=H("tok-db-01-002")).json()
    assert debt["qua_han"] == 0 and debt["du_no"] == 0


def test_agent_tools_are_scoped_and_drafts_go_through_ph1(client):
    t = client.post("/ph0/agent/tools/xem_cong_no?zalo_id=zalo-01-002", json={}).json()
    assert t["ok"] and t["ma_diem_ban"] == "DB-01-002" and t["qua_han"] == 2_000_000
    # QR của hóa đơn thuộc điểm bán khác bị từ chối
    other = client.post("/ph0/agent/tools/tao_ma_qr?zalo_id=zalo-01-001", json={"so_hoa_don": "HD-SEED00002"}).json()
    assert other["ok"] is False
    draft = client.post("/ph0/agent/tools/tao_don_nhap?zalo_id=zalo-01-001",
                        json={"dong": [{"ma_sp": "SP01", "so_luong": 500}, {"ma_sp": "SP03", "so_luong": 2}]}).json()
    assert draft["da_dieu_chinh_theo_ton"] == {"SP01": 180}
    # Chưa xác nhận thì chưa có đơn, chưa giữ tồn
    assert client.get("/ph1/orders", headers=H("tok-db-01-001")).json() == []
    o = client.post(f"/ph1/agent-drafts/{draft['ma_nhap']}/confirm", headers=H("tok-db-01-001")).json()
    assert o["nguon"] == "agent" and o["trang_thai"] in ("DA_DUYET", "CHO_DIEM_BAN_CHON", "CHO_NPP_DUYET")
    # Điểm bán khác không xác nhận hộ được
    d2 = client.post("/ph0/agent/tools/tao_don_nhap?zalo_id=zalo-01-001",
                     json={"dong": [{"ma_sp": "SP03", "so_luong": 2}]}).json()
    assert client.post(f"/ph1/agent-drafts/{d2['ma_nhap']}/confirm", headers=H("tok-db-01-002")).status_code == 404
    clock.advance(minutes=31)
    assert client.post(f"/ph1/agent-drafts/{d2['ma_nhap']}/confirm",
                       headers=H("tok-db-01-001")).json()["error"]["code"] == "DON_NHAP_HET_HAN"


def test_dashboard_kpis_and_scope(client):
    full_delivery(client, "tok-db-01-001", "01", "DB-01-001", [("SP03", 5)])
    load = run_job(client, "ph4.nap_kho_du_lieu")
    assert load["kiem_tra"] == "dat" and load["so_dong"] == 1
    alerts = run_job(client, "ph4.tinh_kpi")["canh_bao"]
    assert any(a["kpi"] == "ty_le_ghe_dung_tuyen" for a in alerts)    # chưa ai đi tuyến hôm nay
    d = client.get("/ph4/dashboard", headers=H("tok-bdh")).json()
    phan_he = {k["phan_he"] for k in d["kpi"]}
    assert phan_he == {"PH1", "PH2", "PH3", "PH4"} and d["pham_vi"] == "CONG_TY"
    assert client.get("/ph4/dashboard?ma_npp=NPP02", headers=H("tok-npp-01")).json()["pham_vi"] == "NPP01"
    drill = client.get("/ph4/dashboard/drill?cap=vung", headers=H("tok-bdh")).json()
    assert {r["vung"] for r in drill} >= {"TH-TP"}


def test_event_bus_retries_and_delivers_once(client):
    calls = {"n": 0}

    @events.subscribe("test.su_kien", "test.ben_nhan")
    def flaky(s, p, ma):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("lỗi tạm thời")

    with tx() as s:
        events.publish(s, "test.su_kien", {"x": 1}, ma_su_kien="EV-TEST-1")
        events.publish(s, "test.su_kien", {"x": 1}, ma_su_kien="EV-TEST-1")   # phát trùng: bỏ qua
    events.dispatch_pending()
    with tx() as s:
        ev = s.get(SuKien, "EV-TEST-1")
        assert ev.trang_thai == "cho" and ev.so_lan_thu == 1
    events.dispatch_pending()
    events.dispatch_pending()
    with tx() as s:
        assert s.get(SuKien, "EV-TEST-1").trang_thai == "xong"
    assert calls["n"] == 2
    events._handlers["test.su_kien"].clear()
