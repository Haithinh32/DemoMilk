import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { get } from './api.js'

// ---- Dữ liệu --------------------------------------------------------------------------------

export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path })
  const seq = useRef(0)
  const load = useCallback(async () => {
    if (!path) return
    const n = ++seq.current
    setState((s) => ({ ...s, loading: true }))
    try {
      const data = await get(path)
      if (n === seq.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (n === seq.current) setState({ data: null, error, loading: false })
    }
  }, [path, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [load])
  return { ...state, reload: load }
}

// ---- Thông báo nổi --------------------------------------------------------------------------

const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((msg, kind = 'ok') => {
    const id = Math.random()
    setItems((x) => [...x, { id, msg, kind }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === 'err' ? 7000 : 3500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <span aria-hidden>{t.kind === 'err' ? '✕' : '✓'}</span> {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/** Chạy một thao tác ghi: khóa nút khi đang gửi, báo lỗi/thành công, trả kết quả. */
export function useAction() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = useCallback(async (fn, okMsg) => {
    setBusy(true)
    try {
      const r = await fn()
      if (okMsg) toast(typeof okMsg === 'function' ? okMsg(r) : okMsg)
      return r
    } catch (e) {
      toast(`${e.code ? `[${e.code}] ` : ''}${e.message}`, 'err')
      return undefined
    } finally {
      setBusy(false)
    }
  }, [toast])
  return [run, busy]
}

// ---- Định dạng ------------------------------------------------------------------------------

const nf = new Intl.NumberFormat('vi-VN')
export const money = (v) => (v == null ? '–' : `${nf.format(Math.round(v))} đ`)
export const num = (v, d = 0) => (v == null ? '–' : new Intl.NumberFormat('vi-VN', { maximumFractionDigits: d }).format(v))
export const pct = (v, d = 1) => (v == null ? '–' : `${num(v * 100, d)}%`)
export const dt = (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '–')
export const day = (v) => (v ? String(v).slice(0, 10).split('-').reverse().join('/') : '–')

// ---- Trạng thái -----------------------------------------------------------------------------

const ORDER_STATES = {
  CHO_KIEM_TRA_TD: ['Chờ kiểm tra tín dụng', 'warn'],
  CHO_DIEM_BAN_CHON: ['Chờ điểm bán chọn', 'warn'],
  CHO_DUYET_NGOAI_LE_TD: ['Chờ duyệt ngoại lệ', 'warn'],
  CHO_NPP_DUYET: ['Chờ NPP duyệt', 'warn'],
  DA_DUYET: ['Đã duyệt', 'info'],
  CHO_GIAO: ['Chờ giao', 'info'],
  DA_GIAO: ['Đã giao', 'good'],
  DA_HUY: ['Đã hủy', 'bad'],
}

const GENERIC = {
  cho_soan: ['Chờ soạn', 'warn'], da_xuat: ['Đã xuất kho', 'info'], da_giao: ['Đã giao', 'good'],
  binh_thuong: ['Bình thường', 'good'], khoa: ['Đang khóa', 'bad'],
  mo: ['Đang mở', 'warn'], da_nhan: ['Đã nhận', 'good'], dong: ['Đã đóng', 'muted'],
  de_xuat: ['Đề xuất', 'warn'], da_gui: ['Đã gửi', 'info'], da_chot: ['Đã chốt', 'good'],
  nhap: ['Nháp', 'muted'], da_duyet: ['Đã duyệt', 'good'], dung: ['Đã dừng', 'bad'], ket_thuc: ['Kết thúc', 'muted'],
  cho: ['Chờ xử lý', 'warn'], xong: ['Xong', 'good'], loi: ['Lỗi', 'bad'],
  chua_tra: ['Chưa trả', 'warn'], tra_mot_phan: ['Trả một phần', 'warn'], da_tra: ['Đã trả', 'good'],
  chap_nhan: ['Chấp nhận', 'good'], sua: ['Đã sửa', 'info'], giu_mac_dinh: ['Giữ mặc định', 'muted'],
  moi: ['Mới', 'info'], da_dat: ['Đã đặt', 'good'], het_han: ['Hết hạn', 'muted'],
  hop_le: ['Hợp lệ', 'good'], nghi_van: ['Nghi vấn', 'bad'],
  do: ['Lô đỏ', 'bad'], vang: ['Lô vàng', 'warn'], xanh: ['Còn hạn', 'good'],
}

const ICON = { good: '✓', warn: '◷', bad: '!', info: '•', muted: '–' }

export function Badge({ value, kind, children }) {
  const [label, k] = ORDER_STATES[value] || GENERIC[value] || [children || value, kind || 'muted']
  return (
    <span className={`badge badge-${kind || k}`}>
      <span aria-hidden>{ICON[kind || k]}</span> {children || label}
    </span>
  )
}

// ---- Bố cục ---------------------------------------------------------------------------------

export function Page({ title, sub, actions, children }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <p className="muted">{sub}</p>}
        </div>
        {actions && <div className="row">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Loading({ q, empty = 'Không có dữ liệu', children }) {
  if (q.loading && !q.data) return <p className="muted pad">Đang tải…</p>
  if (q.error) return <p className="error pad">{q.error.code ? `[${q.error.code}] ` : ''}{q.error.message}</p>
  if (q.data == null || (Array.isArray(q.data) && q.data.length === 0)) return <p className="muted pad">{empty}</p>
  return children(q.data)
}

export function Table({ cols, rows, rowKey, onRow, selected, empty = 'Không có dòng nào' }) {
  if (!rows?.length) return <p className="muted pad">{empty}</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c.key || c.label} className={c.num ? 'num' : ''}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const k = rowKey ? rowKey(r) : i
            return (
              <tr key={k} onClick={onRow ? () => onRow(r) : undefined}
                  className={`${onRow ? 'clickable' : ''} ${selected === k ? 'selected' : ''}`}>
                {cols.map((c) => (
                  <td key={c.key || c.label} className={c.num ? 'num' : ''}>
                    {c.render ? c.render(r) : r[c.key]}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function Btn({ kind = 'primary', busy, sm, children, ...p }) {
  return (
    <button {...p} className={`btn btn-${kind}${sm ? ' btn-sm' : ''}`} disabled={busy || p.disabled}>
      {busy ? 'Đang gửi…' : children}
    </button>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Stat({ label, value, sub }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Json({ value }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, label]) => (
        <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'tab active' : 'tab'}
                onClick={() => onChange(k)}>{label}</button>
      ))}
    </div>
  )
}
