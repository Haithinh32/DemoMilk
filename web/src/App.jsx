import { useCallback, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { get, getToken, setToken } from './api.js'
import { AuthCtx } from './auth.js'
import { dt } from './ui.jsx'
import { ACCOUNTS, Login } from './pages/Login.jsx'
import { DebtPage, ShopPage, ZaloPage } from './pages/outlet.jsx'
import { OrdersPage } from './pages/orders.jsx'
import { RoutePage } from './pages/sales.jsx'
import { ReplenishmentPage } from './pages/npp.jsx'
import { DeliveryPage, PickListsPage, RecallTasksPage } from './pages/warehouse.jsx'
import { LotsPage, RecallsPage } from './pages/lots.jsx'
import { CashPage, ExceptionsPage, HandoverPage, PaymentsPage, ReconcilePage, ScoresPage } from './pages/credit.jsx'
import { PromoNC1Page, PromotionsPage, TransfersPage } from './pages/promo.jsx'
import { DashboardPage } from './pages/dashboard.jsx'
import { SystemPage } from './pages/system.jsx'

const ROLE_NAMES = {
  diem_ban: 'Điểm bán', nvbh: 'NV bán hàng', npp: 'Chủ NPP', thu_kho: 'Thủ kho', nvgh: 'NV giao hàng',
  ke_toan: 'Kế toán NPP', ke_toan_truong: 'Kế toán trưởng', thu_quy: 'Thủ quỹ', pkd: 'Phòng kinh doanh',
  gdkd: 'Giám đốc KD', qa: 'QA công ty', bdh: 'Ban điều hành', admin: 'Quản trị',
}

// [đường dẫn, nhãn, phân hệ, component]
const P = {
  shop: ['/dat-hang', 'Đặt hàng', 'PH1', ShopPage],
  orders: ['/don-hang', 'Đơn hàng', 'PH1', OrdersPage],
  debt: ['/cong-no', 'Công nợ & thanh toán', 'PH3', DebtPage],
  zalo: ['/zalo', 'Zalo OA (agent)', 'PH0', ZaloPage],
  route: ['/tuyen', 'Tuyến hôm nay', 'PH4', RoutePage],
  replenish: ['/bo-sung', 'Đơn bổ sung NPP', 'PH1', ReplenishmentPage],
  pick: ['/soan-hang', 'Soạn & xuất kho', 'PH2', PickListsPage],
  lots: ['/lo-hang', 'Lô hàng', 'PH2', LotsPage],
  recalls: ['/thu-hoi', 'Vụ thu hồi', 'PH2', RecallsPage],
  recallTasks: ['/nhiem-vu-thu-hoi', 'Nhận hàng thu hồi', 'PH2', RecallTasksPage],
  delivery: ['/giao-hang', 'Giao hàng', 'PH2', DeliveryPage],
  cash: ['/thu-tien', 'Thu tiền mặt', 'PH3', CashPage],
  exceptions: ['/ngoai-le', 'Ngoại lệ tín dụng', 'PH3', ExceptionsPage],
  payments: ['/giao-dich-cho', 'Báo có chờ xử lý', 'PH3', PaymentsPage],
  reconcile: ['/doi-soat', 'Đối soát & khóa sổ', 'PH3', ReconcilePage],
  handover: ['/nop-quy', 'Nhận nộp quỹ', 'PH3', HandoverPage],
  scores: ['/cham-diem', 'Chấm điểm tín dụng', 'PH3', ScoresPage],
  promos: ['/khuyen-mai', 'Chương trình KM', 'PH1', PromotionsPage],
  nc1: ['/de-xuat-km', 'Đề xuất & đánh giá KM', 'PH1', PromoNC1Page],
  transfers: ['/dieu-chuyen', 'Điều chuyển lô vàng', 'PH2', TransfersPage],
  dashboard: ['/dashboard', 'Dashboard KPI', 'PH4', DashboardPage],
  system: ['/he-thong', 'Hệ thống & sự kiện', 'PH0', SystemPage],
}

const NAV = {
  diem_ban: ['shop', 'orders', 'debt', 'zalo'],
  nvbh: ['route', 'orders'],
  npp: ['orders', 'replenish', 'lots', 'dashboard'],
  thu_kho: ['pick', 'lots', 'recallTasks'],
  nvgh: ['delivery', 'cash'],
  ke_toan: ['payments', 'reconcile'],
  ke_toan_truong: ['exceptions', 'reconcile', 'payments', 'scores'],
  thu_quy: ['handover', 'reconcile'],
  pkd: ['promos', 'nc1', 'replenish', 'transfers', 'dashboard'],
  gdkd: ['promos', 'scores', 'dashboard'],
  qa: ['lots', 'recalls'],
  bdh: ['dashboard'],
  admin: ['system', 'dashboard', 'promos', 'lots'],
}

export default function App() {
  const [me, setMe] = useState(undefined)

  const login = useCallback(async (tok) => {
    setToken(tok)
    try {
      setMe(await get('/ph0/me'))
    } catch {
      setToken(null)
      setMe(null)
    }
  }, [])

  useEffect(() => {
    const t = getToken()
    if (t) login(t)
    else setMe(null)
  }, [login])

  const logout = () => { setToken(null); setMe(null) }

  if (me === undefined) return <p className="pad muted" style={{ padding: 24 }}>Đang tải…</p>
  if (!me) return <Login onLogin={login} />
  return (
    <AuthCtx.Provider value={{ me }}>
      <Shell me={me} onSwitch={login} onLogout={logout} />
    </AuthCtx.Provider>
  )
}

function Shell({ me, onSwitch, onLogout }) {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const items = (NAV[me.vai_tro] || []).map((k) => P[k])
  const current = getToken() || ''

  return (
    <div className="app">
      <aside className={`side ${open ? 'open' : ''}`}>
        <div className="brand">Cao Sơn Milk<small>B2B & quản lý phân phối</small></div>
        <div className="nav-group">{ROLE_NAMES[me.vai_tro] || me.vai_tro}</div>
        <nav className="nav">
          {items.map(([path, label, ph]) => (
            <NavLink key={path} to={path}>{label} <span className="muted" style={{ fontSize: 11 }}>{ph}</span></NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <div className="topbar">
          <button className="btn btn-ghost btn-sm menu-btn" onClick={() => setOpen(true)} aria-label="Mở menu">☰</button>
          <div>
            <strong>{me.ten}</strong>{' '}
            <span className="muted">
              · {ROLE_NAMES[me.vai_tro]}{me.ma_npp ? ` · ${me.ma_npp}` : ''}{me.ma_diem_ban ? ` · ${me.ma_diem_ban}` : ''}
            </span>
          </div>
          <div className="right row">
            <ServerClock />
            <select aria-label="Đổi vai trò" value={current} onChange={(e) => e.target.value && onSwitch(e.target.value)}>
              <option value="">Đổi vai trò…</option>
              {ACCOUNTS.map((a) => <option key={a.token} value={a.token}>{a.label}</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>Đăng xuất</button>
          </div>
        </div>
        <Routes>
          {items.map(([path, , , C]) => <Route key={path} path={`${path}/*`} element={<C />} />)}
          <Route path="*" element={<Navigate to={items[0]?.[0] || '/'} replace />} />
        </Routes>
      </div>
    </div>
  )
}

/** Giờ của máy chủ (có thể đã bị quản trị tua để demo các hạn BR-06). */
function ServerClock() {
  const [now, setNow] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = () => get('/ph0/clock').then((r) => alive && setNow(r.now)).catch(() => {})
    tick()
    const id = setInterval(tick, 15000)
    window.addEventListener('csm-clock', tick)
    return () => { alive = false; clearInterval(id); window.removeEventListener('csm-clock', tick) }
  }, [])
  return <span className="clock" title="Giờ máy chủ">🕘 {dt(now)}</span>
}
