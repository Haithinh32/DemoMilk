import { useState } from 'react'
import { post } from '../api.js'
import { useMe } from '../auth.js'
import { BarChart } from '../charts.jsx'
import { Badge, Btn, Card, Field, Loading, Page, Stat, Table, Tabs, money, num, pct, useAction, useApi } from '../ui.jsx'

const PHAN_HE = { PH1: 'PH1 – Đặt hàng', PH2: 'PH2 – Kho & lô', PH3: 'PH3 – Tín dụng & đối soát', PH4: 'PH4 – Bán hàng' }
const DRILL = [['vung', 'Vùng'], ['npp', 'NPP'], ['san_pham', 'Sản phẩm'], ['diem_ban', 'Điểm bán'], ['nvbh', 'NV bán hàng']]

// Tên hiển thị cho chỉ số chưa khai báo ngưỡng trong bảng nguong_kpi
const KPI_NAMES = {
  so_don: 'Số đơn trong ngày', so_npp_da_khoa_so: 'Số NPP đã khóa sổ',
  chenh_lech_doi_soat: 'Chênh lệch đối soát', diem_ban_hoat_dong_30_ngay: 'Điểm bán hoạt động 30 ngày',
}
const kpiName = (k) => (k.ten && k.ten !== k.ma_kpi ? k.ten : KPI_NAMES[k.ma_kpi] || k.ma_kpi)

const fmtKpi = (k) => {
  if (k.gia_tri == null) return '–'
  if (k.ma_kpi.startsWith('ty_le')) return pct(k.gia_tri)
  if (k.ma_kpi.includes('_ms')) return `${num(k.gia_tri, 1)} ms`
  if (k.ma_kpi.includes('phut')) return `${num(k.gia_tri, 1)} phút`
  if (k.ma_kpi.includes('chenh_lech')) return money(k.gia_tri)
  return num(k.gia_tri, 2)
}
const fmtTarget = (k) => (k.nguong == null ? '–' : `${k.chieu === 'min' ? '≥' : '≤'} ${fmtKpi({ ...k, gia_tri: k.nguong })}`)

export function DashboardPage() {
  const me = useMe()
  const company = !me.ma_npp
  const [npp, setNpp] = useState('')
  const [cap, setCap] = useState('npp')
  const [range, setRange] = useState({ tu: '', den: '' })
  const qs = new URLSearchParams({ ...(npp && { ma_npp: npp }) }).toString()
  const dash = useApi(`/ph4/dashboard${qs ? `?${qs}` : ''}`)
  const dq = new URLSearchParams({ cap, ...(npp && { ma_npp: npp }), ...(range.tu && { tu: range.tu }), ...(range.den && { den: range.den }) })
  const drill = useApi(`/ph4/dashboard/drill?${dq}`)
  const [run, busy] = useAction()

  const refresh = async () => {
    const ok = await run(async () => {
      await post('/ph0/scheduler/run/ph4.nap_kho_du_lieu')
      return post('/ph0/scheduler/run/ph4.tinh_kpi')
    }, 'Đã nạp kho dữ liệu và tính lại KPI')
    if (ok) { dash.reload(); drill.reload() }
  }

  return (
    <Page title="Dashboard KPI" sub="PH4 CN5 – chỉ số của 4 phân hệ từ kho dữ liệu; cảnh báo khi vượt ngưỡng. Lịch sử bán hàng là dữ liệu mô phỏng"
          actions={<>
            {company && (
              <select aria-label="Phạm vi" value={npp} onChange={(e) => setNpp(e.target.value)}>
                <option value="">Toàn công ty</option><option value="NPP01">NPP01</option><option value="NPP02">NPP02</option>
              </select>
            )}
            {me.vai_tro === 'admin' && <Btn kind="ghost" busy={busy} onClick={refresh}>Nạp dữ liệu & tính KPI</Btn>}
            <Btn kind="ghost" onClick={() => { dash.reload(); drill.reload() }}>Tải lại</Btn>
          </>}>
      <Loading q={dash}>
        {(d) => {
          const breaches = d.kpi.filter((k) => k.vuot_nguong)
          const c = d.chi_so_chinh
          return (
            <>
              <div className="grid-stats">
                <Stat label="Điểm bán hoạt động 30 ngày" value={num(c.diem_ban_hoat_dong_30_ngay)} />
                <Stat label="Điểm bán tự đặt 7 ngày" value={c.diem_ban_tu_dat_7_ngay} />
                <Stat label="Tỷ lệ đơn tự đặt (KPI6)" value={pct(c.ty_le_don_tu_dat)} />
                <Stat label="Tỷ lệ ghé đúng tuyến" value={pct(c.ty_le_ghe_dung_tuyen)} />
                <Stat label="KPI vượt ngưỡng" value={breaches.length}
                      sub={breaches.length ? <Badge kind="bad">Cần xử lý</Badge> : <Badge kind="good">Tất cả trong ngưỡng</Badge>} />
              </div>
              {breaches.length > 0 && (
                <div className="notice notice-bad">
                  <strong>⚠ Vượt ngưỡng:</strong> {breaches.map((k) => `${kpiName(k)} (${fmtKpi(k)}, ngưỡng ${fmtTarget(k)})`).join(' · ')}
                </div>
              )}
              <div className="grid-kpi">
                {Object.keys(PHAN_HE).map((ph) => (
                  <Card key={ph} title={PHAN_HE[ph]}>
                    <Table rows={d.kpi.filter((k) => k.phan_he === ph)} rowKey={(k) => k.ma_kpi} cols={[
                      { label: 'Chỉ số', render: kpiName },
                      { label: 'Giá trị', num: true, render: fmtKpi },
                      { label: 'Ngưỡng', num: true, render: fmtTarget },
                      { label: '', render: (k) => k.gia_tri == null ? <Badge kind="muted">Chưa có dữ liệu</Badge>
                        : k.nguong == null ? null
                          : k.vuot_nguong ? <Badge kind="bad">Vượt ngưỡng</Badge> : <Badge kind="good">Đạt</Badge> },
                    ]} />
                  </Card>
                ))}
              </div>
            </>
          )
        }}
      </Loading>

      <Card title="Khoan xuống doanh số">
        <div className="form-row">
          <Tabs tabs={DRILL} value={cap} onChange={setCap} />
          <Field label="Từ ngày"><input type="date" value={range.tu} onChange={(e) => setRange({ ...range, tu: e.target.value })} /></Field>
          <Field label="Đến ngày"><input type="date" value={range.den} onChange={(e) => setRange({ ...range, den: e.target.value })} /></Field>
        </div>
        <p className="muted" style={{ fontSize: 12 }}>Mặc định từ đầu tháng đến hôm nay.</p>
        <Loading q={drill} empty="Không có dữ liệu trong khoảng này">
          {(rows) => cap === 'nvbh'
            ? <BarChart rows={rows} label={(r) => r.ma_nvbh} value={(r) => r.so_luot_ghe} valueLabel="Số lượt ghé" format={(v) => num(v)} />
            : <BarChart rows={rows} label={(r) => r[cap]} value={(r) => r.doanh_thu} valueLabel="Doanh thu"
                        format={(v) => (v >= 1e6 ? `${num(v / 1e6, 1)} tr` : num(v))} max={15} />}
        </Loading>
      </Card>
    </Page>
  )
}
