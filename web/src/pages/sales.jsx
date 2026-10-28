import { useState } from 'react'
import { get, newKey, post } from '../api.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Table, money, useApi, useToast } from '../ui.jsx'
import { ShopPanel } from './outlet.jsx'

// Dịch tọa độ ~300 m về phía bắc để giả lập check-in xa điểm bán (BR6: bán kính 100 m)
const FAR_OFFSET = 0.0027

export function RoutePage() {
  const route = useApi('/ph4/route/today')
  const [sel, setSel] = useState(null)
  const [visits, setVisits] = useState({})
  const outlet = route.data?.diem_ban.find((d) => d.ma_diem_ban === sel)

  return (
    <Page title="Tuyến hôm nay" sub="PH4 CN1 – check-in trong bán kính 100 m, ghi nhận trưng bày, hết hàng, thu nợ; chỉ đặt hộ sau check-in hợp lệ"
          actions={<Btn kind="ghost" onClick={route.reload}>Tải lại</Btn>}>
      <div className="grid-2">
        <Card title={route.data?.ma_tuyen ? `Tuyến ${route.data.ma_tuyen}` : 'Tuyến'}>
          <Loading q={route} empty="Hôm nay không có tuyến">
            {(r) => r.diem_ban.length === 0 ? <p className="muted">Hôm nay không có tuyến.</p> : (
              <Table rows={r.diem_ban} rowKey={(d) => d.ma_diem_ban} selected={sel} onRow={(d) => setSel(d.ma_diem_ban)} cols={[
                { label: '#', key: 'thu_tu', num: true },
                { label: 'Điểm bán', render: (d) => <><strong>{d.ma_diem_ban}</strong> <span className="muted">{d.ten}</span></> },
                { label: 'Thu nợ', render: (d) => d.thu_no.length ? <Badge kind="warn">{d.thu_no.length} nhiệm vụ</Badge> : '–' },
                { label: 'Lượt ghé', render: (d) => visits[d.ma_diem_ban] ? <Badge value={visits[d.ma_diem_ban].trang_thai} /> : <span className="muted">Chưa ghé</span> },
              ]} />
            )}
          </Loading>
        </Card>
        {outlet
          ? <VisitPanel key={outlet.ma_diem_ban} outlet={outlet} visit={visits[outlet.ma_diem_ban]}
                        onVisit={(v) => { setVisits((x) => ({ ...x, [outlet.ma_diem_ban]: v })); route.reload() }} />
          : <Card><p className="muted">Chọn một điểm bán trên tuyến.</p></Card>}
      </div>
      {outlet && visits[outlet.ma_diem_ban] && (
        <Card title={`Đặt hộ ${outlet.ma_diem_ban}`}>
          <ShopPanel maDiemBan={outlet.ma_diem_ban} nguon="nvbh" />
        </Card>
      )}
    </Page>
  )
}

function VisitPanel({ outlet, visit, onVisit }) {
  const toast = useToast()
  const products = useApi('/ph0/products')
  const [tries, setTries] = useState(1)
  const [reason, setReason] = useState('')
  const [outOfStock, setOutOfStock] = useState([])
  const [display, setDisplay] = useState(true)
  const [collect, setCollect] = useState({})
  const [busy, setBusy] = useState(false)
  const [lastErr, setLastErr] = useState(null)

  const checkin = async (far) => {
    setBusy(true)
    setLastErr(null)
    try {
      const { now } = await get('/ph0/clock')   // giờ máy của app = giờ máy chủ (có thể đã tua cho demo)
      const [r] = await post('/ph4/visits', [{
        ma_luot_ghe: `LG-${newKey().slice(0, 12)}`, ma_diem_ban: outlet.ma_diem_ban, thoi_gian_may: now,
        lat: outlet.lat + (far ? FAR_OFFSET : 0.00005), lng: outlet.lng, so_lan_thu: tries, ly_do_xa: reason || null,
        anh: [{ url: `s3://trung-bay/${outlet.ma_diem_ban}.jpg` }], het_hang: outOfStock, trung_bay_dat: display,
        thu_no: outlet.thu_no.filter((t) => collect[t.ma_nhiem_vu] != null)
          .map((t) => ({ ma_nhiem_vu: t.ma_nhiem_vu, so_tien_thu: Number(collect[t.ma_nhiem_vu]) || 0 })),
      }])
      if (r.loi) {
        setLastErr(r)
        if (r.loi === 'CHECK_IN_XA') setTries((n) => n + 1)
        toast(r.thong_bao, 'err')
      } else {
        onVisit(r)
        toast(r.trang_thai === 'nghi_van' ? 'Đã ghi lượt ghé – bị đánh dấu nghi vấn' : 'Check-in hợp lệ')
      }
    } catch (e) {
      toast(e.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={`${outlet.ma_diem_ban} – ${outlet.ten}`}>
      {visit ? (
        <div className="stack">
          <div className="row">
            <Badge value={visit.trang_thai} /> <span>Cách điểm bán {visit.khoang_cach_m} m</span>
            {visit.dung_tuyen ? <Badge kind="good">Đúng tuyến</Badge> : <Badge kind="warn">Ngoài tuyến</Badge>}
          </div>
          {visit.ly_do?.length > 0 && <div className="notice notice-warn">Bất thường: {visit.ly_do.join(', ')}</div>}
          <p className="muted">Đã check-in – có thể đặt hộ ở khung bên dưới.</p>
        </div>
      ) : (
        <div className="stack">
          <Field label="Sản phẩm hết hàng tại điểm bán">
            <Loading q={products}>
              {(ps) => (
                <div className="row">
                  {ps.map((p) => (
                    <label key={p.ma_sp} className="row" style={{ gap: 4 }}>
                      <input type="checkbox" checked={outOfStock.includes(p.ma_sp)}
                             onChange={(e) => setOutOfStock((x) => e.target.checked ? [...x, p.ma_sp] : x.filter((y) => y !== p.ma_sp))} />
                      {p.ma_sp}
                    </label>
                  ))}
                </div>
              )}
            </Loading>
          </Field>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={display} onChange={(e) => setDisplay(e.target.checked)} /> Trưng bày đạt chuẩn
          </label>
          {outlet.thu_no.map((t) => (
            <Field key={t.ma_nhiem_vu} label={`Thu nợ ${t.so_hoa_don} – cần thu ${money(t.so_tien)} (hạn ${t.han_tra})`}
                   hint="Nhập số tiền thu được; thu đủ thì nhiệm vụ đóng, thiếu thì ghi hẹn trả và gửi PH3">
              <input type="number" min="0" value={collect[t.ma_nhiem_vu] ?? ''} style={{ width: 160 }}
                     onChange={(e) => setCollect((x) => ({ ...x, [t.ma_nhiem_vu]: e.target.value }))} />
            </Field>
          ))}
          {tries > 3 && (
            <Field label="Lý do check-in xa" hint="Quá 3 lần thử vẫn xa hơn 100 m thì phải ghi lý do">
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="VD: điểm bán chuyển địa chỉ" />
            </Field>
          )}
          <div className="row">
            <Btn busy={busy} onClick={() => checkin(false)}>Check-in tại điểm bán</Btn>
            <Btn kind="ghost" busy={busy} onClick={() => checkin(true)}>Giả lập check-in xa ~300 m (lần {tries})</Btn>
          </div>
          {lastErr && <Json value={lastErr} />}
        </div>
      )}
    </Card>
  )
}
