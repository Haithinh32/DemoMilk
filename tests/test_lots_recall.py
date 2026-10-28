"""PH2 CN2 (quét lô, đổi lô) và CN5 (khóa lô, truy xuất, thu hồi -> PH3 cấn trừ -> PH4 trừ điểm)."""
from tests.conftest import H
from tests.helpers import full_delivery, order, pick_list_of


def test_lot_swap_rules(client):
    o = order(client, "tok-db-01-001", "DB-01-001", [("SP01", 10)]).json()
    pl = pick_list_of(client, "01", o["ma_don"])
    line = pl["dong"][0]
    url = f"/ph2/pick-lists/{pl['ma_phieu']}/scan"
    # Lô đỏ bị chặn
    r = client.post(url, json={"dong_id": line["id"], "ma_lo_quet": "LSP01K01A"}, headers=H("tok-tk-01"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "LO_KHONG_HOP_LE"
    # Đổi lô phải có lý do; lô có hạn xa hơn -> cảnh báo FEFO
    r = client.post(url, json={"dong_id": line["id"], "ma_lo_quet": "LSP01K01C"}, headers=H("tok-tk-01"))
    assert r.json()["error"]["code"] == "CAN_LY_DO_DOI_LO"
    r = client.post(url, json={"dong_id": line["id"], "ma_lo_quet": "LSP01K01C", "ly_do": "vi_tri_kho_lay"},
                    headers=H("tok-tk-01"))
    assert r.json()["canh_bao_fefo"] is True
    # NVGH không được quét soạn hàng
    r = client.post(url, json={"dong_id": line["id"], "ma_lo_quet": "LSP01K01B"}, headers=H("tok-gh-01"))
    assert r.status_code == 403


def test_lock_trace_recall_offset(client):
    # Lô LSP03X nằm ở cả K01 và K02; giao cho một điểm bán mỗi NPP
    o1, pl1 = full_delivery(client, "tok-db-01-001", "01", "DB-01-001", [("SP03", 5)])
    o2, pl2 = full_delivery(client, "tok-db-02-001", "02", "DB-02-001", [("SP03", 3)])
    assert pl1["dong"][0]["ma_lo_quet"] == "LSP03X" and pl2["dong"][0]["ma_lo_quet"] == "LSP03X"
    debt_before = client.get("/ph3/debt/DB-01-001", headers=H("tok-db-01-001")).json()["du_no"]
    points_before = client.get("/ph4/points/DB-01-001", headers=H("tok-db-01-001")).json()["diem"]

    # Đơn đã duyệt đang chờ soạn với lô này -> khóa lô thì dòng phiếu chuyển sang lô khác
    pending = order(client, "tok-db-01-002", "DB-01-002", [("SP03", 4)]).json()
    assert pick_list_of(client, "01", pending["ma_don"])["dong"][0]["ma_lo_de_xuat"] == "LSP03X"

    assert client.post("/ph2/lots/LSP03X/lock", json={"ly_do": "khiếu nại vị lạ"}, headers=H("tok-npp-01")).status_code == 403
    r = client.post("/ph2/lots/LSP03X/lock", json={"ly_do": "khiếu nại vị lạ"}, headers=H("tok-qa"))
    assert r.json()["trang_thai"] == "khoa"
    assert pick_list_of(client, "01", pending["ma_don"])["dong"][0]["ma_lo_de_xuat"] == "LSP03K01C"
    # Lô khóa không còn trong tồn khả dụng ở mọi kho
    cat = client.get("/ph1/catalog/DB-02-001", headers=H("tok-db-02-001")).json()
    assert next(x for x in cat if x["ma_sp"] == "SP03")["ton_kha_dung"] == 80

    # Truy xuôi: QA thấy cả hai NPP; NPP chỉ thấy phần của mình
    t = client.get("/ph2/lots/LSP03X/trace", headers=H("tok-qa")).json()
    assert {d["ma_diem_ban"]: d["so_luong"] for d in t["diem_ban"]} == {"DB-01-001": 5, "DB-02-001": 3}
    assert t["thoi_gian_truy_xuat_ms"] < 5 * 60 * 1000          # KPI8
    t2 = client.get("/ph2/lots/LSP03X/trace", headers=H("tok-npp-02")).json()
    assert [d["ma_diem_ban"] for d in t2["diem_ban"]] == ["DB-02-001"] and set(t2["kho"]) == {"K02"}

    # Thu hồi -> nhập khu hàng hỏng theo số thực nhận -> PH3 cấn trừ -> PH4 trừ điểm
    vu = client.post("/ph2/lots/LSP03X/recall", json={"ly_do": "kiểm nghiệm không đạt"}, headers=H("tok-qa")).json()
    assert vu["so_nhiem_vu"] == 2
    tasks = client.get(f"/ph2/recalls/{vu['ma_vu']}/tasks", headers=H("tok-tk-01")).json()
    assert len(tasks) == 1
    r = client.post(f"/ph2/recall-tasks/{tasks[0]['ma_nhiem_vu']}/receive", json={"so_luong_thuc_nhan": 4},
                    headers=H("tok-tk-01"))
    assert r.status_code == 200
    gia = next(d for d in o1["dong"] if d["ma_sp"] == "SP03")["thanh_tien"] // 5
    debt_after = client.get("/ph3/debt/DB-01-001", headers=H("tok-db-01-001")).json()["du_no"]
    assert debt_before - debt_after == 4 * gia
    assert client.get("/ph4/points/DB-01-001", headers=H("tok-db-01-001")).json()["diem"] == \
        points_before - (4 * gia) // 10_000
    # Không mở khóa được khi vụ thu hồi còn mở
    assert client.post("/ph2/lots/LSP03X/unlock", json={"ket_qua_kiem_nghiem": "đạt"},
                       headers=H("tok-qa")).status_code == 409
    closed = client.post(f"/ph2/recalls/{vu['ma_vu']}/close", headers=H("tok-qa")).json()
    assert closed["ty_le_thu_48h"] == 4 / 8 and closed["chua_thu"] == ["DB-02-001"]


def test_delivery_requires_proof_and_is_idempotent(client):
    from tests.helpers import pick_and_issue
    o = order(client, "tok-db-01-001", "DB-01-001", [("SP03", 2)]).json()
    pl = pick_and_issue(client, "01", o["ma_don"])
    dong = [{"ma_sp": "SP03", "ma_lo": pl["dong"][0]["ma_lo_quet"], "so_luong": 2}]
    url = f"/ph2/deliveries/{pl['ma_phieu']}/confirm"
    r = client.post(url, json={"ma_su_kien": "EVT-1", "dong": dong, "bang_chung": {}}, headers=H("tok-gh-01"))
    assert r.json()["error"]["code"] == "THIEU_BANG_CHUNG"
    body = {"ma_su_kien": "EVT-1", "dong": dong, "bang_chung": {"chu_ky": "base64..."}}
    assert client.post(url, json=body, headers=H("tok-gh-01")).status_code == 200
    assert client.post(url, json=body, headers=H("tok-gh-01")).json()["lap_lai"] is True   # đồng bộ lại
    assert len(client.get("/ph3/debt/DB-01-001", headers=H("tok-db-01-001")).json()["hoa_don_mo"]) == 1
