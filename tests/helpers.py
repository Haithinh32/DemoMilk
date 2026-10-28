import json
import uuid

from app.ph0_platform import integration
from tests.conftest import H


def order(client, token, ma_diem_ban, dong, **kw):
    body = {"ma_diem_ban": ma_diem_ban, "dong": [{"ma_sp": sp, "so_luong": q} for sp, q in dong],
            "khoa_chong_trung": kw.pop("khoa", uuid.uuid4().hex), **kw}
    return client.post("/ph1/orders", json=body, headers=H(token))


def pick_list_of(client, npp: str, ma_don: str) -> dict:
    lists = client.get("/ph2/pick-lists", headers=H(f"tok-tk-{npp}")).json()
    ma_phieu = next(p["ma_phieu"] for p in lists if p["ma_don"] == ma_don)
    return client.get(f"/ph2/pick-lists/{ma_phieu}", headers=H(f"tok-tk-{npp}")).json()


def pick_and_issue(client, npp: str, ma_don: str) -> dict:
    pl = pick_list_of(client, npp, ma_don)
    for d in pl["dong"]:
        r = client.post(f"/ph2/pick-lists/{pl['ma_phieu']}/scan",
                        json={"dong_id": d["id"], "ma_lo_quet": d["ma_lo_de_xuat"]}, headers=H(f"tok-tk-{npp}"))
        assert r.status_code == 200, r.text
    r = client.post(f"/ph2/pick-lists/{pl['ma_phieu']}/confirm-issue", headers=H(f"tok-tk-{npp}"))
    assert r.status_code == 200, r.text
    return client.get(f"/ph2/pick-lists/{pl['ma_phieu']}", headers=H(f"tok-tk-{npp}")).json()


def deliver(client, npp: str, pl: dict, giao: dict | None = None) -> dict:
    """giao: {(ma_sp, ma_lo): so_luong}; mặc định giao đủ."""
    dong = [{"ma_sp": d["ma_sp"], "ma_lo": d["ma_lo_quet"],
             "so_luong": (giao or {}).get((d["ma_sp"], d["ma_lo_quet"]), d["so_luong"])} for d in pl["dong"]]
    r = client.post(f"/ph2/deliveries/{pl['ma_phieu']}/confirm",
                    json={"ma_su_kien": f"EVT-{uuid.uuid4().hex[:8]}", "dong": dong,
                          "bang_chung": {"anh_url": "s3://giao/1.jpg"}}, headers=H(f"tok-gh-{npp}"))
    assert r.status_code == 200, r.text
    return r.json()


def full_delivery(client, token, npp, ma_diem_ban, dong):
    r = order(client, token, ma_diem_ban, dong)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["trang_thai"] == "DA_DUYET", o
    pl = pick_and_issue(client, npp, o["ma_don"])
    deliver(client, npp, pl)
    return o, pl


def bank_credit(client, so_tai_khoan, so_tien, noi_dung, ma_gd=None):
    body = json.dumps({"ma_gd_ngan_hang": ma_gd or f"FT{uuid.uuid4().hex[:10]}", "so_tai_khoan": so_tai_khoan,
                       "so_tien": so_tien, "noi_dung": noi_dung}).encode()
    return client.post("/ph3/bank/webhook", content=body,
                       headers={"X-Signature": integration.sign_bank_payload(body), "Content-Type": "application/json"})


def run_job(client, ten, **kw):
    r = client.post(f"/ph0/scheduler/run/{ten}", json=kw or None, headers=H("tok-admin"))
    assert r.status_code == 200, r.text
    return r.json()
