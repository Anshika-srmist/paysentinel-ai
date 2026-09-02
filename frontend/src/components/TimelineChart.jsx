/**
 * Decisions over time. One bar per time bucket: the flagged (VERIFY/HOLD)
 * share at the base in terracotta, the rest in pine. 2px surface gap
 * between the two segments. Hover shows the bucket's counts.
 */
import { useState } from 'react'

export function TimelineChart({ buckets = [], height = 132 }) {
  const [hover, setHover] = useState(null)
  if (buckets.length < 2) {
    return <div className="muted" style={{ fontSize: 12, padding: '24px 0', textAlign: 'center' }}>Not enough history yet.</div>
  }
  const max = Math.max(...buckets.map((b) => b.total), 1)
  const gap = 3
  const w = 100 / buckets.length

  const fmt = (d) => new Date(d.endsWith?.('Z') || d.includes?.('+') ? d : `${d}Z`)
    .toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
        {buckets.map((b, i) => {
          const x = i * w
          const totalH = (b.total / max) * (height - 4)
          const riskH = (b.high_risk / max) * (height - 4)
          const safeH = Math.max(0, totalH - riskH - (riskH > 0 ? 2 : 0))
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x} y={0} width={w} height={height} fill="transparent" />
              {safeH > 0 && (
                <rect x={x + gap / 2} width={w - gap} y={height - totalH} height={safeH}
                  rx="1" fill="var(--ok-bar)" opacity={hover === null || hover === i ? 1 : 0.5} />
              )}
              {riskH > 0 && (
                <rect x={x + gap / 2} width={w - gap} y={height - riskH} height={riskH}
                  rx="1" fill="var(--danger-bar)" opacity={hover === null || hover === i ? 1 : 0.5} />
              )}
            </g>
          )
        })}
      </svg>
      {hover !== null && (
        <div className="chart-tip" style={{ left: `${(hover + 0.5) * w}%` }}>
          <b>{buckets[hover].total}</b> decisions
          {buckets[hover].high_risk > 0 && <> · <span style={{ color: 'var(--danger)' }}>{buckets[hover].high_risk} flagged</span></>}
          <div className="muted">{fmt(buckets[hover].start)}</div>
        </div>
      )}
    </div>
  )
}
