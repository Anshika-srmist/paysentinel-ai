import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, LiveBadge } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { RiskMeter } from '../components/RiskMeter.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { SkeletonRows } from '../components/Skeleton.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { DECISION_ORDER, metaFor, FAILURE_LABEL } from '../lib/decisions.js'
import { money, timeAgo, shortId } from '../lib/format.js'
import './pages.css'

const ROLE_VAR = { ok: '--ok', info: '--info', warn: '--warn', alt: '--alt', danger: '--danger', muted: '--ink-muted' }

export function LiveStream() {
  const [filter, setFilter] = useState(null)
  const navigate = useNavigate()

  const feed = usePolling((signal) => api.decisions({ limit: 90, signal }), 3000)
  const stats = usePolling((signal) => api.stats({ signal }), 10000)

  const rows = feed.data || []
  const counts = stats.data?.decisions_by_action || {}
  const total = Object.values(counts).reduce((a, b) => a + b, 0)

  const shown = useMemo(
    () => (filter ? rows.filter((r) => r.decision === filter) : rows),
    [rows, filter],
  )

  return (
    <>
      <PageHeader
        title="Live stream"
        subtitle="Incoming payment events with the decision the engine reached. Click any row to investigate."
        right={<LiveBadge lastUpdated={feed.lastUpdated} stale={feed.stale} onRefresh={feed.refresh} />}
      />

      {feed.error && !rows.length && (
        <div className="errbar" style={{ marginBottom: 16 }}>
          <Icon name="alert" size={16} /> Can’t reach the API. The stream resumes automatically once the backend is up.
        </div>
      )}

      <div className="streamctl">
        <button className={`fpill ${!filter ? 'is-on' : ''}`} onClick={() => setFilter(null)}>
          All <span className="fpill__count">{total || rows.length}</span>
        </button>
        {DECISION_ORDER.map((key) => (
          <button key={key} className={`fpill ${filter === key ? 'is-on' : ''}`} onClick={() => setFilter(filter === key ? null : key)}>
            <span style={{ width: 7, height: 7, borderRadius: 999, background: `var(${ROLE_VAR[metaFor(key).role]})` }} />
            {metaFor(key).label}
            <span className="fpill__count">{counts[key] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="card stream">
        <div className="stream__head">
          <span />
          <span>Transaction</span>
          <span className="hide-sm">Decision</span>
          <span className="r">Amount</span>
          <span className="hide-sm">Risk</span>
          <span className="hide-sm">Failure</span>
          <span className="r hide-sm">When</span>
          <span />
        </div>

        {feed.loading && !rows.length ? (
          <div style={{ padding: 16 }}><SkeletonRows count={8} h={46} /></div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon="activity"
            title={filter ? `No ${metaFor(filter).label.toLowerCase()} decisions in view` : 'Waiting for payments'}
            hint={filter ? 'Clear the filter or wait for more traffic.' : 'Run the simulator to generate a live feed of events.'}
          />
        ) : (
          shown.map((d) => {
            const meta = metaFor(d.decision)
            const failed = d.status === 'FAILED'
            return (
              <div
                key={d.decision_id}
                className="stream__row"
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/investigation/${d.decision_id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/investigation/${d.decision_id}`) }}
              >
                <span className="stream__rail" style={{ background: `var(${ROLE_VAR[meta.role]})` }} />
                <div>
                  <div className="stream__id mono">{shortId(d.transaction_id)}</div>
                  <div className="stream__cust">{d.customer_id}</div>
                </div>
                <div><StatusChip decision={d.decision} size="sm" /></div>
                <div className={`stream__amt ${failed ? 'is-failed' : ''}`}>{money(d.amount)}</div>
                <div className="stream__cat"><RiskMeter score={d.risk_score} /></div>
                <div className="stream__cat">{FAILURE_LABEL[d.failure_category] || '—'}</div>
                <div className="stream__time">{timeAgo(d.created_at)}</div>
                <Icon name="chevron" size={16} className="stream__chev" />
              </div>
            )
          })
        )}
      </div>
    </>
  )
}
