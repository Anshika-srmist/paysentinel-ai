import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader, LiveBadge } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { Sparkline } from '../components/Sparkline.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { DECISION_ORDER, metaFor } from '../lib/decisions.js'
import { num, pct, compactMoney, money, timeAgo, shortId } from '../lib/format.js'
import './pages.css'

// Brighter fill variants for the breakdown bars (see tokens.css).
const BAR_VAR = { ok: '--ok-bar', info: '--info-bar', warn: '--warn-bar', alt: '--alt-bar', danger: '--danger-bar', muted: '--ink-muted' }

function Tile({ label, value, sub, icon, accent }) {
  return (
    <div className={`card tile ${accent ? 'tile--accent' : ''}`}>
      <span className="tile__ico"><Icon name={icon} size={16} /></span>
      <div className="tile__label">{label}</div>
      <div className="tile__value tnum">{value}</div>
      {sub && <div className="tile__sub">{sub}</div>}
    </div>
  )
}

export function Overview() {
  const stats = usePolling((signal) => api.stats({ signal }), 5000)
  const feed = usePolling((signal) => api.decisions({ limit: 60, signal }), 5000)

  const s = stats.data
  const decisions = feed.data || []

  const breakdown = useMemo(() => {
    const by = s?.decisions_by_action || {}
    const total = Object.values(by).reduce((a, b) => a + b, 0)
    const max = Math.max(1, ...Object.values(by))
    return DECISION_ORDER.map((key) => ({
      key,
      meta: metaFor(key),
      count: by[key] || 0,
      widthPct: ((by[key] || 0) / max) * 100,
      sharePct: total ? (by[key] || 0) / total : 0,
    }))
  }, [s])

  const spark = useMemo(() => {
    if (decisions.length < 4) return []
    const sorted = [...decisions].reverse() // oldest -> newest
    const bins = 12
    const size = Math.ceil(sorted.length / bins)
    const out = []
    for (let i = 0; i < sorted.length; i += size) out.push(sorted.slice(i, i + size).length)
    return out
  }, [decisions])

  const successRate = s && s.total_payments ? s.successful / s.total_payments : null
  const loading = stats.loading && !s

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Every payment scored for risk, classified by failure cause, and resolved into a policy-controlled decision."
        right={<LiveBadge lastUpdated={stats.lastUpdated} stale={stats.stale} onRefresh={() => { stats.refresh(); feed.refresh() }} />}
      />

      {stats.error && !s && (
        <div className="errbar" style={{ marginBottom: 16 }}>
          <Icon name="alert" size={16} /> Can’t reach the API at <code className="mono">{api.base}</code>. Start the backend, then this updates automatically.
        </div>
      )}

      <div className="tiles">
        {loading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <div className="card tile" key={i}><Skeleton h={64} /></div>
          ))
        ) : (
          <>
            <Tile label="Payments" icon="activity" value={num(s?.total_payments)} sub={<>ingested &amp; scored</>} />
            <Tile label="Success rate" icon="check" value={pct(successRate, 1)}
              sub={<><b>{num(s?.successful)}</b> of {num(s?.total_payments)} succeeded</>} />
            <Tile label="Failed" icon="bolt" value={num(s?.failed)} sub="routed through recovery logic" />
            <Tile label="Flagged" icon="shield" value={num(s?.high_risk)} sub="held or sent to verification" />
            <Tile label="Revenue at risk" icon="lock" accent value={compactMoney(s?.revenue_at_risk)}
              sub={<>{money(s?.revenue_at_risk, true)} exposure</>} />
          </>
        )}
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <h2>Decisions by action</h2>
            <span className="muted" style={{ fontSize: 12 }}>escalation order</span>
          </div>
          <div className="card-pad">
            {loading ? <Skeleton h={180} /> : (
              <div className="bd">
                {breakdown.map(({ key, meta, count, widthPct, sharePct }) => (
                  <div className="bd__row" key={key}>
                    <StatusChip decision={key} size="sm" />
                    <div className="bd__track">
                      <div className="bd__fill" style={{ width: `${Math.max(count ? 3 : 0, widthPct)}%`, background: `var(${BAR_VAR[meta.role]})` }} />
                    </div>
                    <div className="bd__num">{num(count)}<span className="bd__pct"> · {pct(sharePct)}</span></div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>Throughput</h2></div>
          <div className="card-pad" style={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div className="tile__value tnum" style={{ fontSize: 26 }}>{num(decisions.length)}</div>
                <div className="tile__sub">decisions in the recent window</div>
              </div>
              <Sparkline values={spark} width={150} height={46} />
            </div>
            <p className="muted" style={{ fontSize: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
              Live feed polled every 5s. Bars show relative volume across the window.
            </p>
          </div>
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2>Recent activity</h2>
          <Link to="/stream" className="card-link">Live stream <Icon name="chevron" size={13} /></Link>
        </div>
        <div style={{ padding: '8px 10px' }}>
          {feed.loading && !decisions.length ? (
            <div style={{ display: 'grid', gap: 6, padding: 6 }}>
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} h={44} r={12} />)}
            </div>
          ) : decisions.length === 0 ? (
            <EmptyState icon="activity" title="No payments yet"
              hint="Start the simulator (python simulator/simulate_payments.py) and events will appear here." />
          ) : (
            decisions.slice(0, 6).map((d) => (
              <Link key={d.decision_id} to={`/investigation/${d.decision_id}`} className="minirow">
                <div>
                  <div className="minirow__id mono">{shortId(d.transaction_id)}</div>
                  <div className="minirow__meta">{d.customer_id} · {timeAgo(d.created_at)}</div>
                </div>
                <div className="minirow__amt tnum">{money(d.amount)}</div>
                <StatusChip decision={d.decision} size="sm" />
              </Link>
            ))
          )}
        </div>
      </section>
    </>
  )
}
