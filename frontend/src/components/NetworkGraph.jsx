import { useMemo, useState } from 'react'

/**
 * Payment graph — a readable 3-column layout (customers · devices · merchants)
 * rather than a force blob, so it stays legible in a demo. Edges are drawn as
 * soft curves; flagged nodes are highlighted; click selects.
 */
const COL = { customer: 0, device: 1, merchant: 2 }
const STATE_FILL = {
  normal: 'var(--surface-sunken)',
  suspicious: 'var(--warn)',
  high: 'var(--danger)',
}

export function NetworkGraph({ data, selected, onSelect }) {
  const [hover, setHover] = useState(null)
  const W = 760
  const colX = [120, W / 2, W - 120]

  const layout = useMemo(() => {
    if (!data?.nodes?.length) return { nodes: [], edges: [], H: 200 }
    const byCol = { customer: [], device: [], merchant: [] }
    for (const n of data.nodes) if (byCol[n.type]) byCol[n.type].push(n)
    for (const k of Object.keys(byCol)) byCol[k].sort((a, b) => (b.degree || 0) - (a.degree || 0))
    const maxLen = Math.max(1, ...Object.values(byCol).map((a) => a.length))
    const gap = 34
    const H = Math.max(240, maxLen * gap + 40)
    const pos = {}
    for (const [type, arr] of Object.entries(byCol)) {
      const top = (H - (arr.length - 1) * gap) / 2
      arr.forEach((n, i) => { pos[n.id] = { x: colX[COL[type]], y: top + i * gap, node: n } })
    }
    const nodes = Object.values(pos)
    const edges = (data.edges || [])
      .map((e) => ({ ...e, a: pos[e.source], b: pos[e.target] }))
      .filter((e) => e.a && e.b)
    return { nodes, edges, H }
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  const nbrs = useMemo(() => {
    const m = new Set()
    if (!selected) return m
    for (const e of layout.edges) {
      if (e.source === selected) m.add(e.target)
      if (e.target === selected) m.add(e.source)
    }
    return m
  }, [selected, layout.edges])

  if (!layout.nodes.length) return null
  const active = (id) => selected === id || hover === id

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${layout.H}`} width="100%" style={{ minWidth: 560, display: 'block' }}>
        {['Customers', 'Devices', 'Merchants'].map((t, i) => (
          <text key={t} x={colX[i]} y={16} textAnchor="middle"
            style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', fill: 'var(--ink-muted)' }}>{t}</text>
        ))}
        {layout.edges.map((e, i) => {
          const dim = selected && !(e.source === selected || e.target === selected)
          const mx = (e.a.x + e.b.x) / 2
          return (
            <path key={i}
              d={`M${e.a.x} ${e.a.y} C ${mx} ${e.a.y}, ${mx} ${e.b.y}, ${e.b.x} ${e.b.y}`}
              fill="none" stroke="var(--border-strong)" strokeWidth={dim ? 0.6 : 1}
              opacity={dim ? 0.3 : 0.75} />
          )
        })}
        {layout.nodes.map(({ x, y, node }) => {
          const r = node.type === 'device' ? 8 : 6.5
          const dim = selected && selected !== node.id && !nbrs.has(node.id)
          const fill = STATE_FILL[node.state] || STATE_FILL.normal
          return (
            <g key={node.id} transform={`translate(${x} ${y})`} style={{ cursor: 'pointer' }}
              opacity={dim ? 0.35 : 1}
              onMouseEnter={() => setHover(node.id)} onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(node)}>
              <circle r={active(node.id) ? r + 3 : r} fill={fill}
                stroke={active(node.id) ? 'var(--accent)' : 'var(--border-strong)'}
                strokeWidth={active(node.id) ? 2 : 1} />
              <text x={node.type === 'merchant' ? 12 : node.type === 'customer' ? -12 : 0}
                y={node.type === 'device' ? -12 : 3}
                textAnchor={node.type === 'merchant' ? 'start' : node.type === 'customer' ? 'end' : 'middle'}
                style={{ fontSize: 9.5, fill: active(node.id) ? 'var(--ink)' : 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                {node.ref}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
