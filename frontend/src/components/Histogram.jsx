/**
 * Risk-score distribution — 10 bins [0,0.1)…[0.9,1.0], each coloured by its
 * risk band (low = pine, mid = gold, high = terracotta), so the shape of the
 * book is legible at a glance. Per-bar hover.
 */
import { useState } from 'react'

const bandColor = (lo) => (lo >= 0.9 ? 'var(--danger-bar)' : lo >= 0.3 ? 'var(--warn-bar)' : 'var(--ok-bar)')

export function Histogram({ bins = [], height = 128 }) {
  const [hover, setHover] = useState(null)
  if (!bins.length) return null
  const max = Math.max(...bins.map((b) => b.count), 1)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height }}>
        {bins.map((b, i) => (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <div style={{ fontSize: 10.5, textAlign: 'center', color: 'var(--ink-muted)', marginBottom: 4, height: 13 }}>
              {hover === i ? b.count : ''}
            </div>
            <div style={{
              height: `${(b.count / max) * 100}%`, minHeight: b.count ? 3 : 0,
              background: bandColor(b.lo), borderRadius: '3px 3px 0 0',
              opacity: hover === null || hover === i ? 1 : 0.55,
              transition: 'opacity 120ms ease',
            }} />
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
        {bins.map((b, i) => (
          <div key={i} style={{ flex: 1, fontSize: 10, textAlign: 'center', color: 'var(--ink-muted)', fontVariantNumeric: 'tabular-nums' }}>
            {i % 2 === 0 ? b.lo.toFixed(1) : ''}
          </div>
        ))}
      </div>
    </div>
  )
}
