import { useState } from 'react'
import { post } from '../api.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Table, Tabs, dt, useAction, useApi } from '../ui.jsx'

const bumpClock = () => window.dispatchEvent(new Event('csm-clock'))

export function SystemPage() {
  const [tab, setTab] = useState('jobs')
  return (
    <Page title="Hệ thống & sự kiện" sub="PH0 – đồng hồ demo, tác vụ định kỳ, bus sự kiện outbox/inbox, thông báo, nhật ký">
      <ClockCard />
      <Tabs tabs={[['jobs', 'Tác vụ định kỳ'], ['events', 'Bus sự kiện'], ['notes', 'Thông báo'], ['audit', 'Nhật ký'], ['agent', 'Nhật ký agent']]}
            value={tab} onChange={setTab} />
      {tab === 'jobs' && <JobsCard />}
      {tab === 'events' && <EventsCard />}
      {tab === 'notes' && <NotesCard />}
      {tab === 'audit' && <AuditCard />}
      {tab === 'agent' && <AgentLogCard />}
    </Page>
  )
}

function ClockCard() {
  const q = useApi('/ph0/clock')
  const [run, busy] = useAction()
  const [at, setAt] = useState('2026-10-28T09:00')
  const set = async (body, msg) => { if (await run(() => post('/ph0/clock', body), msg)) { q.reload(); bumpClock() } }
  return (
    <Card title="Đồng hồ máy chủ" actions={<span className="clock">Hiện tại: <strong>{dt(q.data?.now)}</strong></span>}>
      <div className="form-row">
        <Field label="Đặt giờ"><input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></Field>
        <Btn busy={busy} onClick={() => set({ dat_gio: `${at}:00` }, 'Đã đặt giờ')}>Đặt</Btn>
        <Btn kind="ghost" busy={busy} onClick={() => set({ cong_phut: 30 }, 'Đã tua 30 phút')}>+30 phút</Btn>
        <Btn kind="ghost" busy={busy} onClick={() => set({ cong_phut: 240 }, 'Đã tua 4 giờ')}>+4 giờ</Btn>
        <Btn kind="ghost" busy={busy} onClick={() => set({ cong_phut: 1440 }, 'Đã tua 1 ngày')}>+1 ngày</Btn>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Tua giờ rồi chạy tác vụ “ph1.quet_don_qua_han” để thấy đơn quá hạn BR-06 bị hủy và nhả tồn. Đồng hồ trở về giờ thật khi khởi động lại server.
      </p>
    </Card>
  )
}

function JobsCard() {
  const q = useApi('/ph0/scheduler/jobs')
  const [run, busy] = useAction()
  const [out, setOut] = useState(null)
  const exec = async (ten) => {
    const r = await run(() => post(`/ph0/scheduler/run/${ten}`), `Đã chạy ${ten}`)
    if (r !== undefined) setOut({ ten, r })
  }
  return (
    <div className="grid-2">
      <Card title="Tác vụ">
        <Loading q={q}>
          {(rows) => <Table rows={rows} rowKey={(r) => r.ten} cols={[
            { label: 'Tác vụ', render: (r) => <><span className="mono">{r.ten}</span><br /><span className="muted">{r.mo_ta}</span></> },
            { label: 'Lịch', key: 'lich' },
            { label: '', render: (r) => <Btn sm busy={busy} onClick={() => exec(r.ten)}>Chạy</Btn> },
          ]} />}
        </Loading>
      </Card>
      <Card title={out ? `Kết quả ${out.ten}` : 'Kết quả'}>
        {out ? <Json value={out.r} /> : <p className="muted">Chạy một tác vụ để xem kết quả.</p>}
      </Card>
    </div>
  )
}

function EventsCard() {
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const qs = new URLSearchParams({ limit: 200, ...(status && { trang_thai: status }), ...(type && { loai: type }) })
  const q = useApi(`/ph0/events?${qs}`)
  const [run, busy] = useAction()
  const [sel, setSel] = useState(null)
  const types = [...new Set((q.data || []).map((e) => e.loai))].sort()
  const cur = q.data?.find((e) => e.ma_su_kien === sel)
  return (
    <div className="grid-2">
      <Card title="Sự kiện (outbox)" actions={<>
        <select aria-label="Trạng thái" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Mọi trạng thái</option><option value="cho">Chờ</option><option value="xong">Xong</option><option value="loi">Lỗi</option>
        </select>
        <select aria-label="Loại" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Mọi loại</option>{types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <Btn kind="ghost" sm busy={busy} onClick={async () => { if (await run(() => post('/ph0/events/dispatch'), (r) => `Đã phát ${JSON.stringify(r)}`)) q.reload() }}>Phát sự kiện chờ</Btn>
        <Btn kind="ghost" sm onClick={q.reload}>Tải lại</Btn>
      </>}>
        <Loading q={q} empty="Chưa có sự kiện">
          {(rows) => <Table rows={rows} rowKey={(e) => e.ma_su_kien} selected={sel} onRow={(e) => setSel(e.ma_su_kien)} cols={[
            { label: 'Lúc', render: (e) => dt(e.tao_luc) },
            { label: 'Loại', render: (e) => <span className="mono">{e.loai}</span> },
            { label: 'Trạng thái', render: (e) => <Badge value={e.trang_thai} /> },
            { label: 'Thử', key: 'so_lan_thu', num: true },
          ]} />}
        </Loading>
      </Card>
      <Card title={cur ? cur.ma_su_kien : 'Nội dung sự kiện'}>
        {cur ? <>{cur.loi && <div className="notice notice-bad">{cur.loi}</div>}<Json value={cur.payload} /></> : <p className="muted">Chọn một sự kiện.</p>}
      </Card>
    </div>
  )
}

function NotesCard() {
  const q = useApi('/ph0/notifications?limit=100')
  return (
    <Card title="Thông báo đã gửi (Zalo / app / SMS giả lập)" actions={<Btn kind="ghost" sm onClick={q.reload}>Tải lại</Btn>}>
      <Loading q={q} empty="Chưa có thông báo">
        {(rows) => <Table rows={rows} cols={[
          { label: 'Lúc', render: (r) => dt(r.luc) }, { label: 'Kênh', key: 'kenh' }, { label: 'Người nhận', key: 'nguoi_nhan' },
          { label: 'Nội dung', render: (r) => <><strong>{r.tieu_de}</strong> – {r.noi_dung}</> },
        ]} />}
      </Loading>
    </Card>
  )
}

function AuditCard() {
  const q = useApi('/ph0/audit?limit=200')
  return (
    <Card title="Nhật ký thay đổi" actions={<Btn kind="ghost" sm onClick={q.reload}>Tải lại</Btn>}>
      <Loading q={q} empty="Chưa có thay đổi nào được ghi">
        {(rows) => <Table rows={rows} cols={[
          { label: 'Lúc', render: (r) => dt(r.luc) }, { label: 'Ai', key: 'ai' }, { label: 'Hành động', key: 'hanh_dong' },
          { label: 'Đối tượng', render: (r) => `${r.doi_tuong} ${r.ma}` },
          { label: 'Cũ → mới', render: (r) => <span className="mono">{JSON.stringify(r.cu)} → {JSON.stringify(r.moi)}</span> },
        ]} />}
      </Loading>
    </Card>
  )
}

function AgentLogCard() {
  const q = useApi('/ph0/agent/log')
  return (
    <Card title="Nhật ký agent Zalo" actions={<Btn kind="ghost" sm onClick={q.reload}>Tải lại</Btn>}>
      <Loading q={q} empty="Agent chưa được gọi">
        {(rows) => <Table rows={rows} cols={Object.keys(rows[0]).map((k) => ({
          label: k, render: (r) => (typeof r[k] === 'object' && r[k] !== null ? <span className="mono">{JSON.stringify(r[k])}</span> : String(r[k] ?? '–')),
        }))} />}
      </Loading>
    </Card>
  )
}
