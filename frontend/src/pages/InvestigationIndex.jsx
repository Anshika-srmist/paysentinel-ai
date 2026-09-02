import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHeader, LiveBadge } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { RiskMeter } from '../components/RiskMeter.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { SkeletonRows } from '../components/Skeleton.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { money, timeAgo, shortId } from '../lib/format.js'
import './pages.css'

export function InvestigationIndex() {
  const [idInput, setIdInput] = useState('')
  const navigate = useNavigate()
  const feed = usePolling((signal) => api.decisions({ limit: 90, signal }), 6000)

  const priority = useMemo(
    () => (feed.data || []).filter((d) => d.decision === 'HOLD' || d.decision === 'VERIFY').slice(0, 12),
    [feed.data],
  )

  return (
    <>
      <PageHeader
        title="Investigation"
        subtitle="Open a payment to see its risk score, the signals that fired, and the AI-written explanation behind the decision."
        right={<LiveBadge lastUpdated={feed.lastUpdated} stale={feed.stale} onRefresh={feed.refresh} />}
      />

      <div className="two-col" style={{ marginTop: 0 }}>
        <section className="card">
          <div className="card-head">
            <h2>Needs attention</h2>
            <Link to="/stream" className="card-link">All events <Icon name="chevron" size={13} /></Link>
          </div>
          <div style={{ padding: '8px 10px' }}>
            {feed.loading && !priority.length ? (
              <div style={{ padding: 6 }}><SkeletonRows count={5} h={46} /></div>
            ) : priority.length === 0 ? (
              <EmptyState icon="shield" title="Nothing flagged"
                hint="No payments are on hold or awaiting verification right now." />
            ) : (
              priority.map((d) => (
                <Link key={d.decision_id} to={`/investigation/${d.decision_id}`} className="minirow">
                  <div>
                    <div className="minirow__id mono">{shortId(d.transaction_id)}</div>
                    <div className="minirow__meta">{d.customer_id} · {timeAgo(d.created_at)}</div>
                  </div>
                  <RiskMeter score={d.risk_score} />
                  <StatusChip decision={d.decision} size="sm" />
                </Link>
              ))
            )}
          </div>
        </section>

        <section className="card card-pad" style={{ alignSelf: 'start' }}>
          <div className="eyebrow">Open by ID</div>
          <p className="secondary" style={{ fontSize: 13, margin: '8px 0 14px' }}>
            Have a decision ID from a log or alert? Jump straight to it.
          </p>
          <form
            onSubmit={(e) => { e.preventDefault(); if (idInput.trim()) navigate(`/investigation/${idInput.trim()}`) }}
            style={{ display: 'flex', gap: 8 }}
          >
            <input
              className="idfield"
              inputMode="numeric"
              placeholder="e.g. 128"
              value={idInput}
              onChange={(e) => setIdInput(e.target.value.replace(/[^0-9]/g, ''))}
            />
            <button className="btn-primary" type="submit" disabled={!idInput.trim()}>
              Open <Icon name="chevron" size={14} strokeWidth={2.4} />
            </button>
          </form>
        </section>
      </div>
    </>
  )
}
