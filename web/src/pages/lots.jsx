import { useState } from 'react'
import { post } from '../api.js'
import { useMe } from '../auth.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Table, Tabs, day, num, useAction, useApi } from '../ui.jsx'
import { RecallTasks } from './warehouse.jsx'

const COLORS = [['', 'Tất cả'], ['do', 'Lô đỏ'], ['vang', 'Lô vàng'], ['xanh', 'Còn hạn'], ['khoa', 'Đang khóa']]

export function LotsPage() {
  const me = useMe()
  const q = useApi('/ph2/lots')
  const [filter, setFilter] = useState('')
  const [sel, setSel] = useState(null)
  const rows = (q.data || []).filter((l) => !filter || (filter === 'khoa' ? l.trang_thai === 'khoa' : l.mau === filter))
  const lot = q.data?.find((l) => `${l.ma_lo}|${l.ma_kho}` === sel)

  return (
    <Page title="Lô hàng" sub="Màu theo hạn dùng còn lại: đỏ < 3 ngày (không bán cho điểm bán), vàng ≤ max(4 ngày, 50% hạn dùng) – đầu vào NC2"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Tabs tabs={COLORS} value={filter} onChange={setFilter} />
      <div className="grid-2">
        <Card title={`${rows.length} lô`}>
          <Loading q={q}>
            {() => <Table rows={rows} rowKey={(l) => `${l.ma_lo}|${l.ma_kho}`} selected={sel} onRow={(l) => setSel(`${l.ma_lo}|${l.ma_kho}`)} cols={[
              { label: 'Lô', render: (l) => <span className="mono">{l.ma_lo}</span> },
              { label: 'SP', render: (l) => <span title={l.ten_sp}>{l.ma_sp}</span> },
              { label: 'Kho', key: 'ma_kho' },
              { label: 'Tồn', key: 'so_luong', num: true },
              { label: 'HSD', render: (l) => day(l.hsd) },
              { label: 'Còn', num: true, render: (l) => `${l.con_ngay} ngày` },
              { label: 'Hạn', render: (l) => <Badge value={l.mau} /> },
              { label: 'Trạng thái', render: (l) => <Badge value={l.trang_thai} /> },
            ]} />}
          </Loading>
        </Card>
        {lot ? <LotPanel key={lot.ma_lo} lot={lot} qa={me.vai_tro === 'qa'} onDone={q.reload} />
          : <Card><p className="muted">Chọn một lô để {me.vai_tro === 'qa' ? 'khóa, truy xuất hoặc thu hồi' : 'xem truy xuất'}.</p></Card>}
      </div>
    </Page>
  )
}

function LotPanel({ lot, qa, onDone }) {
  const [run, busy] = useAction()
  const [reason, setReason] = useState('')
  const [result, setResult] = useState(null)
  const trace = useApi(`/ph2/lots/${lot.ma_lo}/trace`)
  const act = async (path, body, msg) => {
    const r = await run(() => post(`/ph2/lots/${lot.ma_lo}/${path}`, body), msg)
    if (r) { setResult(r); onDone(); trace.reload() }
  }

  return (
    <div className="stack">
      <Card title={`Lô ${lot.ma_lo} – ${lot.ten_sp}`}>
        <div className="row">
          <Badge value={lot.mau} /> <Badge value={lot.trang_thai} />
          <span className="muted">NSX {day(lot.nsx)} · HSD {day(lot.hsd)}</span>
        </div>
        {lot.ly_do_khoa && <div className="notice notice-bad">Lý do khóa: {lot.ly_do_khoa}</div>}
        {qa && (
          <div className="stack">
            <Field label={lot.trang_thai === 'khoa' ? 'Kết quả kiểm nghiệm (để mở khóa)' : 'Lý do khóa / thu hồi'}>
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={lot.trang_thai === 'khoa' ? 'VD: đạt chỉ tiêu vi sinh' : 'VD: khiếu nại vị chua'} />
            </Field>
            <div className="row">
              {lot.trang_thai !== 'khoa'
                ? <Btn kind="danger" busy={busy} onClick={() => act('lock', { ly_do: reason || 'nghi vấn chất lượng' }, 'Đã khóa lô – các phiếu đang soạn được chuyển lô')}>Khóa lô</Btn>
                : <Btn kind="good" busy={busy} onClick={() => act('unlock', { ket_qua_kiem_nghiem: reason || 'đạt' }, 'Đã mở khóa lô')}>Mở khóa</Btn>}
              <Btn kind="ghost" busy={busy} onClick={() => act('recall', { ly_do: reason || 'thu hồi phòng ngừa' }, (r) => `Đã mở vụ ${r.ma_vu}, ${r.so_nhiem_vu} nhiệm vụ thu hồi`)}>Mở vụ thu hồi</Btn>
            </div>
            {result && <Json value={result} />}
          </div>
        )}
      </Card>
      <Card title="Truy xuất xuôi (kho → điểm bán)">
        <Loading q={trace}>
          {(t) => (
            <div className="stack">
              <p className="muted">Truy xuất trong {num(t.thoi_gian_truy_xuat_ms, 1)} ms · Tổng đã giao {t.tong_da_giao} thùng</p>
              <Table rows={Object.entries(t.kho).map(([k, v]) => ({ kho: k, ...v }))} rowKey={(r) => r.kho} cols={[
                { label: 'Kho', key: 'kho' },
                { label: 'Nhập', render: (r) => Object.entries(r.nhap).map(([n, s]) => `${n}: ${s}`).join(', ') },
                { label: 'Tồn bán', key: 'ton_ban', num: true },
                { label: 'Tồn hỏng', key: 'ton_hong', num: true },
              ]} />
              <Table rows={t.diem_ban} empty="Lô chưa giao cho điểm bán nào"
                     cols={Object.keys(t.diem_ban[0] || {}).map((k) => ({ label: k, key: k }))} />
            </div>
          )}
        </Loading>
      </Card>
    </div>
  )
}

export function RecallsPage() {
  const q = useApi('/ph2/recalls')
  const [sel, setSel] = useState(null)
  const [run, busy] = useAction()
  const close = async () => {
    if (await run(() => post(`/ph2/recalls/${sel}/close`), 'Đã đóng vụ thu hồi')) q.reload()
  }
  return (
    <Page title="Vụ thu hồi" sub="PH2 CN5 – mở vụ từ trang Lô hàng; thủ kho NPP nhận hàng về; QA đóng vụ khi thu đủ"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <div className="grid-2">
        <Card title="Danh sách">
          <Loading q={q} empty="Chưa có vụ thu hồi – mở vụ ở trang Lô hàng">
            {(rows) => <Table rows={rows} rowKey={(r) => r.ma_vu} selected={sel} onRow={(r) => setSel(r.ma_vu)} cols={[
              { label: 'Vụ', render: (r) => <span className="mono">{r.ma_vu}</span> },
              { label: 'Lô', render: (r) => <span className="mono">{r.ma_lo}</span> },
              { label: 'Lý do', key: 'ly_do' },
              { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
            ]} />}
          </Loading>
        </Card>
        {sel ? <RecallTasks key={sel} ma={sel} extra={<Btn kind="ghost" sm busy={busy} onClick={close}>Đóng vụ</Btn>} />
          : <Card><p className="muted">Chọn một vụ.</p></Card>}
      </div>
    </Page>
  )
}
