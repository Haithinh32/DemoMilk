import { useState } from 'react'
import { post } from '../api.js'
import { useMe } from '../auth.js'
import { Badge, Btn, Card, Field, Loading, Page, Table, Tabs, dt, day, money, useAction, useApi } from '../ui.jsx'

const FILTERS = [
  ['', 'Tất cả'], ['CHO_DIEM_BAN_CHON', 'Chờ điểm bán chọn'], ['CHO_DUYET_NGOAI_LE_TD', 'Chờ ngoại lệ'],
  ['CHO_NPP_DUYET', 'Chờ NPP duyệt'], ['DA_DUYET', 'Đã duyệt'], ['DA_GIAO', 'Đã giao'], ['DA_HUY', 'Đã hủy'],
]

export function OrdersPage() {
  const me = useMe()
  const [filter, setFilter] = useState(me.vai_tro === 'npp' ? 'CHO_NPP_DUYET' : '')
  const [sel, setSel] = useState(null)
  const q = useApi(`/ph1/orders${filter ? `?trang_thai=${filter}` : ''}`)
  return (
    <Page title="Đơn hàng" sub="PH1 CN2–CN3: theo dõi trạng thái, các bước duyệt và hạn xử lý (BR-06)"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Tabs tabs={FILTERS} value={filter} onChange={(f) => { setFilter(f); setSel(null) }} />
      <div className="grid-2">
        <Card title="Danh sách">
          <Loading q={q} empty="Không có đơn nào">
            {(rows) => (
              <Table rows={rows} rowKey={(r) => r.ma_don} selected={sel} onRow={(r) => setSel(r.ma_don)} cols={[
                { label: 'Mã đơn', render: (r) => <span className="mono">{r.ma_don}</span> },
                { label: 'Điểm bán', key: 'ma_diem_ban' },
                { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
                { label: 'Tổng tiền', num: true, render: (r) => money(r.tong_tien) },
                { label: 'Nguồn', key: 'nguon' },
                { label: 'Tạo lúc', render: (r) => dt(r.tao_luc) },
              ]} />
            )}
          </Loading>
        </Card>
        {sel ? <OrderDetail ma={sel} onChange={q.reload} /> : <Card><p className="muted">Chọn một đơn để xem chi tiết.</p></Card>}
      </div>
    </Page>
  )
}

export function OrderDetail({ ma, onChange }) {
  const q = useApi(`/ph1/orders/${ma}`)
  const reload = () => { q.reload(); onChange?.() }
  return (
    <Card title={`Đơn ${ma}`} actions={<Btn kind="ghost" sm onClick={q.reload}>Tải lại</Btn>}>
      <Loading q={q}>{(o) => <OrderBody o={o} onDone={reload} />}</Loading>
    </Card>
  )
}

export function OrderBody({ o, onDone }) {
  return (
    <div className="stack">
      <div className="row">
        <Badge value={o.trang_thai} />
        {o.tu_dong_duyet && <Badge kind="good">Duyệt tự động</Badge>}
        <Badge kind={o.hinh_thuc_tt === 'tra_ngay' ? 'warn' : 'info'}>
          {o.hinh_thuc_tt === 'tra_ngay' ? 'Trả tiền khi nhận' : 'Mua chịu (công nợ)'}
        </Badge>
      </div>
      {o.han_trang_thai && <div className="notice notice-warn">Hạn xử lý trạng thái này: <strong>{dt(o.han_trang_thai)}</strong> – quá hạn hệ thống tự hủy và nhả tồn.</div>}
      {o.ly_do && <div className="notice">Lý do: {o.ly_do}</div>}
      <Table rows={o.dong} rowKey={(d) => d.ma_sp} cols={[
        { label: 'Sản phẩm', key: 'ma_sp' },
        { label: 'SL (thùng)', key: 'so_luong', num: true },
        { label: 'Đơn giá', num: true, render: (d) => money(d.don_gia) },
        { label: 'KM', render: (d) => d.ma_km ? `${d.ma_km} (−${money(d.tien_km)})` : '–' },
        { label: 'Thành tiền', num: true, render: (d) => money(d.thanh_tien) },
      ]} />
      <div className="row">
        <span>Trước KM: {money(o.tong_truoc_km)}</span>
        <span>· KM: −{money(o.tong_km)}</span>
        <strong className="right">Tổng: {money(o.tong_tien)}</strong>
      </div>
      <div className="row muted">
        <span>Ngày giao: {day(o.ngay_giao)}</span>
        {o.giao_hang && <span>· Kho: <Badge value={o.giao_hang.trang_thai} /></span>}
      </div>
      <OrderActions o={o} onDone={onDone} />
    </div>
  )
}

function OrderActions({ o, onDone }) {
  const me = useMe()
  const [run, busy] = useAction()
  const [reason, setReason] = useState('')
  const act = async (path, body, msg) => { if (await run(() => post(`/ph1/orders/${o.ma_don}/${path}`, body), msg)) { setReason(''); onDone() } }

  const outletSide = ['diem_ban', 'nvbh'].includes(me.vai_tro)
  const blocks = []
  if (o.trang_thai === 'CHO_DIEM_BAN_CHON' && outletSide) {
    blocks.push(
      <div key="credit" className="stack">
        <div className="notice notice-warn">Đơn vượt hạn mức tín dụng. Chọn trả tiền khi nhận hàng, hoặc xin kế toán trưởng duyệt ngoại lệ.</div>
        <Field label="Lý do xin ngoại lệ"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="VD: khách quen, cuối tuần thanh toán" /></Field>
        <div className="row">
          <Btn busy={busy} onClick={() => act('credit-choice', { lua_chon: 'tra_ngay' }, 'Đã chuyển sang trả tiền khi nhận')}>Trả tiền khi nhận</Btn>
          <Btn kind="ghost" busy={busy} onClick={() => act('credit-choice', { lua_chon: 'xin_ngoai_le', ly_do: reason }, 'Đã gửi yêu cầu ngoại lệ cho PH3')}>Xin ngoại lệ tín dụng</Btn>
        </div>
      </div>,
    )
  }
  if (o.trang_thai === 'CHO_NPP_DUYET' && me.vai_tro === 'npp') {
    blocks.push(
      <div key="npp" className="stack">
        <Field label="Ghi chú / lý do"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="row">
          <Btn kind="good" busy={busy} onClick={() => act('npp-decision', { duyet: true, ly_do: reason || null }, 'Đã duyệt đơn')}>Duyệt</Btn>
          <Btn kind="danger" busy={busy} onClick={() => act('npp-decision', { duyet: false, ly_do: reason || 'NPP từ chối' }, 'Đã từ chối đơn')}>Từ chối</Btn>
        </div>
      </div>,
    )
  }
  const cancellable = !['DA_GIAO', 'DA_HUY', 'CHO_GIAO'].includes(o.trang_thai)
  if (cancellable && ['diem_ban', 'nvbh', 'npp'].includes(me.vai_tro)) {
    blocks.push(
      <div key="cancel" className="row">
        <Btn kind="ghost" busy={busy} onClick={() => act('cancel', { ly_do: reason || 'Hủy theo yêu cầu' }, 'Đã hủy đơn, nhả tồn và hạn mức')}>Hủy đơn</Btn>
      </div>,
    )
  }
  return blocks.length ? <div className="stack">{blocks}</div> : null
}
