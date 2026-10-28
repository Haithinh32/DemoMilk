import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { api, newKey, post } from '../api.js'
import { useMe } from '../auth.js'
import { Badge, Btn, Card, Field, Json, Loading, Page, Stat, Table, day, dt, money, pct, useAction, useApi, useToast } from '../ui.jsx'
import { OrderDetail } from './orders.jsx'

// ---- PH1 CN2: đặt hàng ----------------------------------------------------------------------

export function ShopPage() {
  const me = useMe()
  return (
    <Page title="Đặt hàng" sub="PH1 CN2 – giữ tồn cả giỏ (PH2), kiểm tra tín dụng (PH3), duyệt tự động hoặc chuyển bước duyệt">
      <ShopPanel maDiemBan={me.ma_diem_ban} nguon="app" />
    </Page>
  )
}

/** Dùng chung cho điểm bán tự đặt và NVBH đặt hộ (sau khi check-in). */
export function ShopPanel({ maDiemBan, nguon }) {
  const toast = useToast()
  const cat = useApi(`/ph1/catalog/${maDiemBan}`)
  const [qty, setQty] = useState({})
  const [suggest, setSuggest] = useState(null)
  const [discount, setDiscount] = useState(0)
  const [key, setKey] = useState(newKey)
  const [busy, setBusy] = useState(false)
  const [shortage, setShortage] = useState(null)
  const [placed, setPlaced] = useState(null)

  const lines = Object.entries(qty).filter(([, v]) => v > 0).map(([ma_sp, so_luong]) => ({ ma_sp, so_luong }))
  const subtotal = useMemo(() => {
    const price = Object.fromEntries((cat.data || []).map((p) => [p.ma_sp, p.don_gia]))
    return lines.reduce((s, l) => s + (price[l.ma_sp] || 0) * l.so_luong, 0)
  }, [cat.data, lines])

  const setLine = (ma, v) => { setQty((q) => ({ ...q, [ma]: Math.max(0, Number(v) || 0) })); setKey(newKey()) }

  const loadSuggestion = async () => {
    try {
      const r = await api(`/ph1/cart/from-suggestion/${maDiemBan}`)
      setQty(Object.fromEntries(r.dong.map((d) => [d.ma_sp, d.so_luong])))
      setSuggest(r)
      setKey(newKey())
      toast(`Đã nạp đơn gợi ý ${r.ma_goi_y}`)
    } catch (e) {
      toast(e.code === 'KHONG_TIM_THAY' || e.status === 404
        ? 'Chưa có đơn gợi ý hôm nay – quản trị chạy tác vụ ph4.nc1_goi_y_don ở trang Hệ thống'
        : e.message, 'err')
    }
  }

  const submit = async () => {
    setBusy(true)
    setShortage(null)
    try {
      // Cùng một khóa chống trùng cho mọi lần gửi lại của cùng giỏ hàng
      const o = await post('/ph1/orders', {
        ma_diem_ban: maDiemBan, dong: lines, khoa_chong_trung: key, nguon: suggest ? 'goi_y' : nguon,
        ma_goi_y: suggest?.ma_goi_y || null, yc_chiet_khau_pct: Number(discount) || 0,
      })
      setPlaced(o.ma_don)
      setQty({}); setSuggest(null); setDiscount(0); setKey(newKey())
      cat.reload()
      toast(`Đã tạo đơn ${o.ma_don}`)
    } catch (e) {
      if (e.code === 'THIEU_HANG') {
        setShortage(e.data)
        setQty(Object.fromEntries((e.data.gio_cap_nhat || []).map((d) => [d.ma_sp, d.so_luong])))
        setKey(newKey())
        cat.reload()
      } else {
        toast(`${e.code ? `[${e.code}] ` : ''}${e.message}`, 'err')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid-2">
      <Card title={`Sản phẩm – ${maDiemBan}`} actions={<Btn kind="ghost" sm onClick={loadSuggestion}>Dùng đơn gợi ý (PH4 NC1)</Btn>}>
        <Loading q={cat}>
          {(rows) => (
            <Table rows={rows} rowKey={(r) => r.ma_sp} cols={[
              { label: 'Sản phẩm', render: (r) => <><strong>{r.ma_sp}</strong><br /><span className="muted" style={{ fontSize: 12 }}>{r.ten}</span></> },
              { label: 'Giá/thùng', num: true, render: (r) => <>{money(r.don_gia)}{r.km && <><br /><Badge kind="info">KM −{pct(r.muc_giam, 0)}</Badge></>}</> },
              { label: 'Tồn', num: true, render: (r) => r.het_hang ? <Badge kind="bad">Hết hàng</Badge> : r.ton_kha_dung },
              { label: 'Số thùng', num: true, render: (r) => (
                <input type="number" min="0" max={r.so_luong_toi_da} disabled={r.het_hang} aria-label={`Số thùng ${r.ma_sp}`}
                       value={qty[r.ma_sp] || ''} onChange={(e) => setLine(r.ma_sp, e.target.value)} />
              ) },
            ]} />
          )}
        </Loading>
        {suggest && (
          <div className="notice">
            Đơn gợi ý <span className="mono">{suggest.ma_goi_y}</span> đã lọc theo tồn khả dụng của PH2.
            Lý do: {[...new Set(suggest.dong.map((d) => d.ly_do))].join(', ')}
          </div>
        )}
      </Card>

      <div className="stack">
        <Card title="Giỏ hàng">
          {lines.length === 0 ? <p className="muted">Chưa chọn sản phẩm.</p> : (
            <Table rows={lines} rowKey={(l) => l.ma_sp} cols={[
              { label: 'Sản phẩm', key: 'ma_sp' }, { label: 'Số thùng', key: 'so_luong', num: true },
            ]} />
          )}
          <Field label="Đề nghị chiết khấu thêm (%)" hint="> 0 là ngoại lệ chính sách: đơn chuyển chủ NPP duyệt">
            <input type="number" min="0" max="20" step="0.5" value={discount} onChange={(e) => { setDiscount(e.target.value); setKey(newKey()) }} />
          </Field>
          <div className="row">
            <span>Tạm tính (trước KM): <strong>{money(subtotal)}</strong></span>
            <span className="right"><Btn busy={busy} disabled={!lines.length} onClick={submit}>Đặt hàng</Btn></span>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Đơn trên 20 triệu chuyển chủ NPP duyệt. Khuyến mãi và hạn mức được tính lại ở máy chủ khi đặt.
          </p>
          {shortage && (
            <div className="notice notice-warn">
              Tồn vừa thay đổi nên đơn <strong>chưa được tạo</strong>. Giỏ đã được giảm theo tồn khả dụng mới – kiểm tra rồi bấm Đặt hàng lại.
            </div>
          )}
        </Card>
        {placed && <OrderDetail ma={placed} onChange={cat.reload} />}
      </div>
    </div>
  )
}

// ---- PH3: công nợ, VietQR -------------------------------------------------------------------

export function DebtPage() {
  const me = useMe()
  const ma = me.ma_diem_ban
  const debt = useApi(`/ph3/debt/${ma}`)
  const points = useApi(`/ph4/points/${ma}`)
  const lots = useApi(`/ph2/outlets/${ma}/lots`)
  const notes = useApi('/ph0/notifications?limit=15')
  const [inv, setInv] = useState(null)
  const reloadAll = () => { debt.reload(); notes.reload() }

  return (
    <Page title="Công nợ & thanh toán" sub="PH3 CN1 hạn mức · CN3 thanh toán VietQR, gạch nợ tự động · PH4 điểm thưởng"
          actions={<Btn kind="ghost" onClick={reloadAll}>Tải lại</Btn>}>
      <Loading q={debt}>
        {(d) => (
          <>
            <div className="grid-stats">
              <Stat label="Hạn mức" value={money(d.han_muc)} sub={d.mua_chiu ? `Kỳ hạn ${d.ky_han_ngay} ngày` : 'Không mua chịu'} />
              <Stat label="Dư nợ" value={money(d.du_no)} />
              <Stat label="Nợ quá hạn" value={money(d.qua_han)} sub={d.qua_han > 0 ? 'Đơn mới phải trả tiền khi nhận (BR-02)' : 'Không có'} />
              <Stat label="Đang giữ cho đơn chờ giao" value={money(d.dang_giu)} />
              <Stat label="Hạn mức còn lại" value={money(d.han_muc_con_lai)} />
              <Loading q={points}>{(p) => <Stat label="Điểm thưởng" value={p.diem} sub={`Hạng ${p.hang}`} />}</Loading>
            </div>
            <div className="grid-2">
              <Card title="Hóa đơn còn nợ">
                <Table rows={d.hoa_don_mo} rowKey={(r) => r.so_hoa_don} selected={inv} onRow={(r) => setInv(r.so_hoa_don)}
                       empty="Không có hóa đơn còn nợ" cols={[
                  { label: 'Số hóa đơn', render: (r) => <span className="mono">{r.so_hoa_don}</span> },
                  { label: 'Còn lại', num: true, render: (r) => money(r.con_lai) },
                  { label: 'Hạn trả', render: (r) => day(r.han_tra) },
                  { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
                ]} />
              </Card>
              {inv ? <QrPanel soHoaDon={inv} onPaid={() => { setInv(null); reloadAll() }} />
                : <Card><p className="muted">Chọn một hóa đơn để thanh toán bằng VietQR.</p></Card>}
            </div>
          </>
        )}
      </Loading>
      <div className="grid-2">
        <Card title="Lô đã nhận (truy xuất ngược – PH2 CN5)">
          <Loading q={lots}>
            {(l) => <Table rows={l.lo_da_nhan} empty="Chưa nhận lô nào" cols={Object.keys(l.lo_da_nhan[0] || {}).map((k) => ({ label: k, key: k }))} />}
          </Loading>
        </Card>
        <Card title="Thông báo">
          <Loading q={notes} empty="Chưa có thông báo">
            {(rows) => <Table rows={rows} cols={[
              { label: 'Lúc', render: (r) => dt(r.luc) }, { label: 'Kênh', key: 'kenh' },
              { label: 'Nội dung', render: (r) => <><strong>{r.tieu_de}</strong> – {r.noi_dung}</> },
            ]} />}
          </Loading>
        </Card>
      </div>
    </Page>
  )
}

function QrPanel({ soHoaDon, onPaid }) {
  const q = useApi(`/ph3/qr/${soHoaDon}`)
  const [img, setImg] = useState(null)
  const [run, busy] = useAction()
  const [result, setResult] = useState(null)
  useEffect(() => {
    if (q.data?.qr) QRCode.toDataURL(q.data.qr, { margin: 1, width: 360 }).then(setImg)
  }, [q.data])

  const pay = async (noi_dung) => {
    const r = await run(() => post('/ph3/bank/simulate', { so_tai_khoan: q.data.so_tai_khoan, so_tien: q.data.so_tien, noi_dung }),
      (x) => (x.trang_thai === 'da_gach_no' ? 'Ngân hàng báo có – đã gạch nợ tự động' : 'Báo có không khớp hóa đơn – chuyển kế toán xử lý'))
    if (r) { setResult(r); setTimeout(onPaid, 1200) }
  }

  return (
    <Card title={`Thanh toán ${soHoaDon}`}>
      <Loading q={q}>
        {(d) => (
          <div className="stack">
            <div className="row" style={{ alignItems: 'flex-start' }}>
              {img && <img className="qr" src={img} alt={`Mã VietQR cho hóa đơn ${soHoaDon}`} />}
              <div className="stack">
                <div>Số tài khoản NPP: <strong className="mono">{d.so_tai_khoan}</strong></div>
                <div>Số tiền: <strong>{money(d.so_tien)}</strong></div>
                <div>Nội dung: <strong className="mono">{d.noi_dung}</strong></div>
              </div>
            </div>
            <div className="notice">
              Bản mẫu không nối ngân hàng thật. Hai nút dưới đóng vai ngân hàng gửi báo có qua đúng luồng webhook của PH3.
            </div>
            <div className="row">
              <Btn busy={busy} onClick={() => pay(d.noi_dung)}>Mô phỏng: chuyển khoản đúng nội dung</Btn>
              <Btn kind="ghost" busy={busy} onClick={() => pay('chuyen tien hang')}>Chuyển khoản ghi sai nội dung</Btn>
            </div>
            {result && <Json value={result} />}
          </div>
        )}
      </Loading>
    </Card>
  )
}

// ---- PH0: agent Zalo OA ---------------------------------------------------------------------

const TOOLS = [
  ['xem_ton_kho', 'Xem tồn kho', {}],
  ['xem_goi_y_don', 'Xem đơn gợi ý', {}],
  ['xem_trang_thai_don', 'Trạng thái đơn', {}],
  ['xem_cong_no', 'Xem công nợ', {}],
  ['tao_don_nhap', 'Tạo đơn nháp (2 thùng SP01)', { dong: [{ ma_sp: 'SP01', so_luong: 2 }] }],
]

export function ZaloPage() {
  const me = useMe()
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [toolOut, setToolOut] = useState(null)
  const drafts = useApi('/ph1/agent-drafts')
  const [run, busy] = useAction()

  const send = async (e) => {
    e.preventDefault()
    if (!text.trim()) return
    const m = text
    setMsgs((x) => [...x, { me: true, text: m }])
    setText('')
    setSending(true)
    try {
      const r = await post('/ph0/agent/zalo', { zalo_id: me.zalo_id, tin_nhan: m })
      setMsgs((x) => [...x, { me: false, text: r.tra_loi, tools: r.cong_cu }])
      drafts.reload()
    } catch (err) {
      setMsgs((x) => [...x, { me: false, text: `⚠ ${err.message}`, error: true }])
    } finally {
      setSending(false)
    }
  }

  const callTool = async (ten, body) => {
    const r = await run(() => api(`/ph0/agent/tools/${ten}?zalo_id=${encodeURIComponent(me.zalo_id)}`, { method: 'POST', body }))
    if (r) { setToolOut({ ten, r }); drafts.reload() }
  }

  const confirm = async (ma) => {
    const r = await run(() => post(`/ph1/agent-drafts/${ma}/confirm`), (o) => `Đã đặt đơn ${o.ma_don} từ đơn nháp`)
    if (r) drafts.reload()
  }

  return (
    <Page title="Zalo OA – trợ lý đặt hàng" sub={`Agent chỉ thấy dữ liệu của ${me.ma_diem_ban} (xác định từ zalo_id ${me.zalo_id} ở máy chủ) và chỉ tạo được đơn nháp`}>
      <div className="grid-2">
        <Card title="Trò chuyện">
          <div className="chat">
            {msgs.length === 0 && <p className="muted">Thử: “Còn sữa tươi không?”, “Tôi còn nợ bao nhiêu?”, “Đặt 3 thùng SP02”.</p>}
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.me ? 'msg-me' : 'msg-bot'}`}>
                {m.text}
                {m.tools?.length > 0 && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>công cụ: {m.tools.join(', ')}</div>}
              </div>
            ))}
            {sending && <div className="msg msg-bot muted">Đang trả lời…</div>}
          </div>
          <form className="row" onSubmit={send}>
            <input style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Nhắn tin cho Cao Sơn Milk…" aria-label="Tin nhắn" />
            <Btn busy={sending} type="submit">Gửi</Btn>
          </form>
          <p className="muted" style={{ fontSize: 12 }}>Cần ANTHROPIC_API_KEY ở máy chủ; chưa có thì máy chủ trả lỗi 503 kèm lý do.</p>
        </Card>
        <div className="stack">
          <Card title="Đơn nháp chờ xác nhận">
            <Loading q={drafts} empty="Chưa có đơn nháp">
              {(rows) => <Table rows={rows} rowKey={(r) => r.ma_nhap} cols={[
                { label: 'Mã nháp', render: (r) => <span className="mono">{r.ma_nhap}</span> },
                { label: 'Dòng', render: (r) => r.dong.map((d) => `${d.ma_sp}×${d.so_luong}`).join(', ') },
                { label: 'Hạn', render: (r) => dt(r.han) },
                { label: 'Trạng thái', render: (r) => r.ma_don ? <span className="mono">{r.ma_don}</span> : <Badge value={r.trang_thai} /> },
                { label: '', render: (r) => r.trang_thai === 'moi' && <Btn sm busy={busy} onClick={() => confirm(r.ma_nhap)}>Xác nhận đặt</Btn> },
              ]} />}
            </Loading>
          </Card>
          <Card title="Gọi thẳng công cụ của agent (không qua LLM)">
            <div className="row">
              {TOOLS.map(([ten, label, body]) => <Btn key={ten} kind="ghost" sm busy={busy} onClick={() => callTool(ten, body)}>{label}</Btn>)}
            </div>
            {toolOut && <><div className="muted">{toolOut.ten}</div><Json value={toolOut.r} /></>}
          </Card>
        </div>
      </div>
    </Page>
  )
}
