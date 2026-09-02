import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { RiskMeter } from '../components/RiskMeter.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { money, num, pct, timeAgo, shortId } from '../lib/format.js'
import './pages.css'

function Tile({ label, value, sub, accent }) {
  return (
    <div className={`card tile ${accent ? 'tile--accent' : ''}`}>
      <div className="tile__label">{label}</div>
      <div className="tile__value tnum">{value}</div>
      {sub && <div className="tile__sub">{sub}</div>}
    </div>
  )
}

export function Customer() {
  const { id } = useParams()
  const { data, error, loading } = usePolling((signal) => api.customer(id, { signal }), 12000, [id])

  if (error && !data) {
    return (
      <>
        <PageHeader title="Customer" />
        <div className="card">
          <EmptyState icon="user" title={`No activity for ${id}`}
            hint="This customer hasn't sent any payments yet."
            action={<Link to="/stream" className="btn-primary" style={{ marginTop: 6 }}>Back to live stream</Link>} />
        </div>
      </>
    )
  }

  if (!data) {
    return (
      <>
        <PageHeader title="Customer" />
        <div className="stack"><div className="card card-pad"><Skeleton h={90} /></div><div className="card card-pad"><Skeleton h={220} /></div></div>
      </>
    )
  }

  return (
    <>
      <Link to="/stream" className="inv__back">
        <Icon name="arrowLeft" size={15} strokeWidth={2.2} /> Live stream
      </Link>

      <PageHeader
        title={<span className="mono">{data.customer_id}</span>}
        subtitle={
          <>
            {num(data.total_events)} payments · {pct(data.success_rate)} success ·{' '}
            <b style={{ color: data.history_good ? 'var(--ok)' : 'var(--warn)' }}>
              {data.history_good ? 'established history' : 'thin / mixed history'}
            </b>
          </>
        }
      />

      <div className="tiles" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <Tile label="Payments" value={num(data.total_events)} sub={<>{num(data.successful)} ok · {num(data.failed)} failed</>} />
        <Tile label="Success rate" value={pct(data.success_rate, 1)} />
        <Tile label="Flagged" value={num(data.flagged_count)} sub="verify or hold" />
        <Tile label="Amount at risk" accent value={money(data.amount_at_risk)} />
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head"><h2>Behavioural baseline</h2><span className="muted" style={{ fontSize: 12 }}>what the model compares against</span></div>
          <div className="card-pad">
            <div className="kv">
              <div className="kv__item"><span className="kv__k">Typical amount</span><span className="kv__v tnum">{money(data.typical_amount)}</span></div>
              <div className="kv__item"><span className="kv__k">Usual device</span><span className="kv__v mono">{data.usual_device || '—'}</span></div>
              <div className="kv__item"><span className="kv__k">Usual method</span><span className="kv__v">{data.usual_payment_method || '—'}</span></div>
              <div className="kv__item"><span className="kv__k">Recent failed streak</span><span className="kv__v tnum">{num(data.recent_failed_streak)}</span></div>
              <div className="kv__item"><span className="kv__k">History depth</span><span className="kv__v tnum">{num(data.prior_event_count)} events</span></div>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>Decision mix</h2></div>
          <div className="card-pad" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.keys(data.decisions_by_action).length === 0
              ? <span className="muted" style={{ fontSize: 13 }}>No decisions yet.</span>
              : Object.entries(data.decisions_by_action).map(([d, n]) => (
                <span key={d} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <StatusChip decision={d} size="sm" />
                  <span className="tnum secondary" style={{ fontSize: 13, fontWeight: 600 }}>{n}</span>
                </span>
              ))}
          </div>
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Payment history</h2><span className="muted" style={{ fontSize: 12 }}>newest first</span></div>
        <div style={{ padding: '8px 10px' }}>
          {data.history.map((h) => {
            const inner = (
              <>
                <div>
                  <div className="minirow__id mono">{shortId(h.transaction_id)}</div>
                  <div className="minirow__meta">{h.status} · {timeAgo(h.event_time)}</div>
                </div>
                {h.risk_score != null ? <RiskMeter score={h.risk_score} /> : <span />}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span className="minirow__amt tnum">{money(h.amount)}</span>
                  {h.decision && <StatusChip decision={h.decision} size="sm" />}
                </div>
              </>
            )
            return h.decision_id
              ? <Link key={h.transaction_id} to={`/investigation/${h.decision_id}`} className="minirow" style={{ gridTemplateColumns: '1fr auto auto' }}>{inner}</Link>
              : <div key={h.transaction_id} className="minirow" style={{ gridTemplateColumns: '1fr auto auto' }}>{inner}</div>
          })}
        </div>
      </section>
    </>
  )
}
