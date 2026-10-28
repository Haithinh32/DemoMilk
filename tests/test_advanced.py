"""4 chức năng nâng cao trong phạm vi cốt lõi: PH1 NC1, PH2 NC2, PH3 NC1, PH4 NC1 (dữ liệu lịch sử MÔ PHỎNG)."""
from app.db import tx
from app.ph1_order.models import ChuongTrinhKM, DonBoSung
from app.ph4_sales.models import GoiYDon
from tests.conftest import H
from tests.helpers import order, run_job


def test_ph4_nc1_suggestions_only_available_and_feed_ph1(client):
    res = run_job(client, "ph4.nc1_goi_y_don")
    assert res["so_goi_y"] > 0
    cat = {x["ma_sp"]: x["ton_kha_dung"] for x in client.get("/ph1/catalog/DB-01-001", headers=H("tok-db-01-001")).json()}
    cart = client.get("/ph1/cart/from-suggestion/DB-01-001", headers=H("tok-db-01-001")).json()
    assert cart["dong"] and all(0 < d["so_luong"] <= cat[d["ma_sp"]] for d in cart["dong"])   # BR14
    # Điểm bán mới (dưới 4 tuần lịch sử) dùng trung bình nhóm cùng vùng (BR9)
    new = client.get("/ph1/cart/from-suggestion/DB-01-040", headers=H("tok-admin")).json()
    assert {d["ly_do"] for d in new["dong"]} == {"trung_binh_nhom_cung_vung"}
    # Đặt một chạm: đi qua PH1 như đơn thường, PH4 ghi nhận gợi ý được chấp nhận
    o = order(client, "tok-db-01-001", "DB-01-001", [(d["ma_sp"], d["so_luong"]) for d in cart["dong"]],
              nguon="goi_y", ma_goi_y=cart["ma_goi_y"]).json()
    assert o["nguon"] == "goi_y"
    with tx() as s:
        assert s.get(GoiYDon, cart["ma_goi_y"]).trang_thai == "da_dat"


def test_ph2_nc2_replenishment_and_yellow_lots(client):
    run_job(client, "ph0.quet_tep_erp")                     # hàng đang về K02: 40 thùng SP04
    stock = client.get("/ph2/stock/K02", headers=H("tok-npp-02")).json()
    assert stock["hang_dang_ve"] == {"SP04": 40} and stock["ton_kha_dung"]["SP04"] == 90   # đang về không cộng
    res = run_job(client, "ph2.nc2_du_bao_bo_sung")
    assert {p["ma_kho"] for p in res["de_xuat_bo_sung"]} >= {"K02"}
    with tx() as s:
        bs = s.scalar(__import__("sqlalchemy").select(DonBoSung).where(DonBoSung.ma_kho == "K02"))
        line = next(l for l in bs.dong if l["ma_sp"] == "SP01")
        c = line["can_cu"]
        # Đề xuất = ⌈tồn mục tiêu − tồn khả dụng − hàng đang về⌉ (tồn mục tiêu hiển thị đã làm tròn 0,1)
        net = c["ton_muc_tieu"] - c["ton_kha_dung"] - c["hang_dang_ve"]
        assert -0.05 <= line["de_xuat"] - net < 1.05
        ma_bs = bs.ma_don_bs
    # NPP chỉnh lệch > 30% phải ghi lý do; PKD chốt -> tệp gửi ERP
    url = f"/ph1/replenishment/{ma_bs}/submit"
    r = client.post(url, json={"dieu_chinh": {"SP01": {"so_luong": 1}}}, headers=H("tok-npp-02"))
    assert r.json()["error"]["code"] == "CAN_LY_DO_LECH"
    client.post(url, json={"dieu_chinh": {"SP01": {"so_luong": 1, "ly_do": "sắp nghỉ lễ"}}}, headers=H("tok-npp-02"))
    assert client.post(f"/ph1/replenishment/{ma_bs}/confirm", headers=H("tok-pkd")).json()["trang_thai"] == "da_chot"
    from app.ph0_platform import integration
    assert list(integration.exchange_dir(integration.KENH_ERP_RA).glob(f"{ma_bs}_v1.csv"))

    plan = run_job(client, "ph2.nc2_lo_vang")
    # Lô vàng dư ở K01 -> ưu tiên điều chuyển sang K02 đang thiếu, phần còn lại thành đề xuất KM xả lô
    assert any(d["ma_lo"] == "LSP01K01B" and d["den"] == "K02" for d in plan["dieu_chuyen"])
    assert any(x["ma_lo"] == "LSP01K01B" for x in plan["xa_lo"])
    with tx() as s:
        km = s.scalars(__import__("sqlalchemy").select(ChuongTrinhKM).where(ChuongTrinhKM.nguon == "ph2_xa_lo")).all()
        assert km and all(k.trang_thai == "de_xuat" and k.ma_npp == "NPP01" for k in km)   # chờ GĐKD duyệt


def test_ph1_nc1_promo_proposal_beats_uniform_and_did(client):
    r = client.post("/ph1/nc1/propose", json={"ma_sp": "SP03", "tu_ngay": "2026-11-02", "den_ngay": "2026-11-15",
                                              "ngan_sach": 5_000_000}, headers=H("tok-pkd"))
    assert r.status_code == 200, r.text
    best, _, uniform = r.json()["phuong_an"]
    assert best["tong_chi_phi"] <= 5_000_000
    assert best["tong_loi_nhuan_tang_them"] >= uniform["tong_loi_nhuan_tang_them"]
    assert all(d["loi_nhuan_tang_them"] > 0 for d in best["don_vi"])          # không chọn tổ hợp lỗ
    assert best["don_vi_doi_chung"] and not {d["don_vi"] for d in best["don_vi"]} & set(best["don_vi_doi_chung"])
    # Mô phỏng: tạp hóa nhỏ gần như không phản ứng KM -> không được chọn
    assert not any(d["don_vi"].endswith("tap_hoa_nho") for d in best["don_vi"])
    # Tạo chương trình từ phương án: vẫn qua duyệt hai bước
    ma_km = client.post(f"/ph1/nc1/{r.json()['ma_pa']}/create-program", json={"chi_so": 0},
                        headers=H("tok-pkd")).json()["ma_km"]
    assert client.post(f"/ph1/promotions/{ma_km}/approve", headers=H("tok-gdkd")).json()["trang_thai"] == "da_duyet"
    # ROI thật của KM quá khứ bằng so sánh với đối chứng: 5% có lãi, giảm sâu thì lỗ
    roi = {k: client.get(f"/ph1/nc1/evaluate/{k}", headers=H("tok-pkd")).json()["roi_that"] for k in ("KMH-1", "KMH-2")}
    assert roi["KMH-1"] > 0 > roi["KMH-2"]


def test_ph3_nc1_credit_scoring(client):
    res = run_job(client, "ph3.nc1_cham_diem")
    assert res["chi_so"]["auc_logistic"] > 0.7
    by = res["ty_le_qua_han_theo_hang"]
    assert by["A"]["mean"] < by["D"]["mean"]
    scores = {x["ma_diem_ban"]: x for x in client.get("/ph3/nc1/scores", headers=H("tok-ktt-01")).json()}
    assert all(k.startswith("DB-01") for k in scores)
    assert scores["DB-01-002"]["hang"] == "D" and scores["DB-01-002"]["han_muc_de_xuat"] == 0
    assert scores["DB-01-040"]["trang_thai"] == "giu_mac_dinh"             # chưa đủ 6 tháng
    good = next(x for x in scores.values() if x["hang"] == "A")
    url = f"/ph3/nc1/scores/{good['id']}/decide"
    r = client.post(url, json={"han_muc_chot": good["han_muc_de_xuat"] * 2 + 1_000_000}, headers=H("tok-ktt-01"))
    assert r.json()["error"]["code"] == "CAN_LY_DO_LECH"
    r = client.post(url, json={}, headers=H("tok-ktt-01"))
    assert r.json()["han_muc"] == good["han_muc_de_xuat"]
    debt = client.get(f"/ph3/debt/{good['ma_diem_ban']}", headers=H("tok-ktt-01")).json()
    assert debt["han_muc"] == good["han_muc_de_xuat"]
