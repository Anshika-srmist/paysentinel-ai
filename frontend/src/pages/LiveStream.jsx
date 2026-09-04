import { useEffect, useMemo, useState } from 'react'
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

  const [scenarioList, setScenarioList] = useState([])
  const [injecting, setInjecting] = useState(null)
  const [injectResult, setInjectResult] = useState(null)
  const [injectError, setInjectError] = useState(null)

  useEffect(() => {
    api.scenarios().then((r) => setScenarioList(r.scenarios)).catch(() => {})
  }, [])

  const inject = async (name) => {
    setInjecting(name)
    setInjectError(null)
    try {
      const result = await api.runScenario(name)
      setInjectResult(result)
      feed.refresh()
      stats.refresh()
    } catch (err) {
      setInjectError(err.message)
    } finally {
      setInjecting(null)
    }
  }

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

      {scenarioList.length > 0 && (
        <div className="card card-pad injector">
          <div className="injector__head">
            <span className="eyebrow"><Icon name="bolt" size={13} strokeWidth={2.2} /> Trigger a scenario</span>
            <span className="muted" style={{ fontSize: 12.5 }}>
              Fires a real burst through the real pipeline right now — for a live walkthrough, not a mock.
            </span>
          </div>
          <div className="injector__row">
            {scenarioList.map((s) => (
              <button
                key={s.name}
                type="button"
                className={`fpill ${s.name === 'coordinated_ring' ? 'fpill--hero' : ''}`}
                disabled={Boolean(injecting)}
                onClick={() => inject(s.name)}
              >
                {injecting === s.name ? 'Running…' : s.label}
              </button>
            ))}
          </div>

          {injectError && (
            <div className="errbar" style={{ marginTop: 10 }}><Icon name="alert" size={15} /> {injectError}</div>
          )}

          {injectResult && (
            <div className="injector__result">
              <div className="injector__resulthead">
                <Icon name="check" size={14} strokeWidth={2.2} />
                <b>{injectResult.label}</b>
                <span className="muted">
                  — {injectResult.events_created} event{injectResult.events_created === 1 ? '' : 's'}
                  {injectResult.hold_count ? `, ${injectResult.hold_count} held` : ''}, expected {injectResult.expect}
                </span>
              </div>
              <div className="injector__decisions">
                {injectResult.decisions.slice(0, 8).map((d) => (
                  <span
                    key={d.transaction_id}
                    className="injector__d"
                    role="button"
                    tabIndex={0}
                    onClick={() => navigate(`/investigation/${d.decision_id}`)}
                  >
                    <StatusChip decision={d.decision} size="sm" />
                    <span className="mono">{shortId(d.transaction_id)}</span>
                    <span className="tnum">{d.risk_score.toFixed(2)}</span>
                  </span>
                ))}
                {injectResult.decisions.length > 8 && (
                  <span className="muted" style={{ fontSize: 12 }}>+{injectResult.decisions.length - 8} more</span>
                )}
              </div>
            </div>
          )}
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
          <span className="hide-sm">Composite risk</span>
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
                <div className="stream__cat">
                  <RiskMeter score={d.risk_score} />
                  {(d.ml_risk != null || d.network_risk != null) && (
                    <div className="stream__sub tnum">
                      ml {(d.ml_risk ?? 0).toFixed(2)} · net {(d.network_risk ?? 0).toFixed(2)}
                    </div>
                  )}
                </div>
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
