// Bản mẫu đăng nhập bằng token cố định (bản thật: OTP + JWT).
export const ACCOUNTS = [
  { token: 'tok-db-01-001', label: 'Điểm bán DB-01-001', note: 'Hạn mức bình thường', group: 'Điểm bán' },
  { token: 'tok-db-01-002', label: 'Điểm bán DB-01-002', note: 'Có nợ quá hạn → trả tiền khi nhận', group: 'Điểm bán' },
  { token: 'tok-db-01-003', label: 'Điểm bán DB-01-003', note: 'Hạn mức 2 triệu → dễ vượt hạn mức', group: 'Điểm bán' },
  { token: 'tok-db-02-001', label: 'Điểm bán DB-02-001', note: 'Thuộc NPP02 (kho K02)', group: 'Điểm bán' },
  { token: 'tok-bh-01', label: 'NV bán hàng NPP01', note: 'Đi tuyến, check-in, đặt hộ', group: 'NPP01' },
  { token: 'tok-npp-01', label: 'Chủ NPP01', note: 'Duyệt đơn ngoại lệ, đơn bổ sung', group: 'NPP01' },
  { token: 'tok-npp-02', label: 'Chủ NPP02', note: 'Đơn bổ sung từ dự báo NC2', group: 'NPP02' },
  { token: 'tok-tk-01', label: 'Thủ kho NPP01', note: 'Soạn hàng FEFO, quét lô', group: 'NPP01' },
  { token: 'tok-gh-01', label: 'NV giao hàng NPP01', note: 'Xác nhận giao, thu tiền mặt', group: 'NPP01' },
  { token: 'tok-kt-01', label: 'Kế toán NPP01', note: 'Báo có chờ xử lý', group: 'NPP01' },
  { token: 'tok-ktt-01', label: 'Kế toán trưởng NPP01', note: 'Ngoại lệ tín dụng, khóa sổ, hạn mức', group: 'NPP01' },
  { token: 'tok-tq-01', label: 'Thủ quỹ NPP01', note: 'Nhận nộp tiền mặt', group: 'NPP01' },
  { token: 'tok-pkd', label: 'Phòng kinh doanh', note: 'Lập KM, đề xuất NC1, chốt đơn bổ sung', group: 'Công ty' },
  { token: 'tok-gdkd', label: 'Giám đốc kinh doanh', note: 'Duyệt KM', group: 'Công ty' },
  { token: 'tok-qa', label: 'QA công ty', note: 'Khóa lô, truy xuất, thu hồi', group: 'Công ty' },
  { token: 'tok-bdh', label: 'Ban điều hành', note: 'Dashboard toàn công ty', group: 'Công ty' },
  { token: 'tok-admin', label: 'Quản trị', note: 'Tác vụ định kỳ, đồng hồ, bus sự kiện', group: 'Công ty' },
]

export function Login({ onLogin }) {
  const groups = [...new Set(ACCOUNTS.map((a) => a.group))]
  return (
    <div className="login">
      <div>
        <h1>Cao Sơn Milk – Bản mẫu B2B & quản lý phân phối</h1>
        <p className="muted" style={{ marginTop: 6 }}>
          Chọn một vai trò để đăng nhập. Có thể đổi vai trò bất cứ lúc nào ở góc trên bên phải.
          Dữ liệu lịch sử là dữ liệu mô phỏng.
        </p>
      </div>
      {groups.map((g) => (
        <section key={g} className="stack">
          <h2>{g}</h2>
          <div className="login-grid">
            {ACCOUNTS.filter((a) => a.group === g).map((a) => (
              <button key={a.token} className="login-card" onClick={() => onLogin(a.token)}>
                <strong>{a.label}</strong>
                <small>{a.note}</small>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
