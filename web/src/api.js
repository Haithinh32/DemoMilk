// Gọi API FastAPI qua tiền tố /api (Vite proxy khi dev, nginx khi chạy Docker).
const KEY = 'csm_token'

function readToken() {
  try { return localStorage.getItem(KEY) } catch { return null }
}

let token = readToken()

export function getToken() { return token }

export function setToken(t) {
  token = t
  try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY) } catch { /* trình duyệt chặn lưu trữ */ }
}

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message)
    this.status = status
    this.code = code
    this.data = data || {}
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  const text = await res.text()
  let json = null
  try { json = text ? JSON.parse(text) : null } catch { /* không phải JSON */ }
  if (!res.ok) {
    if (json?.error) throw new ApiError(res.status, json.error.code, json.error.message, json.error.data)
    if (Array.isArray(json?.detail)) {
      const msg = json.detail.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ')
      throw new ApiError(res.status, 'DU_LIEU_SAI', msg)
    }
    throw new ApiError(res.status, 'LOI', text || res.statusText)
  }
  return json
}

export const get = (path) => api(path)
export const post = (path, body = {}) => api(path, { method: 'POST', body })

export function newKey() {
  return (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/-/g, '')
}
