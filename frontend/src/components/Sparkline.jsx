/**
 * Single-series area sparkline. One hue, no axes, no legend (the caption
 * names it) — a "change over time" glance, not a full chart.
 */
export function Sparkline({ values = [], width = 132, height = 40, stroke = 'var(--accent)' }) {
  if (values.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />
  }
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const stepX = width / (values.length - 1)
  const pt = (v, i) => [i * stepX, height - 3 - ((v - min) / span) * (height - 6)]
  const pts = values.map(pt)
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  const area = `${line} L${width} ${height} L0 ${height} Z`
  const gid = `sl-${Math.random().toString(36).slice(2, 8)}`
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="trend">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.20" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.6" fill={stroke} />
    </svg>
  )
}
