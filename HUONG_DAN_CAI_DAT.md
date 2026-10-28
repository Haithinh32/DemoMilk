# Hướng dẫn cài đặt và chạy – Cao Sơn Milk (bản mẫu)

Hướng dẫn cho thành viên nhóm chạy bản mẫu trên máy cá nhân (Windows, có ghi chú cho macOS/Linux).
Kiến trúc, danh sách sự kiện và bảng chức năng ↔ kiểm thử xem ở [README.md](README.md).

## 1. Yêu cầu

| Thành phần | Phiên bản | Bắt buộc? |
|---|---|---|
| Python | 3.11 trở lên (đã thử với 3.12) | Có |
| Git | bất kỳ | Có |
| Node.js | 20 trở lên | Chỉ khi chạy giao diện web trên máy (mục 7) |
| Docker Desktop | bất kỳ | Chỉ khi chạy bằng Docker (mục 8) – khi đó không cần Python, Node |
| Khóa API Anthropic | – | Chỉ khi thử agent Zalo |

Kiểm tra: `python --version`, `node --version`. Nếu máy có nhiều bản Python, trên Windows dùng `py -3.12` thay cho `python` ở bước 2.

## 2. Cài đặt

Mở PowerShell tại thư mục `DemoMilk`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

- Nếu PowerShell báo *running scripts is disabled*, chạy một lần
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` rồi kích hoạt lại.
- Dùng `cmd`: `.venv\Scripts\activate.bat`. macOS/Linux: `source .venv/bin/activate`.
- Mỗi lần mở terminal mới đều phải kích hoạt lại `.venv`.

## 3. Nạp dữ liệu mẫu

```powershell
python -m app.seed
```

Lệnh tạo `data/csm.db` (SQLite) và nạp: 2 NPP, 2 kho, 6 sản phẩm, 80 điểm bán, các lô (có lô đỏ, lô vàng),
200 ngày lịch sử bán hàng và 12 tháng lịch sử tín dụng **mô phỏng**.
Chạy lại lệnh này bất cứ lúc nào để **xóa sạch** và nạp lại từ đầu.

## 4. Chạy kiểm thử

```powershell
python -m pytest
```

Kết quả mong đợi: `25 passed, 1 skipped`. Kiểm thử bị bỏ qua là kiểm thử tranh chấp trên PostgreSQL (mục 8).
Chạy riêng một nhóm: `python -m pytest tests/test_order_to_cash.py -v`.

## 5. Chạy kịch bản demo

```powershell
python -m scripts.demo
```

Không cần bật server. Kịch bản dùng CSDL riêng `data/demo/demo.db` nên không ảnh hưởng dữ liệu ở bước 3,
và in từng bước của chu trình xuyên 4 phân hệ:

1. PH4 sinh đơn gợi ý → điểm bán đặt hàng → PH2 giữ tồn → PH3 kiểm tra tín dụng → PH1 duyệt.
2. PH2 xuất kho FEFO → giao hàng → sự kiện *Đã giao* → PH3 ghi phải thu, PH4 cộng điểm.
3. Thanh toán VietQR → PH3 gạch nợ (báo có trùng bị bỏ qua) → đối soát, khóa sổ.
4. QA khóa lô, truy xuất; các chức năng nâng cao NC2, NC1 của PH1/PH3; dashboard KPI.

## 6. Chạy server API

```powershell
uvicorn app.main:app --reload
```

Mở <http://127.0.0.1:8000/docs> (Swagger). Bấm **Authorize**, nhập một token ở bảng dưới (chỉ phần token,
không gõ chữ `Bearer`), rồi thử các endpoint.

| Vai trò | Token |
|---|---|
| Điểm bán DB-01-001 (bình thường) | `tok-db-01-001` |
| Điểm bán DB-01-002 (có nợ quá hạn) | `tok-db-01-002` |
| Điểm bán DB-01-003 (hạn mức 2 triệu) | `tok-db-01-003` |
| Điểm bán thuộc NPP02 | `tok-db-02-001` |
| Chủ NPP | `tok-npp-01`, `tok-npp-02` |
| Thủ kho / giao hàng / bán hàng NPP01 | `tok-tk-01`, `tok-gh-01`, `tok-bh-01` |
| Kế toán / KT trưởng / thủ quỹ | `tok-kt-01`, `tok-ktt-01`, `tok-tq-01` |
| Phòng KD / Giám đốc KD / QA / Ban điều hành | `tok-pkd`, `tok-gdkd`, `tok-qa`, `tok-bdh` |
| Quản trị | `tok-admin` |

Thử nhanh bằng dòng lệnh (PowerShell):

```powershell
$h = @{ Authorization = "Bearer tok-db-01-001" }
Invoke-RestMethod http://127.0.0.1:8000/ph0/me -Headers $h
Invoke-RestMethod http://127.0.0.1:8000/ph3/debt/DB-01-001 -Headers $h
```

Một số thao tác hữu ích (đều cần `tok-admin`):

| Mục đích | Endpoint |
|---|---|
| Xem danh sách tác vụ định kỳ | `GET /ph0/scheduler/jobs` |
| Chạy ngay một tác vụ, ví dụ sinh đơn gợi ý | `POST /ph0/scheduler/run/ph4.nc1_goi_y_don` |
| Xem đồng hồ hệ thống | `GET /ph0/clock` |
| Đặt giờ hoặc tua thời gian (để thấy các hạn BR-06) | `POST /ph0/clock` với `{"dat_gio": "2026-10-28T09:00:00"}` hoặc `{"cong_phut": 120}` |
| Xem sự kiện đã đi qua bus | `GET /ph0/events` |

Ghi chú:
- Server dùng giờ thật của máy. Đơn đặt sau 16h được tính sang ngày giao kế tiếp; muốn thử như trong giờ làm việc
  thì đặt giờ 09:00 bằng `POST /ph0/clock`. Đồng hồ trở về giờ thật khi khởi động lại server.
- Tác vụ định kỳ mặc định **tắt**; chạy tay bằng endpoint ở trên, hoặc bật tự chạy bằng
  `$env:CSM_SCHEDULER="on"` trước khi gọi `uvicorn`.

## 7. Giao diện web

Giao diện React (thư mục `web/`) gọi đúng các API ở mục 6, mỗi vai trò thấy các màn hình của mình.
Cần server API đang chạy ở cổng 8000 (mục 6). Mở terminal **thứ hai**:

```powershell
cd web
npm install          # lần đầu
npm run dev          # http://localhost:5173
```

Trang đầu là danh sách tài khoản demo; bấm một thẻ để đăng nhập, đổi vai trò bằng ô chọn ở góc trên bên phải.
Trình duyệt gọi `/api/...`, Vite chuyển tiếp sang `http://127.0.0.1:8000` (đổi bằng biến `CSM_API_URL` nếu server ở chỗ khác).

| Vai trò | Màn hình |
|---|---|
| Điểm bán | Đặt hàng (kèm đơn gợi ý), Đơn hàng, Công nợ & thanh toán VietQR, Zalo OA |
| NV bán hàng | Tuyến hôm nay (check-in, thu nợ, đặt hộ), Đơn hàng |
| Chủ NPP | Đơn hàng (duyệt ngoại lệ), Đơn bổ sung, Lô hàng, Dashboard |
| Thủ kho | Soạn & xuất kho (quét lô FEFO), Lô hàng, Nhận hàng thu hồi |
| NV giao hàng | Giao hàng (bằng chứng), Thu tiền mặt |
| Kế toán / KT trưởng / thủ quỹ | Báo có chờ xử lý, Ngoại lệ tín dụng, Đối soát & khóa sổ, Chấm điểm tín dụng, Nhận nộp quỹ |
| Phòng KD / GĐKD | Chương trình KM (lập / duyệt), Đề xuất & đánh giá KM, Đơn bổ sung, Điều chuyển lô vàng, Dashboard |
| QA | Lô hàng (khóa, mở khóa, truy xuất, thu hồi), Vụ thu hồi |
| Ban điều hành | Dashboard KPI |
| Quản trị | Hệ thống: đồng hồ, tác vụ định kỳ, bus sự kiện, thông báo, nhật ký |

Kịch bản trình diễn gợi ý (dữ liệu vừa nạp ở mục 3):

1. **Quản trị** → Hệ thống: bấm *Đặt* (09:00), chạy `ph4.nc1_goi_y_don`.
2. **Điểm bán DB-01-001** → Đặt hàng: *Dùng đơn gợi ý*, sửa số thùng, *Đặt hàng* → đơn được duyệt tự động.
3. **Thủ kho** → Soạn & xuất kho: chọn phiếu, *Quét* từng dòng, *Xác nhận xuất kho*.
4. **NV giao hàng** → Giao hàng: *Xác nhận đã giao* (xóa ô ảnh để thấy hệ thống chặn khi thiếu bằng chứng).
5. **Điểm bán DB-01-001** → Công nợ: chọn hóa đơn, *Mô phỏng: chuyển khoản* → gạch nợ tự động, điểm thưởng tăng.
6. **Kế toán trưởng** → Đối soát: *Khóa sổ ngày*.
7. Nhánh khác: DB-01-003 đặt 20 thùng SP01 (vượt hạn mức) → xin ngoại lệ → kế toán trưởng duyệt;
   QA khóa lô LSP01K01B → phiếu soạn mới tự đề xuất lô khác; phòng KD tính đề xuất KM cho SP03.
8. **Ban điều hành** → Dashboard; **Quản trị** → Hệ thống → Bus sự kiện để xem các sự kiện vừa đi qua.

Nút *Mô phỏng: chuyển khoản* đóng vai ngân hàng (endpoint `POST /ph3/bank/simulate`, chỉ dùng cho demo) vì
trình duyệt không giữ khóa ký webhook ngân hàng.

## 8. Chạy toàn bộ bằng Docker (PostgreSQL)

Không cần cài Python, chỉ cần Docker Desktop đang chạy. Mọi thứ chạy trên PostgreSQL, đúng thiết kế (khóa dòng thật).

```powershell
docker compose up -d --build      # PostgreSQL + server API + giao diện web, lần đầu tự nạp dữ liệu mẫu
docker compose run --rm tests     # 26 kiểm thử, gồm kiểm thử tranh chấp trên PostgreSQL
docker compose run --rm demo      # kịch bản demo xuyên 4 phân hệ
```

Giao diện web ở <http://localhost:5173> (như mục 7), API ở <http://localhost:8000/docs> (như mục 6). Các dịch vụ:

| Dịch vụ | Việc | CSDL |
|---|---|---|
| `db` | PostgreSQL 16, mở cổng 5432 (user/mật khẩu `csm`/`csm`) | – |
| `api` | Nạp dữ liệu mẫu nếu CSDL trống, rồi chạy server ở cổng 8000 | `csm` |
| `web` | nginx phục vụ giao diện đã build ở cổng 5173, chuyển `/api/` sang `api` | – |
| `tests` | Chạy `pytest` | `csm_test` |
| `demo` | Chạy `scripts.demo` | `csm_demo` |

`tests` và `demo` xóa sạch CSDL riêng của chúng mỗi lần chạy, nên không ảnh hưởng dữ liệu của `api`.

Lệnh thường dùng:

| Mục đích | Lệnh |
|---|---|
| Xem log server | `docker compose logs -f api` |
| Nạp lại dữ liệu mẫu cho `api` (xóa dữ liệu cũ) | `docker compose exec api python -m app.seed` |
| Sau khi sửa code | `docker compose up -d --build` |
| Sau khi sửa model (thêm/đổi cột) | `docker compose down -v` rồi `docker compose up -d --build` |
| Bật tác vụ định kỳ tự chạy | `$env:CSM_SCHEDULER="on"; docker compose up -d` |
| Dùng agent Zalo | `$env:ANTHROPIC_API_KEY="sk-ant-..."; docker compose up -d` |
| Mở psql | `docker compose exec db psql -U csm csm` |
| Dừng (giữ dữ liệu) / dừng và xóa dữ liệu | `docker compose down` / `docker compose down -v` |

Ghi chú:
- Bản mẫu chưa có Alembic, nên khi đổi model phải xóa volume (`down -v`) để tạo lại bảng.
- Container chạy theo giờ Việt Nam (`TZ=Asia/Ho_Chi_Minh`).
- Nếu cổng 5432 hoặc 8000 đã bị chương trình khác dùng, sửa vế trái của `ports` trong
  `docker-compose.yml`, ví dụ `"8080:8000"`.

Chạy server trên máy nhưng dùng PostgreSQL trong Docker:

```powershell
docker compose up -d db
python -m pip install "psycopg[binary]"
$env:DATABASE_URL = "postgresql+psycopg://csm:csm@localhost:5432/csm"
python -m app.seed
uvicorn app.main:app
```

Quay lại SQLite: `Remove-Item Env:DATABASE_URL` (hoặc mở terminal mới).

## 9. (Tùy chọn) Agent Zalo

```powershell
python -m pip install anthropic
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uvicorn app.main:app
```

Gửi tin nhắn giả lập từ Zalo của điểm bán DB-01-001:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ph0/agent/zalo -Method Post -ContentType "application/json" `
  -Body '{"zalo_id": "zalo-01-001", "tin_nhan": "Cho tôi xem công nợ"}'
```

Chưa có khóa API thì endpoint trả lỗi 503 kèm lý do. Các công cụ của agent vẫn thử được mà không cần khóa:
`POST /ph0/agent/tools/xem_cong_no?zalo_id=zalo-01-001` với body `{}`.

## 10. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/csm.db` | Chuỗi kết nối CSDL |
| `CSM_DATA_DIR` | `data/` | Thư mục chứa CSDL SQLite và tệp trao đổi ERP |
| `CSM_SCHEDULER` | `off` | `on` để tác vụ định kỳ tự chạy trong server |
| `CSM_BANK_SECRET` | `demo-bank-secret` | Khóa HMAC kiểm chữ ký webhook ngân hàng |
| `CSM_AGENT_MODEL` | `claude-opus-5-5` | Mô hình dùng cho agent Zalo |
| `ANTHROPIC_API_KEY` | – | Khóa API cho agent Zalo |
| `CSM_PG_URL` | – | Có giá trị thì chạy kiểm thử PostgreSQL |
| `CSM_DEMO_DB_URL` | SQLite `data/demo/demo.db` | CSDL cho `scripts.demo` |

## 11. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | Chạy lệnh từ thư mục `DemoMilk` và dùng dạng `python -m ...` |
| `ModuleNotFoundError` cho fastapi, sklearn… | Chưa kích hoạt `.venv` hoặc chưa cài `requirements.txt` |
| `UnicodeEncodeError` khi in tiếng Việt | `$env:PYTHONIOENCODING="utf-8"` rồi chạy lại |
| `no such table` khi gọi API | Chưa chạy `python -m app.seed` |
| Cổng 8000 đã bị dùng | `uvicorn app.main:app --port 8001`, rồi chạy web với `$env:CSM_API_URL="http://127.0.0.1:8001"` |
| Giao diện báo `[LOI]` hoặc 502 ngay sau khi bật Docker | Server đang nạp dữ liệu mẫu, chờ vài giây rồi tải lại |
| Muốn bắt đầu demo lại từ đầu | `python -m app.seed` (Docker: `docker compose exec api python -m app.seed`), rồi tải lại trang |
| `401` / `403` | Thiếu header `Authorization` hoặc token không đúng vai trò |
| `404` khi xem dữ liệu NPP/điểm bán khác | Đúng thiết kế: dữ liệu được cô lập theo NPP |
| `failed to connect to the docker API` | Docker Desktop chưa chạy; mở Docker Desktop, chờ báo *Engine running* |
| Lỗi 500 trên Docker ngay sau khi sửa model | Bảng cũ chưa đổi: `docker compose down -v` rồi `docker compose up -d --build` |
