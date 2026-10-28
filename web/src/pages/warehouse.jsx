import { useState } from 'react'
import { get, newKey, post } from '../api.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Table, Tabs, day, money, useAction, useApi } from '../ui.jsx'

const SWAP_REASONS = [
  ['vi_tri_kho_lay', 'Vị trí kho khó lấy'], ['bao_bi_mop', 'Bao bì móp'],
  ['lo_de_xuat_khong_thay', 'Không thấy lô đề xuất'], ['khac', 'Khác'],
]

// ---- PH2 CN2: soạn hàng FEFO, quét lô, xuất kho ---------------------------------------------

export function PickListsPage() {
  const [tab, setTab] = useState('cho_soan')
  const [sel, setSel] = useState(null)
  const q = useApi(`/ph2/pick-lists?trang_thai=${tab}`)
  return (
    <Page title="Soạn & xuất kho" sub="PH2 CN2 – lệnh xuất đến qua bus sự kiện khi PH1 duyệt đơn; hệ thống đề xuất lô theo FEFO, bỏ lô đỏ và lô khóa"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Tabs tabs={[['cho_soan', 'Chờ soạn'], ['da_xuat', 'Đã xuất'], ['da_giao', 'Đã giao']]} value={tab} onChange={(t) => { setTab(t); setSel(null) }} />
      <div className="grid-2">
        <Card title="Phiếu xuất">
          <Loading q={q} empty="Không có phiếu">
            {(rows) => <Table rows={rows} rowKey={(r) => r.ma_phieu} selected={sel} onRow={(r) => setSel(r.ma_phieu)} cols={[
              { label: 'Phiếu', render: (r) => <span className="mono">{r.ma_phieu}</span> },
              { label: 'Đơn', render: (r) => <span className="mono">{r.ma_don}</span> },
              { label: 'Điểm bán', key: 'ma_diem_ban' },
              { label: 'Ngày giao', render: (r) => day(r.ngay_giao) },
            ]} />}
          </Loading>
        </Card>
        {sel ? <PickDetail key={sel} ma={sel} onDone={() => { q.reload() }} /> : <Card><p className="muted">Chọn một phiếu xuất.</p></Card>}
      </div>
    </Page>
  )
}

function PickDetail({ ma, onDone }) {
  const q = useApi(`/ph2/pick-lists/${ma}`)
  const [run, busy] = useAction()
  const [scan, setScan] = useState({})
  const [reason, setReason] = useState({})
  const [short, setShort] = useState({})
  const reload = () => { q.reload(); onDone() }

  const doScan = async (d) => {
    const lot = scan[d.id] ?? d.ma_lo_de_xuat
    const r = await run(() => post(`/ph2/pick-lists/${ma}/scan`, { dong_id: d.id, ma_lo_quet: lot, ly_do: reason[d.id] || null }),
      (x) => x.thong_bao || `Đã quét ${x.ma_lo_quet}`)
    if (r) q.reload()
  }
  const doShort = async (d) => {
    const n = Number(short[d.id]) || 0
    if (await run(() => post(`/ph2/pick-lists/${ma}/shortage`, { dong_id: d.id, so_luong_thieu: n, ly_do: 'hu_hong_khi_soan' }),
      'Đã báo thiếu – PH1 cắt dòng và tính lại tiền')) reload()
  }

  return (
    <Card title={`Phiếu ${ma}`}>
      <Loading q={q}>
        {(p) => (
          <div className="stack">
            <div className="row"><Badge value={p.trang_thai} /> <span className="muted">Kho {p.ma_kho} · Đơn {p.ma_don}</span></div>
            <Table rows={p.dong} rowKey={(d) => d.id} cols={[
              { label: 'SP', key: 'ma_sp' },
              { label: 'SL', key: 'so_luong', num: true },
              { label: 'Lô đề xuất (FEFO)', render: (d) => <span className="mono">{d.ma_lo_de_xuat}</span> },
              { label: 'Lô quét', render: (d) => p.trang_thai !== 'cho_soan' || d.ma_lo_quet
                ? <span className="row" style={{ gap: 4 }}>
                    <span className="mono">{d.ma_lo_quet || '–'}</span>
                    {d.doi_lo && <Badge kind="warn">Đổi lô</Badge>}
                    {d.canh_bao_fefo && <Badge kind="bad">Sai FEFO</Badge>}
                  </span>
                : <span className="row" style={{ gap: 4 }}>
                    <input className="mono" style={{ width: 130 }} aria-label="Mã lô quét" value={scan[d.id] ?? d.ma_lo_de_xuat}
                           onChange={(e) => setScan((x) => ({ ...x, [d.id]: e.target.value }))} />
                    {(scan[d.id] ?? d.ma_lo_de_xuat) !== d.ma_lo_de_xuat && (
                      <select aria-label="Lý do đổi lô" value={reason[d.id] || ''} onChange={(e) => setReason((x) => ({ ...x, [d.id]: e.target.value }))}>
                        <option value="">Lý do đổi lô…</option>
                        {SWAP_REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </select>
                    )}
                    <Btn sm busy={busy} onClick={() => doScan(d)}>Quét</Btn>
                  </span> },
              { label: 'Báo thiếu', render: (d) => p.trang_thai === 'cho_soan' && (
                <span className="row" style={{ gap: 4 }}>
                  <input type="number" min="1" max={d.so_luong} aria-label="Số thùng thiếu" value={short[d.id] || ''}
                         onChange={(e) => setShort((x) => ({ ...x, [d.id]: e.target.value }))} style={{ width: 64 }} />
                  <Btn kind="ghost" sm busy={busy} disabled={!short[d.id]} onClick={() => doShort(d)}>Báo</Btn>
                </span>
              ) },
            ]} />
            {p.trang_thai === 'cho_soan' && (
              <div className="row">
                <Btn busy={busy} disabled={p.dong.some((d) => !d.ma_lo_quet)}
                     onClick={async () => { if (await run(() => post(`/ph2/pick-lists/${ma}/confirm-issue`), 'Đã xuất kho – đơn sang Chờ giao')) reload() }}>
                  Xác nhận xuất kho
                </Btn>
                <span className="muted">Quét đủ mọi dòng mới xuất được.</span>
              </div>
            )}
          </div>
        )}
      </Loading>
    </Card>
  )
}

// ---- Xác nhận giao (bản tối thiểu, ngoài 12 chức năng) --------------------------------------

export function DeliveryPage() {
  const q = useApi('/ph2/pick-lists?trang_thai=da_xuat')
  const [sel, setSel] = useState(null)
  return (
    <Page title="Giao hàng" sub="Xác nhận giao cần ảnh hoặc chữ ký (BR2.7); sự kiện 'Đã giao' làm PH3 ghi phải thu và PH4 cộng điểm"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <div className="grid-2">
        <Card title="Chờ giao">
          <Loading q={q} empty="Không có phiếu chờ giao">
            {(rows) => <Table rows={rows} rowKey={(r) => r.ma_phieu} selected={sel} onRow={(r) => setSel(r.ma_phieu)} cols={[
              { label: 'Phiếu', render: (r) => <span className="mono">{r.ma_phieu}</span> },
              { label: 'Đơn', render: (r) => <span className="mono">{r.ma_don}</span> },
              { label: 'Điểm bán', key: 'ma_diem_ban' },
              { label: 'Ngày giao', render: (r) => day(r.ngay_giao) },
            ]} />}
          </Loading>
        </Card>
        {sel ? <DeliverForm key={sel} ma={sel} onDone={() => { setSel(null); q.reload() }} /> : <Card><p className="muted">Chọn phiếu cần giao.</p></Card>}
      </div>
    </Page>
  )
}

function DeliverForm({ ma, onDone }) {
  const q = useApi(`/ph2/pick-lists/${ma}`)
  const [run, busy] = useAction()
  const [qty, setQty] = useState({})
  const [photo, setPhoto] = useState(`s3://giao/${ma}.jpg`)
  const [eventId] = useState(() => `EVT-${newKey().slice(0, 16)}`)   // gửi lại không ghi trùng

  const submit = async (p) => {
    const dong = p.dong.map((d) => ({ ma_sp: d.ma_sp, ma_lo: d.ma_lo_quet, so_luong: Number(qty[d.id] ?? d.so_luong) }))
    const r = await run(() => post(`/ph2/deliveries/${ma}/confirm`, { ma_su_kien: eventId, dong, bang_chung: photo ? { anh_url: photo } : {} }),
      'Đã xác nhận giao')
    if (r) onDone()
  }

  return (
    <Card title={`Giao ${ma}`}>
      <Loading q={q}>
        {(p) => (
          <div className="stack">
            <Table rows={p.dong} rowKey={(d) => d.id} cols={[
              { label: 'SP', key: 'ma_sp' },
              { label: 'Lô', render: (d) => <span className="mono">{d.ma_lo_quet}</span> },
              { label: 'Đã xuất', key: 'so_luong', num: true },
              { label: 'Thực giao', num: true, render: (d) => (
                <input type="number" min="0" max={d.so_luong} aria-label={`Thực giao ${d.ma_sp}`} value={qty[d.id] ?? d.so_luong}
                       onChange={(e) => setQty((x) => ({ ...x, [d.id]: e.target.value }))} />
              ) },
            ]} />
            <Field label="Ảnh bằng chứng giao hàng" hint="Xóa trống để thấy hệ thống chặn khi thiếu bằng chứng">
              <input value={photo} onChange={(e) => setPhoto(e.target.value)} />
            </Field>
            <div className="row"><Btn busy={busy} onClick={() => submit(p)}>Xác nhận đã giao</Btn></div>
          </div>
        )}
      </Loading>
    </Card>
  )
}

// ---- PH2 CN5: thủ kho nhận hàng thu hồi -----------------------------------------------------

export function RecallTasksPage() {
  const recalls = useApi('/ph2/recalls')
  const [vu, setVu] = useState(null)
  return (
    <Page title="Nhận hàng thu hồi" sub="PH2 CN5 – nhận lại hàng thu hồi từ điểm bán; PH3 cấn trừ công nợ theo số thực nhận">
      <div className="grid-2">
        <Card title="Vụ thu hồi">
          <Loading q={recalls} empty="Chưa có vụ thu hồi">
            {(rows) => <Table rows={rows} rowKey={(r) => r.ma_vu} selected={vu} onRow={(r) => setVu(r.ma_vu)} cols={[
              { label: 'Vụ', render: (r) => <span className="mono">{r.ma_vu}</span> },
              { label: 'Lô', render: (r) => <span className="mono">{r.ma_lo}</span> },
              { label: 'Lý do', key: 'ly_do' },
              { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
            ]} />}
          </Loading>
        </Card>
        {vu ? <RecallTasks key={vu} ma={vu} canReceive /> : <Card><p className="muted">Chọn một vụ thu hồi.</p></Card>}
      </div>
    </Page>
  )
}

export function RecallTasks({ ma, canReceive, extra }) {
  const q = useApi(`/ph2/recalls/${ma}/tasks`)
  const [run, busy] = useAction()
  const [qty, setQty] = useState({})
  const [last, setLast] = useState(null)
  const receive = async (t) => {
    const r = await run(() => post(`/ph2/recall-tasks/${t.ma_nhiem_vu}/receive`, { so_luong_thuc_nhan: Number(qty[t.ma_nhiem_vu] ?? t.so_luong_da_giao) }),
      'Đã nhận hàng thu hồi – PH3 sẽ cấn trừ công nợ')
    if (r) { setLast(r); q.reload() }
  }
  return (
    <Card title={`Nhiệm vụ của vụ ${ma}`} actions={extra}>
      <Loading q={q} empty="Không có nhiệm vụ (lô chưa giao cho điểm bán nào)">
        {(rows) => <Table rows={rows} rowKey={(r) => r.ma_nhiem_vu} cols={[
          { label: 'Điểm bán', key: 'ma_diem_ban' },
          { label: 'Đã giao', key: 'so_luong_da_giao', num: true },
          { label: 'Thu về', num: true, render: (t) => t.so_luong_thu ?? (canReceive && t.trang_thai === 'mo'
            ? <input type="number" min="0" max={t.so_luong_da_giao} aria-label="Số thùng thu về" value={qty[t.ma_nhiem_vu] ?? t.so_luong_da_giao}
                     onChange={(e) => setQty((x) => ({ ...x, [t.ma_nhiem_vu]: e.target.value }))} />
            : '–') },
          { label: 'Trạng thái', render: (t) => <Badge value={t.trang_thai} /> },
          { label: '', render: (t) => canReceive && t.trang_thai === 'mo' && <Btn sm busy={busy} onClick={() => receive(t)}>Nhận</Btn> },
        ]} />}
      </Loading>
      {last && <Json value={last} />}
    </Card>
  )
}

// Dùng ở trang thu tiền: tra hóa đơn của một điểm bán
export async function outletInvoices(ma) {
  const d = await get(`/ph3/debt/${ma}`)
  return d.hoa_don_mo.map((h) => ({ ...h, label: `${h.so_hoa_don} – còn ${money(h.con_lai)}` }))
}
