import { useEffect, useRef, useState } from 'react'
import { Table } from './ui.jsx'

/**
 * Biểu đồ thanh ngang một chuỗi số liệu (độ lớn): một màu, sắp giảm dần, nhãn giá trị ở đầu thanh,
 * tooltip khi rê chuột, có nút xem dạng bảng.
 */
export function BarChart({ rows, label, value, format = String, title, valueLabel = 'Giá trị', max = 12 }) {
  const [hover, setHover] = useState(null)
  const [asTable, setAsTable] = useState(false)
  const box = useRef(null)
  const [width, setWidth] = useState(640)
  useEffect(() => {
    if (!box.current) return undefined
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [asTable, rows.length])
  const data = [...rows].sort((a, b) => value(b) - value(a)).slice(0, max)
  if (!data.length) return <p className="muted">Không có dữ liệu.</p>

  // Vẽ theo đúng số điểm ảnh của khung để chữ luôn 12px, không bị phóng/thu theo viewBox
  const W = Math.max(280, width), labelW = Math.min(170, Math.round(W * 0.28)), valueW = 76, barH = 18, gap = 10, top = 4
  const plotW = W - labelW - valueW
  const H = top + data.length * (barH + gap)
  const vmax = Math.max(...data.map(value), 0) || 1
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * vmax)
  const x = (v) => labelW + (Math.max(0, v) / vmax) * plotW

  // Thanh bo tròn 4px ở đầu dữ liệu, góc vuông ở đường gốc
  const bar = (w, y) => {
    const r = Math.min(4, w / 2, barH / 2)
    return `M${labelW},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${barH - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - r)} z`
  }

  return (
    <div className="stack">
      <div className="row">
        {title && <strong>{title}</strong>}
        <button className="btn btn-ghost btn-sm right" onClick={() => setAsTable((v) => !v)}>{asTable ? 'Xem biểu đồ' : 'Xem bảng'}</button>
      </div>
      {asTable ? (
        <Table rows={data} cols={[{ label: '', render: label }, { label: valueLabel, num: true, render: (r) => format(value(r)) }]} />
      ) : (
        <div className="chart" ref={box} onMouseLeave={() => setHover(null)}>
          <svg width={W} height={H + 20} viewBox={`0 0 ${W} ${H + 20}`} role="img" aria-label={title || valueLabel}>
            <g className="grid">
              {ticks.slice(1).map((t) => <line key={t} x1={x(t)} x2={x(t)} y1={0} y2={H} />)}
            </g>
            {data.map((r, i) => {
              const y = top + i * (barH + gap)
              const w = Math.max(1, x(value(r)) - labelW)
              return (
                <g key={i} className="bar-row"
                   onMouseMove={(e) => {
                     const box = e.currentTarget.ownerSVGElement.getBoundingClientRect()
                     setHover({ r, left: e.clientX - box.left, top: e.clientY - box.top })
                   }}>
                  <rect className="bar-hit" x={0} y={y - gap / 2} width={W} height={barH + gap} />
                  <text className="axis-label" x={labelW - 8} y={y + barH / 2 + 4} textAnchor="end">{label(r)}</text>
                  <path className="bar" d={bar(w, y)} />
                  <text className="value-label" x={labelW + w + 6} y={y + barH / 2 + 4}>{format(value(r))}</text>
                </g>
              )
            })}
            <line className="baseline" x1={labelW} x2={labelW} y1={0} y2={H} />
            {ticks.map((t) => (
              <text key={t} className="axis-label" x={x(t)} y={H + 14} textAnchor="middle" style={{ fontSize: 11 }}>{format(t)}</text>
            ))}
          </svg>
          {hover && (
            <div className="tooltip" style={{ left: hover.left, top: hover.top }}>
              <strong>{label(hover.r)}</strong><br />{valueLabel}: {format(value(hover.r))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
