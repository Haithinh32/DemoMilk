# Cao Sơn Milk – Bản mẫu TMĐT B2B và Quản lý phân phối

Bản mẫu cho mục tiêu "Triển khai và Tích hợp Mô-đun": 12 chức năng cốt lõi của 4 phân hệ chạy trên **một nền tảng
chung (PH0)**, với cơ chế giao tiếp rõ ràng giữa các mô-đun và với agent Zalo. Thiết kế theo báo cáo
`Khung_bao_cao_cuoi_ky_Nhom3_Cao_Son_Milk_4.docx` (chương 2–4).

> Mọi lịch sử bán hàng và tín dụng dùng để huấn luyện các chức năng nâng cao là **dữ liệu mô phỏng**
> (`mo_phong = True` trong kho dữ liệu). Báo cáo phải ghi rõ điều này khi trích số liệu.

## Chạy nhanh

Hướng dẫn chi tiết từng bước (môi trường ảo, Swagger, giao diện web, Docker, agent, lỗi thường gặp): [HUONG_DAN_CAI_DAT.md](HUONG_DAN_CAI_DAT.md).

```bash
pip install -r requirements.txt
python -m app.seed                      # tạo data/csm.db và nạp dữ liệu mẫu (xóa dữ liệu cũ)
uvicorn app.main:app --reload           # http://127.0.0.1:8000/docs
python -m scripts.demo                  # kịch bản demo xuyên 4 phân hệ, in từng bước
python -m pytest                        # 25 kiểm thử (1 kiểm thử PostgreSQL bị bỏ qua nếu không có CSM_PG_URL)
cd web && npm install && npm run dev   # giao diện web ở http://localhost:5173 (cần server API ở cổng 8000)
```

Toàn bộ bằng Docker, trên PostgreSQL (khóa dòng thật, đúng thiết kế):

```bash
docker compose up -d --build            # PostgreSQL + API (:8000/docs) + giao diện web (http://localhost:5173)
docker compose run --rm tests           # 26 kiểm thử, gồm kiểm thử tranh chấp trên PostgreSQL
docker compose run --rm demo            # kịch bản demo trên PostgreSQL
```

Đăng nhập bằng header `Authorization: Bearer <token>` (thay cho OTP + JWT ở bản thật). Token mẫu:

| Vai trò | Token | Vai trò | Token |
|---|---|---|---|
| Điểm bán DB-01-001 (hạn mức bình thường) | `tok-db-01-001` | Thủ kho NPP01 | `tok-tk-01` |
| Điểm bán DB-01-002 (có nợ quá hạn) | `tok-db-01-002` | NV giao hàng NPP01 | `tok-gh-01` |
| Điểm bán DB-01-003 (hạn mức 2 triệu) | `tok-db-01-003` | Kế toán / KT trưởng / thủ quỹ | `tok-kt-01`, `tok-ktt-01`, `tok-tq-01` |
| Điểm bán NPP02 | `tok-db-02-001` | NV bán hàng NPP01 | `tok-bh-01` |
| Chủ NPP | `tok-npp-01`, `tok-npp-02` | Phòng KD / Giám đốc KD / QA / BĐH | `tok-pkd`, `tok-gdkd`, `tok-qa`, `tok-bdh` |
| Quản trị (chạy tác vụ, tua đồng hồ) | `tok-admin` | Zalo của DB-01-001 | `zalo_id = zalo-01-001` |

## Kiến trúc

Modular monolith (mục 2.4): một FastAPI, một CSDL, mỗi phân hệ là một package có ranh giới rõ.

```
app/
  ph0_platform/   Identity, Notification, Integration (ERP tệp, VietQR, HĐĐT), Scheduler, AI Engine,
                  bus sự kiện (events.py + event_catalog.py), Agent Gateway Zalo (agent.py)
  ph1_order/      CN2, CN3 (service.py) · NC1 (promo_nc1.py) · CN1/CN5 tối thiểu (promo.py)
  ph2_inventory/  CN2 (contracts.py giữ tồn, service.py xuất FEFO) · CN5 (recall.py) · NC2 (forecast_nc2.py)
  ph3_credit/     CN1 (contracts.py) · CN3 (ledger.py) · NC1 (scoring_nc1.py)
  ph4_sales/      CN1 (field.py) · CN5 (dashboard.py) · NC1 (suggest_nc1.py)
  jobs.py         đăng ký mọi tác vụ định kỳ    seed.py  dữ liệu mẫu
web/             giao diện React (Vite): src/pages/ một file cho mỗi nhóm màn hình, gọi API qua /api
```

Mỗi phân hệ **chỉ ghi bảng của mình** (Bảng 4.1) và chỉ gọi phân hệ khác qua `contracts.py` của phân hệ đó
hoặc qua sự kiện. Đây là chỗ mỗi thành viên phát triển tiếp mà không đụng code của người khác.

### Ba cơ chế giao tiếp giữa các mô-đun

| Cơ chế | Dùng khi | Ví dụ trong code |
|---|---|---|
| **Gọi hợp đồng trong cùng giao dịch** | Cần nguyên tử: cùng thành công hoặc cùng hoàn tác | `ph1.service.place_order` gọi `ph2.contracts.reserve_cart` rồi trừ ngân sách KM bằng `UPDATE … WHERE da_dung + chi_phi <= ngan_sach`, tất cả trong một giao dịch |
| **Gọi hợp đồng, giao dịch riêng** | Cần kết quả ngay nhưng không được làm hỏng bước trước | `review_order` gọi `ph3.contracts.check_credit` sau khi đơn đã giữ tồn; PH3 lỗi thì đơn ở `CHO_KIEM_TRA_TD` và tác vụ `ph1.thu_lai_tin_dung` thử lại |
| **Sự kiện qua outbox/inbox** | Không cần đồng bộ tức thời; một bên phát, nhiều bên nhận | `ph2.don_hang.da_giao` → PH3 ghi phải thu, PH4 cộng điểm, PH1 cập nhật trạng thái |

Bus sự kiện (`app/ph0_platform/events.py`):
- `publish()` ghi vào bảng `su_kien` **trong giao dịch của bên phát**, nên thay đổi nghiệp vụ và sự kiện cùng
  commit hoặc cùng rollback.
- Mỗi bên nhận xử lý trong giao dịch riêng và ghi `(ben_nhan, ma_su_kien)` vào `su_kien_da_xu_ly`, nên
  gửi lại không bị xử lý hai lần.
- Bên nhận lỗi thì sự kiện được thử lại, quá 5 lần chuyển `loi` (xem `GET /ph0/events?trang_thai=loi`).
- Khi tách service (NFR9): thay `dispatch_pending` bằng relay đẩy bảng `su_kien` lên message broker;
  danh mục sự kiện trong `event_catalog.py` giữ nguyên.

Danh mục sự kiện (đối chiếu Bảng 2.4):

| Sự kiện | Phát | Nhận |
|---|---|---|
| `ph1.don_hang.da_duyet` | PH1 CN3 | PH2 lập phiếu xuất FEFO |
| `ph1.don_hang.da_tao` / `da_huy` | PH1 | PH4 ghi nhận gợi ý được đặt |
| `ph1.don_bo_sung.da_chot` | PH1 CN5 | Integration ghi tệp cho ERP |
| `ph2.don_hang.thieu_hang` | PH2 CN2 | PH1 cắt dòng, tính lại KM, PH3 tính lại hạn mức giữ |
| `ph2.don_hang.cho_giao` / `da_giao` | PH2 | PH1; PH3 (phải thu, HĐĐT); PH4 (cộng điểm) |
| `ph2.lo.da_khoa` | PH2 CN5 | PH1, PH4 thông báo |
| `ph2.thu_hoi.da_nhan` | PH2 CN5 | PH3 cấn trừ theo số kho thực nhận |
| `ph2.nc2.de_xuat_bo_sung` / `de_xuat_km_xa_lo` | PH2 NC2 | PH1 (đơn bổ sung, KM xả lô chờ duyệt) |
| `ph3.ngoai_le.da_quyet` | PH3 CN1 | PH1 duyệt tiếp hoặc hủy đơn |
| `ph3.can_tru.da_xac_nhan` | PH3 | PH4 trừ điểm |
| `ph3.thu_no.nhiem_vu` | PH3 | PH4 gắn vào tuyến NVBH |
| `ph3.so.da_khoa` | PH3 CN3 | Integration ghi bút toán cho phần mềm kế toán NPP |
| `ph4.thu_no.ket_qua` | PH4 CN1 | PH3 gạch nợ tiền NVBH thu |

### Agent Zalo (tác nhân thứ hai giao tiếp với hệ thống)

`POST /ph0/agent/zalo {zalo_id, tin_nhan}`: một agent Claude (`claude-opus-5-5`) gọi công cụ theo vòng lặp
thủ công. Công cụ: xem tồn, xem gợi ý, tạo đơn nháp, xem trạng thái đơn, xem công nợ, tạo QR.
- Điểm bán xác định từ `zalo_id` ở máy chủ; mô hình không truyền mã điểm bán nên không đọc được điểm bán khác.
- Agent chỉ tạo **đơn nháp** (30 phút). Đơn thật sinh khi điểm bán bấm `POST /ph1/agent-drafts/{ma}/confirm`
  và đi qua đúng luồng giữ tồn → giá → tín dụng như đơn app.
- Mọi lần gọi công cụ ghi vào `nhat_ky_agent`. Kiểm thử công cụ không cần LLM: `POST /ph0/agent/tools/{ten}?zalo_id=`.
- Cần `pip install anthropic` và `ANTHROPIC_API_KEY`; chưa có thì endpoint trả 503 rõ lý do.

## 12 chức năng và nơi kiểm chứng

| Chức năng | Code | Kiểm thử chính |
|---|---|---|
| PH1 CN2 Đặt hàng trực tuyến | `ph1_order/service.py: place_order, catalog, cart_from_suggestion` | `test_last_cases_and_idempotency`, `test_cutoff_moves_delivery_date` |
| PH1 CN3 Kiểm tra và duyệt đơn | `review_order, credit_choice, npp_decide, expire_orders` | `test_over_limit_*`, `test_policy_exception_goes_to_npp` |
| PH1 NC1 Đề xuất và đánh giá KM | `ph1_order/promo_nc1.py` (T-learner + cái túi nhiều lựa chọn + DiD) | `test_ph1_nc1_promo_proposal_beats_uniform_and_did` |
| PH2 CN2 Giữ tồn và xuất FEFO | `ph2_inventory/contracts.py: reserve_cart`, `service.py` | `test_order_to_cash`, `test_lot_swap_rules` |
| PH2 CN5 Khóa lô, truy xuất, thu hồi | `ph2_inventory/recall.py` | `test_lock_trace_recall_offset` |
| PH2 NC2 Dự báo và hoạch định tồn | `ph2_inventory/forecast_nc2.py` (dự báo, tồn mục tiêu, bài toán vận tải lô vàng) | `test_ph2_nc2_replenishment_and_yellow_lots` |
| PH3 CN1 Hạn mức, kiểm soát tín dụng | `ph3_credit/contracts.py: check_credit`, `ledger.decide_exception` | `test_over_limit_exception_approved`, `test_overdue_outlet_must_pay_on_delivery` |
| PH3 CN3 Đối soát và ghi sổ | `ph3_credit/ledger.py` | `test_order_to_cash`, `test_unmatched_payment_blocks_day_close`, `test_cash_receipt_and_handover` |
| PH3 NC1 Chấm điểm tín dụng | `ph3_credit/scoring_nc1.py` | `test_ph3_nc1_credit_scoring` |
| PH4 CN1 Đi tuyến, chăm sóc điểm bán | `ph4_sales/field.py` | `test_route_checkin_and_order_on_behalf`, `test_collection_task_flows_ph3_to_ph4_and_back` |
| PH4 CN5 Báo cáo, dashboard | `ph4_sales/dashboard.py` (KPI lấy từ `kpi_snapshot` của cả 4 phân hệ) | `test_dashboard_kpis_and_scope` |
| PH4 NC1 Gợi ý đơn hàng | `ph4_sales/suggest_nc1.py` | `test_ph4_nc1_suggestions_only_available_and_feed_ph1` |

Tác vụ định kỳ: `GET /ph0/scheduler/jobs`; chạy tay `POST /ph0/scheduler/run/{ten}` (token admin).
Tua thời gian để thấy các hạn BR-06: `POST /ph0/clock {"cong_phut": 31}`.

## Phần làm tối thiểu, đơn giản hóa và chưa làm

Làm tối thiểu vì các chức năng cốt lõi phụ thuộc vào chúng: xác nhận giao hàng (PH2 CN4), ghi phải thu và thu
tiền mặt (PH3 CN2), cấn trừ thu hồi (PH3 CN4), nhắc nợ (PH3 CN5), lập/duyệt KM (PH1 CN1), đơn bổ sung NPP
(PH1 CN5), nhận phiếu xuất ERP qua tệp.

Đơn giản hóa so với thiết kế:
- Token tĩnh thay cho OTP + JWT. Cô lập NPP làm ở tầng ứng dụng (lấy `ma_npp` từ token, trả 404 khi khác NPP);
  **chưa bật Row-Level Security của PostgreSQL** (Bảng 4.4, tầng 2).
- LightGBM / OR-Tools chưa cài nên dùng HistGradientBoosting (scikit-learn) và SciPy (`milp`, `linprog`);
  `ai_engine.BACKEND` cho biết đang dùng gì. Có LightGBM thì tự dùng.
- Lý do chấm điểm tín dụng lấy từ hệ số logistic, chưa dùng SHAP.
- Bất thường check-in chấm theo luật (khoảng cách, ảnh trùng, lệch giờ, đồng bộ trễ), chưa có mô hình PH4 NC2.
- Mỗi dòng đơn áp tối đa một KM (không cộng dồn).
- Hội thoại agent lưu trong bộ nhớ; tạo bảng bằng `create_all`, chưa có Alembic.
- Giao diện web là bản trình diễn: chưa có app di động ngoại tuyến cho NVBH (check-in dùng tọa độ giả lập),
  chưa có SSO/OTP; nút *Mô phỏng: chuyển khoản* gọi `POST /ph3/bank/simulate` thay cho ngân hàng thật.

## Điều chỉnh so với báo cáo (đề nghị sửa báo cáo cho khớp)

1. **Tồn khả dụng**: mục 3.3.11 trừ thêm "hàng đang chuyển đến", nhưng hàng đang về chưa nằm trong tồn thực
   nên trừ nữa là trừ hai lần. Code theo BR-04 và mục 4.7.2: hàng đang về không cộng, không trừ.
2. **Mã quy tắc trùng**: PH1 và PH3 cùng dùng BR-01…BR-09. Comment trong code ghi kèm phân hệ (ví dụ
   "BR-02 PH3"); nên đổi trong báo cáo thành PH1.BR-xx / PH3.BR-xx.
3. **Nợ quá hạn**: CN3 PH1 viết "không đạt thì chọn trả ngay hoặc xin ngoại lệ", nhưng BR-02 PH3 là chặn cứng.
   Code: có nợ quá hạn hoặc chưa được mua chịu thì đơn tự chuyển "trả khi nhận hàng" (vẫn bán được); chỉ vượt
   hạn mức mới có lựa chọn 30 phút / xin ngoại lệ.
4. **Ngưỡng lô vàng**: báo cáo chưa chốt; code dùng "còn ≤ max(4 ngày, 50% hạn dùng)", lô đỏ < 3 ngày (BR-04).
