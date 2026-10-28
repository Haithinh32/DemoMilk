"""Dữ liệu mẫu cho vùng thí điểm (2 NPP) – mọi lịch sử bán và tín dụng là MÔ PHỎNG (mo_phong=True).

python -m app.seed      # tạo lại CSDL và nạp dữ liệu (xóa dữ liệu cũ!)
"""
import math
import random
from datetime import date, timedelta

import numpy as np
from sqlalchemy import insert

from app import clock, db
from app.ph0_platform import identity as R
from app.ph0_platform import integration
from app.ph0_platform.models import NPP, NguoiDung, SanPham
from app.ph1_order.models import BangGia, ChuongTrinhKM, DongGia
from app.ph2_inventory.models import Kho, LoHang, NhapKho, TonKhoLo, TonKhoSP
from app.ph3_credit.models import DwTinDungThang, HanMuc, KhoanPhaiThu
from app.ph4_sales.models import DiemBan, DwBanHangNgay, NguongKpi, SoDiem, Tuyen, TuyenDiemBan

SAN_PHAM = [  # ma, ten, nhiệt, hạn (ngày), hộp/thùng, biên LN, L (ngày phủ), giá/thùng, hệ số bán
    ("SP01", "Sữa tươi thanh trùng 1L", "lanh", 10, 12, 0.25, 2, 300_000, 1.2),
    ("SP02", "Sữa chua có đường 100g", "lanh", 14, 48, 0.30, 3, 260_000, 1.0),
    ("SP03", "Sữa tiệt trùng 180ml", "thuong", 180, 48, 0.30, 7, 320_000, 1.5),
    ("SP04", "Sữa chua uống 170ml", "lanh", 30, 48, 0.22, 3, 290_000, 0.8),
    ("SP05", "Sữa hộp xanh 1L", "thuong", 180, 12, 0.20, 7, 350_000, 1.0),
    ("SP06", "Váng sữa 55g", "lanh", 20, 24, 0.28, 3, 240_000, 0.5),
]
NPPS = [("NPP01", "NPP Thanh Hóa", "1001001", "K01", 19.807, 105.776, ["TH-TP", "TH-NT"]),
        ("NPP02", "NPP Nghệ An", "1002002", "K02", 18.679, 105.681, ["NA-TP", "NA-NT"])]
# tên, nhu cầu (thùng/tuần/SKU), uplift thật khi giảm 10% (mô phỏng: tạp hóa lớn phản ứng mạnh, nhỏ gần như không)
NHOM = [("tap_hoa_nho", 1.0, 0.2), ("tap_hoa_lon", 2.5, 1.0), ("cua_hang_sua", 1.8, 0.6)]
TY_LE_MUA_DON = 0.3   # 30% phần tăng thêm là mua dồn, trả lại trong 14 ngày sau KM
SO_DIEM_BAN = 40
SO_DIEM_BAN_MOI = 3
SO_NGAY_LICH_SU = 200
# Chương trình KM quá khứ của SP03 (để NC1 học uplift và đo ROI có đối chứng)
KM_QUA_KHU = [("KMH-1", 150, 0.05), ("KMH-2", 100, 0.10), ("KMH-3", 50, 0.15)]
DOI_CHUNG = ["TH-NT|tap_hoa_lon", "NA-TP|tap_hoa_nho", "NA-NT|cua_hang_sua"]


def outlet_code(npp_idx: int, i: int) -> str:
    return f"DB-{npp_idx:02d}-{i:03d}"


def seed(today: date | None = None, rng_seed: int = 7) -> None:
    today = today or clock.today()
    rng = random.Random(rng_seed)
    nrng = np.random.default_rng(rng_seed)
    with db.tx() as s:
        for ma, ten, tk, *_ in NPPS:
            s.add(NPP(ma_npp=ma, ten=ten, vung="Bac Trung Bo", so_tai_khoan=tk))
        for ma, ten, nhiet, han, qc, bien, L, *_ in SAN_PHAM:
            s.add(SanPham(ma_sp=ma, ten=ten, nhom_nhiet=nhiet, so_ngay_han=han, quy_cach_thung=qc, bien_ln=bien,
                          so_ngay_phu=L))
        s.flush()
        users = [("ADMIN", "Quản trị", R.ADMIN, None, None, "tok-admin", None),
                 ("PKD01", "Phòng KD", R.PKD, None, None, "tok-pkd", None),
                 ("GDKD01", "Giám đốc KD", R.GDKD, None, None, "tok-gdkd", None),
                 ("QA01", "QA công ty", R.QA, None, None, "tok-qa", None),
                 ("BDH01", "Ban điều hành", R.BDH, None, None, "tok-bdh", None)]
        for idx, (ma_npp, *_rest) in enumerate(NPPS, 1):
            n = f"{idx:02d}"
            users += [(f"NPP-{n}", f"Chủ {ma_npp}", R.NPP, ma_npp, None, f"tok-npp-{n}", None),
                      (f"TK-{n}", "Thủ kho", R.THU_KHO, ma_npp, None, f"tok-tk-{n}", None),
                      (f"GH-{n}", "NV giao hàng", R.NVGH, ma_npp, None, f"tok-gh-{n}", None),
                      (f"KT-{n}", "Kế toán NPP", R.KE_TOAN, ma_npp, None, f"tok-kt-{n}", None),
                      (f"KTT-{n}", "Kế toán trưởng", R.KE_TOAN_TRUONG, ma_npp, None, f"tok-ktt-{n}", None),
                      (f"TQ-{n}", "Thủ quỹ", R.THU_QUY, ma_npp, None, f"tok-tq-{n}", None),
                      (f"BH-{n}", "NV bán hàng", R.NVBH, ma_npp, None, f"tok-bh-{n}", None),
                      (f"GS-{n}", "Giám sát", R.GIAM_SAT, ma_npp, None, f"tok-gs-{n}", None)]
            for i in range(1, 4):
                code = outlet_code(idx, i)
                users.append((f"U-{code}", f"Chủ {code}", R.DIEM_BAN, ma_npp, code, f"tok-{code.lower()}",
                              f"zalo-{idx:02d}-{i:03d}"))
        for ma, ten, vt, npp, dbn, tok, zalo in users:
            s.add(NguoiDung(ma_nguoi_dung=ma, ten=ten, vai_tro=vt, ma_npp=npp, ma_diem_ban=dbn, token=tok,
                            zalo_id=zalo))
        s.flush()

        # ---- PH2: kho, lô, tồn -------------------------------------------------------------
        products = {p[0]: p for p in SAN_PHAM}
        for ma_npp, _, _, kho, lat, lng, _ in NPPS:
            s.add(Kho(ma_kho=kho, ma_npp=ma_npp, ten=f"Kho {ma_npp}", lat=lat, lng=lng))
        s.flush()

        def add_lot(ma_lo, sp, kho, hsd_offset, qty):
            han = products[sp][3]
            hsd = today + timedelta(days=hsd_offset)
            if s.get(LoHang, ma_lo) is None:
                s.add(LoHang(ma_lo=ma_lo, ma_sp=sp, nsx=hsd - timedelta(days=han), hsd=hsd))
                s.flush()
            s.add(TonKhoLo(ma_lo=ma_lo, ma_kho=kho, khu="ban", so_luong=qty))
            s.add(NhapKho(ma_lo=ma_lo, ma_kho=kho, so_luong=qty, ngay=today - timedelta(days=max(1, han - hsd_offset)),
                          nguon="nha_may"))

        for ma_npp, _, _, kho, *_ in NPPS:
            for sp, _, _, han, *_ in SAN_PHAM:
                s.add(TonKhoSP(ma_kho=kho, ma_sp=sp, ma_npp=ma_npp, da_giu=0))
                if sp == "SP01":
                    add_lot(f"L{sp}{kho}A", sp, kho, 2, 5)            # lô đỏ: không bán
                    if kho == "K01":
                        add_lot(f"L{sp}{kho}B", sp, kho, 5, 120)      # lô vàng dư nhiều -> NC2
                        add_lot(f"L{sp}{kho}C", sp, kho, han - 1, 60)
                    else:
                        add_lot(f"L{sp}{kho}C", sp, kho, han - 1, 10)  # kho thiếu -> nhận điều chuyển
                elif sp == "SP03":
                    add_lot("LSP03X", sp, kho, 120, 40)                # một lô nhà máy giao cho cả hai NPP
                    add_lot(f"L{sp}{kho}C", sp, kho, han - 5, 80)
                else:
                    add_lot(f"L{sp}{kho}B", sp, kho, max(4, int(han * 0.5)), 30)
                    add_lot(f"L{sp}{kho}C", sp, kho, han - 1, 60)

        # ---- PH4: điểm bán, tuyến ------------------------------------------------------------
        outlets = []
        for idx, (ma_npp, _, _, kho, lat, lng, vungs) in enumerate(NPPS, 1):
            for w in range(6):
                s.add(Tuyen(ma_tuyen=f"T-{idx:02d}-{w}", ma_npp=ma_npp, ma_nvbh=f"BH-{idx:02d}", thu_trong_tuan=w))
            s.flush()
            for i in range(1, SO_DIEM_BAN + 1):
                code = outlet_code(idx, i)
                nhom = NHOM[0] if i % 10 < 5 else NHOM[1] if i % 10 < 8 else NHOM[2]
                moi = i > SO_DIEM_BAN - SO_DIEM_BAN_MOI
                d = DiemBan(ma_diem_ban=code, ma_npp=ma_npp, ma_kho=kho, ten=f"Tạp hóa {code}",
                            sdt=f"09{idx}{i:07d}", lat=lat + rng.uniform(-0.05, 0.05), lng=lng + rng.uniform(-0.05, 0.05),
                            vung_gia="BTB", vung=vungs[0] if i <= SO_DIEM_BAN // 2 else vungs[1], nhom=nhom[0],
                            trang_thai="hoat_dong",
                            ngay_kich_hoat=today - timedelta(days=10 if moi else 400))
                s.add(d)
                s.flush()
                thu = (i - 1 + today.weekday()) % 6
                s.add(TuyenDiemBan(ma_tuyen=f"T-{idx:02d}-{thu}", ma_diem_ban=code, thu_tu=i))
                s.add(SoDiem(ma_diem_ban=code, diem=0))
                if moi:
                    s.add(HanMuc(ma_diem_ban=code, ma_npp=ma_npp, mua_chiu=False))
                else:
                    limit = 2_000_000 if i == 3 else rng.choice([15, 20, 30, 40]) * 1_000_000
                    s.add(HanMuc(ma_diem_ban=code, ma_npp=ma_npp, mua_chiu=True, han_muc=limit,
                                 ky_han_ngay=rng.choice([7, 14]), nguoi_duyet=f"KTT-{idx:02d}"))
                outlets.append((d, nhom, moi, thu))
        s.flush()
        # Điểm bán DB-01-002 có một khoản nợ quá hạn
        s.add(KhoanPhaiThu(so_hoa_don="HD-SEED00002", ma_don="SEED-DH-0002", ma_diem_ban="DB-01-002", ma_npp="NPP01",
                           so_tien=2_000_000, ngay=today - timedelta(days=20), han_tra=today - timedelta(days=6),
                           hinh_thuc_tt="cong_no"))

        # ---- PH1: bảng giá, KM ---------------------------------------------------------------
        s.add(BangGia(ma_bang_gia="BG-DB-V1", ten="Giá điểm bán", doi_tuong="diem_ban", vung_gia=None, phien_ban=1,
                      hieu_luc_tu=today - timedelta(days=365), trang_thai="da_duyet", nguoi_lap="PKD01",
                      nguoi_duyet="GDKD01"))
        s.add(BangGia(ma_bang_gia="BG-NPP-V1", ten="Giá NPP", doi_tuong="npp", vung_gia=None, phien_ban=1,
                      hieu_luc_tu=today - timedelta(days=365), trang_thai="da_duyet", nguoi_lap="PKD01",
                      nguoi_duyet="GDKD01"))
        s.flush()
        for sp, *_x, gia, _f in SAN_PHAM:
            s.add(DongGia(ma_bang_gia="BG-DB-V1", ma_sp=sp, don_gia=gia))
            s.add(DongGia(ma_bang_gia="BG-NPP-V1", ma_sp=sp, don_gia=int(gia * 0.85)))
        s.add(ChuongTrinhKM(ma_km="KM-SP02-5PCT", ten="Sữa chua: mua từ 5 thùng giảm 5%", ma_sp="SP02", sl_toi_thieu=5,
                            muc_giam=0.05, tu_ngay=today - timedelta(days=3), den_ngay=today + timedelta(days=10),
                            ngan_sach=3_000_000, da_dung=0, trang_thai="da_duyet", nguoi_lap="PKD01",
                            nguoi_duyet="GDKD01"))

        # ---- Lịch sử bán mô phỏng + KM quá khứ có đối chứng ------------------------------------
        units = sorted({f"{d.vung}|{d.nhom}" for d, *_ in outlets})
        hist_promos = {}
        for ma_km, ago, m in KM_QUA_KHU:
            tu = today - timedelta(days=ago)
            treated = [u for u in units if u not in DOI_CHUNG]
            hist_promos[ma_km] = (tu, tu + timedelta(days=13), m, set(treated))
        cost = {k: 0 for k in hist_promos}
        rows = []
        for d, (nhom, demand, uplift10), moi, thu in outlets:
            if moi:
                continue
            unit = f"{d.vung}|{d.nhom}"
            for sp, _, _, _, _, _, _, gia, fsp in SAN_PHAM:
                lam = demand * fsp
                for back in range(SO_NGAY_LICH_SU, 0, -1):
                    day = today - timedelta(days=back)
                    season = 1 + 0.1 * math.sin(2 * math.pi * back / 30)
                    rate = lam * season * (0.8 if day.weekday() == thu else 0.04)
                    m, km_code = 0.0, None
                    if sp == "SP03":
                        for k, (tu, den, lv, treated) in hist_promos.items():
                            if unit in treated and tu <= day <= den:
                                rate *= 1 + uplift10 * lv / 0.10
                                m, km_code = lv, k
                            elif unit in treated and den < day <= den + timedelta(days=14):
                                rate *= max(0.2, 1 - TY_LE_MUA_DON * uplift10 * lv / 0.10)
                    q = int(nrng.poisson(rate))
                    if q <= 0:
                        continue
                    if km_code:
                        cost[km_code] += int(q * gia * m)
                    rows.append({"ngay": day, "ma_npp": d.ma_npp, "ma_kho": d.ma_kho, "ma_diem_ban": d.ma_diem_ban,
                                 "vung": d.vung, "nhom": d.nhom, "ma_sp": sp, "so_luong": q,
                                 "doanh_thu": int(q * gia * (1 - m)), "muc_giam": m, "ma_km": km_code,
                                 "tu_dat": rng.random() < 0.2, "mo_phong": True})
        s.execute(insert(DwBanHangNgay), rows)
        for k, (tu, den, lv, treated) in hist_promos.items():
            s.add(ChuongTrinhKM(ma_km=k, ten=f"KM quá khứ SP03 giảm {lv:.0%}", ma_sp="SP03", sl_toi_thieu=1, muc_giam=lv,
                                muc_giam_theo_don_vi={u: lv for u in treated}, don_vi_doi_chung=DOI_CHUNG,
                                tu_ngay=tu, den_ngay=den, ngan_sach=max(cost[k], 1), da_dung=cost[k],
                                trang_thai="ket_thuc", nguon="pkd", nguoi_lap="PKD01", nguoi_duyet="GDKD01",
                                ghi_chu="Lịch sử mô phỏng"))

        # ---- Lịch sử tín dụng mô phỏng (12 tháng) -------------------------------------------
        credit_rows = []
        month0 = today.replace(day=1)
        for d, (nhom, demand, _), moi, _ in outlets:
            risk = 0.6 if d.ma_diem_ban == "DB-01-002" else float(nrng.beta(1.2, 12))
            n_months = 2 if moi else 12
            for k in range(n_months, 0, -1):
                thang = (month0 - timedelta(days=30 * k)).replace(day=1)
                qh6 = int(nrng.poisson(6 * risk))
                f = {"doanh_so_chiu": int(demand * 4 * 300_000 * nrng.uniform(0.7, 1.3)),
                     "do_deu_dat_hang": float(np.clip(1 - risk + nrng.normal(0, 0.1), 0, 1)),
                     "so_thang_hoat_dong": 24 - k if not moi else n_months - k + 1,
                     "so_ngay_tra_tb": float(max(0, 5 + 30 * risk + nrng.normal(0, 3))),
                     "so_lan_qua_han_6t": qh6,
                     "ty_le_qr": float(np.clip(0.7 - 0.5 * risk + nrng.normal(0, 0.1), 0, 1)),
                     "muc_su_dung_han_muc": float(np.clip(0.4 + 0.6 * risk + nrng.normal(0, 0.1), 0, 1.5)),
                     "ty_le_tra_hang": float(np.clip(0.02 + 0.1 * risk + nrng.normal(0, 0.01), 0, 1)),
                     "so_lan_dong_cua": int(nrng.poisson(2 * risk))}
                p = 1 / (1 + math.exp(-(-4.5 + 9 * risk + 0.35 * qh6)))
                credit_rows.append({"ma_diem_ban": d.ma_diem_ban, "thang": thang, **f,
                                    "qua_han_30": bool(nrng.random() < p), "mo_phong": True})
        s.execute(insert(DwTinDungThang), credit_rows)

        for ma, ten, ph, chieu, nguong, nhan in [
            ("ty_le_tu_dong_duyet", "Tỷ lệ đơn duyệt tự động", "PH1", "min", 0.8, "PKD"),
            ("tg_duyet_tb_phut", "Thời gian duyệt đơn TB (phút)", "PH1", "max", 120, "PKD"),
            ("ty_le_don_tu_dat", "Tỷ lệ đơn điểm bán tự đặt (KPI6)", "PH1", "min", 0.3, "PKD"),
            ("so_km_vuot_ngan_sach", "Số KM chi vượt ngân sách", "PH1", "max", 0, "GDKD"),
            ("ty_le_tuan_thu_fefo", "Tuân thủ FEFO", "PH2", "min", 0.98, "QA"),
            ("ty_le_ton_can_han", "Tồn cận hạn", "PH2", "max", 0.05, "PKD"),
            ("tg_truy_xuat_lo_ms_max", "Thời gian truy xuất lô (ms)", "PH2", "max", 300_000, "QA"),
            ("ty_le_no_qua_han", "Tỷ lệ nợ quá hạn", "PH3", "max", 0.05, "KTT"),
            ("ty_le_gach_no_tu_dong", "Tỷ lệ gạch nợ tự động", "PH3", "min", 0.95, "KTT"),
            ("ty_le_ghe_dung_tuyen", "Tỷ lệ ghé đúng tuyến", "PH4", "min", 0.95, "GS"),
            ("ty_le_check_in_nghi_van", "Check-in nghi vấn", "PH4", "max", 0.02, "GS")]:
            s.add(NguongKpi(ma_kpi=ma, ten=ten, phan_he=ph, chieu=chieu, nguong=nguong, nguoi_nhan=nhan))

    # Phiếu xuất nhà máy mẫu trong thư mục trao đổi ERP (hàng đang về cho K02)
    integration.write_exchange_file(integration.KENH_ERP_VAO, "PXNM-0001", 1, [
        {"ma_phieu_erp": "PXNM-0001", "ma_kho": "K02", "ma_sp": "SP04", "ma_lo": "LSP04NM1",
         "nsx": str(today - timedelta(days=1)), "hsd": str(today + timedelta(days=29)), "so_luong": 40,
         "ngay_ve": str(today + timedelta(days=1))}])


def reset_and_seed(today: date | None = None) -> None:
    import shutil
    from app import config
    db.drop_all()
    db.create_all()
    shutil.rmtree(config.DATA_DIR / "exchange", ignore_errors=True)
    seed(today)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    db.init_engine()
    # --if-empty: dùng khi container khởi động, không xóa dữ liệu đã có
    if "--if-empty" in sys.argv:
        from sqlalchemy import inspect, select
        if inspect(db.engine).has_table(NPP.__tablename__):
            with db.tx() as s:
                if s.scalar(select(NPP.ma_npp).limit(1)) is not None:
                    print("CSDL đã có dữ liệu, bỏ qua nạp mẫu.")
                    sys.exit(0)
    reset_and_seed()
    print("Đã nạp dữ liệu mẫu (lịch sử mô phỏng).")
