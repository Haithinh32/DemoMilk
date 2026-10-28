import { useState } from 'react'
import { newKey, post } from '../api.js'
import { useMe } from '../auth.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Stat, Table, Tabs, dt, money, pct, useAction, useApi } from '../ui.jsx'
import { outletInvoices } from './warehouse.jsx'

// ---- PH3 CN1: ngoại lệ tín dụng -------------------------------------------------------------

export function ExceptionsPage() {
  const q = useApi('/ph3/exceptions')
  const [run, busy] = useAction()
  const [reason, setReason] = useState({})
  const decide = async (y, duyet) => {
    const r = await run(() => post(`/ph3/exceptions/${y.ma_yc}/decide`, { duyet, ly_do: reason[y.ma_yc] || null }),
      duyet ? 'Đã duyệt – PH1 nhận kết quả qua bus và duyệt tiếp đơn' : 'Đã từ chối – PH1 hủy đơn, nhả tồn')
    if (r) q.reload()
  }
  return (
    <Page title="Ngoại lệ tín dụng" sub="PH3 CN1 – đơn vượt hạn mức mà điểm bán xin mua chịu; hạn xử lý trong giờ hành chính (BR-06)"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Card>
        <Loading q={q} empty="Không có yêu cầu đang chờ">
          {(rows) => <Table rows={rows} rowKey={(r) => r.ma_yc} cols={[
            { label: 'Yêu cầu', render: (r) => <span className="mono">{r.ma_yc}</span> },
            { label: 'Đơn', render: (r) => <span className="mono">{r.ma_don}</span> },
            { label: 'Điểm bán', key: 'ma_diem_ban' },
            { label: 'Số tiền', num: true, render: (r) => money(r.so_tien) },
            { label: 'Lý do điểm bán', key: 'ly_do' },
            { label: 'Hạn', render: (r) => dt(r.han) },
            { label: 'Ghi chú', render: (r) => <input aria-label="Ghi chú quyết định" value={reason[r.ma_yc] || ''} onChange={(e) => setReason((x) => ({ ...x, [r.ma_yc]: e.target.value }))} /> },
            { label: '', render: (r) => (
              <span className="row" style={{ gap: 4 }}>
                <Btn kind="good" sm busy={busy} onClick={() => decide(r, true)}>Duyệt</Btn>
                <Btn kind="danger" sm busy={busy} onClick={() => decide(r, false)}>Từ chối</Btn>
              </span>
            ) },
          ]} />}
        </Loading>
      </Card>
    </Page>
  )
}

// ---- PH3 CN3: báo có chờ xử lý --------------------------------------------------------------

export function PaymentsPage() {
  const q = useApi('/ph3/payments/pending')
  const [run, busy] = useAction()
  const [inv, setInv] = useState({})
  const assign = async (g) => {
    const r = await run(() => post(`/ph3/payments/${g.ma_gd}/assign`, { so_hoa_don: inv[g.ma_gd] }), 'Đã gạch nợ theo hóa đơn chỉ định')
    if (r) q.reload()
  }
  return (
    <Page title="Báo có chờ xử lý" sub="PH3 CN3 – chuyển khoản không đọc được mã hóa đơn trong nội dung; kế toán chỉ định hóa đơn"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Card>
        <Loading q={q} empty="Không có giao dịch chờ xử lý">
          {(rows) => <Table rows={rows} rowKey={(r) => r.ma_gd} cols={[
            { label: 'Giao dịch', render: (r) => <span className="mono">{r.ma_gd}</span> },
            { label: 'Ngày', key: 'ngay' },
            { label: 'Số tiền', num: true, render: (r) => money(r.so_tien) },
            { label: 'Nội dung', key: 'noi_dung' },
            { label: 'Hóa đơn', render: (r) => <input className="mono" aria-label="Số hóa đơn" placeholder="HD-…" value={inv[r.ma_gd] || ''} onChange={(e) => setInv((x) => ({ ...x, [r.ma_gd]: e.target.value.trim() }))} /> },
            { label: '', render: (r) => <Btn sm busy={busy} disabled={!inv[r.ma_gd]} onClick={() => assign(r)}>Gạch nợ</Btn> },
          ]} />}
        </Loading>
      </Card>
    </Page>
  )
}

// ---- PH3 CN3: đối soát 3 nguồn, khóa sổ -----------------------------------------------------

export function ReconcilePage() {
  const me = useMe()
  const npp = me.ma_npp || 'NPP01'
  const q = useApi(`/ph3/reconcile/${npp}`)
  const [run, busy] = useAction()
  const [res, setRes] = useState(null)
  const [adj, setAdj] = useState({ no_tk: '6428', co_tk: '1111', so_tien: '', ly_do: '' })
  const ktt = me.vai_tro === 'ke_toan_truong'

  const close = async () => {
    const r = await run(() => post(`/ph3/close-day/${npp}`), (x) => (x.khoa_so ? 'Đã khóa sổ ngày, ghi bút toán cho NPP' : 'Chưa khóa được – còn chênh lệch hoặc giao dịch chờ'))
    if (r) { setRes(r); q.reload() }
  }
  const adjust = async () => {
    const r = await run(() => post(`/ph3/adjustments/${npp}`, { ...adj, so_tien: Number(adj.so_tien), ngay: q.data.ngay }), 'Đã ghi bút toán điều chỉnh')
    if (r) { setRes(r); q.reload() }
  }

  return (
    <Page title={`Đối soát & khóa sổ – ${npp}`} sub="PH3 CN3 – đối chiếu ngân hàng, quỹ thực nộp và số đã ghi nhận; chỉ khóa sổ khi khớp"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Loading q={q}>
        {(r) => (
          <>
            <div className="grid-stats">
              <Stat label="Ngân hàng báo có" value={money(r.ngan_hang)} />
              <Stat label="Quỹ thực nộp" value={money(r.quy_thuc_nop)} />
              <Stat label="Đã ghi nhận" value={money(r.da_ghi_nhan)} />
              <Stat label="Chênh lệch" value={money(r.chenh_lech)} sub={r.chenh_lech === 0 ? 'Khớp' : 'Cần xử lý'} />
              <Stat label="Giao dịch chờ xử lý" value={r.giao_dich_cho_xu_ly} />
            </div>
            <Card title={`Ngày ${r.ngay}`}>
              <div className="row">
                {r.chenh_lech === 0 && !r.giao_dich_cho_xu_ly ? <Badge kind="good">Ba nguồn khớp</Badge> : <Badge kind="bad">Chưa khớp</Badge>}
                {ktt && <Btn busy={busy} onClick={close}>Khóa sổ ngày</Btn>}
              </div>
              {res && <Json value={res} />}
            </Card>
          </>
        )}
      </Loading>
      {ktt && (
        <Card title="Bút toán điều chỉnh (kế toán trưởng)">
          <div className="form-row">
            <Field label="Nợ TK"><input value={adj.no_tk} onChange={(e) => setAdj({ ...adj, no_tk: e.target.value })} /></Field>
            <Field label="Có TK"><input value={adj.co_tk} onChange={(e) => setAdj({ ...adj, co_tk: e.target.value })} /></Field>
            <Field label="Số tiền"><input type="number" style={{ width: 140 }} value={adj.so_tien} onChange={(e) => setAdj({ ...adj, so_tien: e.target.value })} /></Field>
            <Field label="Lý do"><input value={adj.ly_do} onChange={(e) => setAdj({ ...adj, ly_do: e.target.value })} /></Field>
            <Btn kind="ghost" busy={busy} disabled={!adj.so_tien || !adj.ly_do} onClick={adjust}>Ghi bút toán</Btn>
          </div>
        </Card>
      )}
    </Page>
  )
}

// ---- Thu tiền mặt (NV giao hàng) và nộp quỹ (thủ quỹ) ---------------------------------------

export function CashPage() {
  const [outlet, setOutlet] = useState('DB-01-002')
  const [invoices, setInvoices] = useState(null)
  const [inv, setInv] = useState('')
  const [amount, setAmount] = useState('')
  const [receipt, setReceipt] = useState(() => `BN-${newKey().slice(0, 10).toUpperCase()}`)
  const [run, busy] = useAction()
  const [res, setRes] = useState(null)

  const load = async () => {
    const r = await run(() => outletInvoices(outlet))
    if (r) { setInvoices(r); setInv(r[0]?.so_hoa_don || ''); setAmount(r[0]?.con_lai || '') }
  }
  const submit = async () => {
    const r = await run(() => post('/ph3/cash', { so_hoa_don: inv, so_tien: Number(amount), ma_bien_nhan: receipt }), 'Đã ghi nhận thu tiền mặt')
    if (r) { setRes(r); setReceipt(`BN-${newKey().slice(0, 10).toUpperCase()}`); load() }
  }

  return (
    <Page title="Thu tiền mặt" sub="Đơn trả tiền khi nhận: thu tại điểm bán, mỗi biên nhận ghi một lần, cuối ngày nộp thủ quỹ">
      <Card>
        <div className="form-row">
          <Field label="Điểm bán"><input value={outlet} onChange={(e) => setOutlet(e.target.value.trim())} /></Field>
          <Btn kind="ghost" busy={busy} onClick={load}>Xem hóa đơn</Btn>
        </div>
        {invoices && (invoices.length === 0 ? <p className="muted">Điểm bán không còn hóa đơn nợ.</p> : (
          <div className="form-row">
            <Field label="Hóa đơn">
              <select value={inv} onChange={(e) => { setInv(e.target.value); setAmount(invoices.find((i) => i.so_hoa_don === e.target.value)?.con_lai || '') }}>
                {invoices.map((i) => <option key={i.so_hoa_don} value={i.so_hoa_don}>{i.label}</option>)}
              </select>
            </Field>
            <Field label="Số tiền"><input type="number" style={{ width: 140 }} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Mã biên nhận" hint="Gửi lại cùng mã không ghi trùng"><input className="mono" value={receipt} onChange={(e) => setReceipt(e.target.value)} /></Field>
            <Btn busy={busy} onClick={submit}>Ghi nhận</Btn>
          </div>
        ))}
        {res && <Json value={res} />}
      </Card>
    </Page>
  )
}

export function HandoverPage() {
  const [collector, setCollector] = useState('GH-01')
  const [amount, setAmount] = useState('')
  const [run, busy] = useAction()
  const [res, setRes] = useState(null)
  const submit = async () => {
    const r = await run(() => post('/ph3/cash-handover', { ma_nguoi_thu: collector, thuc_nop: Number(amount) }), 'Đã nhận nộp quỹ')
    if (r) setRes(r)
  }
  return (
    <Page title="Nhận nộp quỹ" sub="Thủ quỹ nhận tiền mặt NV giao hàng đã thu; lệch so với biên nhận được ghi để đối soát">
      <Card>
        <div className="form-row">
          <Field label="Người nộp"><input value={collector} onChange={(e) => setCollector(e.target.value)} /></Field>
          <Field label="Số tiền thực nộp"><input type="number" style={{ width: 160 }} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Btn busy={busy} disabled={amount === ''} onClick={submit}>Xác nhận</Btn>
        </div>
        {res && <Json value={res} />}
      </Card>
    </Page>
  )
}

// ---- PH3 NC1: chấm điểm tín dụng ------------------------------------------------------------

export function ScoresPage() {
  const me = useMe()
  const q = useApi('/ph3/nc1/scores')
  const [tab, setTab] = useState('de_xuat')
  const [run, busy] = useAction()
  const [limit, setLimit] = useState({})
  const rows = (q.data || []).filter((d) => !tab || d.trang_thai === tab)
  const decide = async (d, accept) => {
    const body = accept ? { ly_do: 'chấp nhận đề xuất' } : { han_muc_chot: Number(limit[d.id]), ly_do: 'kế toán trưởng điều chỉnh' }
    if (await run(() => post(`/ph3/nc1/scores/${d.id}/decide`, body), 'Đã chốt hạn mức')) q.reload()
  }
  return (
    <Page title="Chấm điểm tín dụng" sub="PH3 NC1 – xác suất quá hạn 30 ngày (hồi quy logistic trên 12 tháng lịch sử mô phỏng), hạng A–D, hạn mức đề xuất"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Tabs tabs={[['de_xuat', 'Chờ quyết định'], ['chap_nhan', 'Chấp nhận'], ['sua', 'Đã sửa'], ['giu_mac_dinh', 'Chưa đủ lịch sử'], ['', 'Tất cả']]} value={tab} onChange={setTab} />
      <Card>
        <Loading q={q} empty="Chưa có kết quả – quản trị chạy tác vụ ph3.nc1_cham_diem">
          {() => <Table rows={rows} rowKey={(d) => d.id} cols={[
            { label: 'Điểm bán', key: 'ma_diem_ban' },
            { label: 'Kỳ', key: 'ky' },
            { label: 'XS quá hạn', num: true, render: (d) => pct(d.xac_suat) },
            { label: 'Hạng', render: (d) => <Badge kind={{ A: 'good', B: 'info', C: 'warn', D: 'bad' }[d.hang] || 'muted'}>{d.hang}</Badge> },
            { label: 'Hạn mức hiện tại', num: true, render: (d) => money(d.han_muc_hien_tai) },
            { label: 'Đề xuất', num: true, render: (d) => money(d.han_muc_de_xuat) },
            { label: 'Căn cứ', render: (d) => (d.ly_do || []).join(', ') },
            { label: 'Trạng thái', render: (d) => <Badge value={d.trang_thai} /> },
            { label: '', render: (d) => me.vai_tro === 'ke_toan_truong' && d.trang_thai === 'de_xuat' && (
              <span className="row" style={{ gap: 4 }}>
                <Btn kind="good" sm busy={busy} onClick={() => decide(d, true)}>Chấp nhận</Btn>
                <input type="number" aria-label="Hạn mức chốt" placeholder="Hạn mức khác" style={{ width: 120 }} value={limit[d.id] || ''}
                       onChange={(e) => setLimit((x) => ({ ...x, [d.id]: e.target.value }))} />
                <Btn kind="ghost" sm busy={busy} disabled={!limit[d.id]} onClick={() => decide(d, false)}>Sửa</Btn>
              </span>
            ) },
          ]} />}
        </Loading>
      </Card>
    </Page>
  )
}
