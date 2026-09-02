import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { RiskMeter } from '../components/RiskMeter.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { metaFor, riskBand, FAILURE_LABEL } from '../lib/decisions.js'
import { money, pct, num } from '../lib/format.js'
import './pages.css'

const fmtDateTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function KV({ k, v, mono }) {
  return (
    <div className="kv__item">
      <span className="kv__k">{k}</span>
      <span className={`kv__v ${mono ? 'mono' : ''}`}>{v ?? '—'}</span>
    </div>
  )
}

function FeatCell({ k, v, flag }) {
  return (
    <div className="feat__cell">
      <div className="feat__k">{k}</div>
      <div className={`feat__v ${flag ? 'is-flag' : ''}`}>{v}</div>
    </div>
  )
}

export function Investigation() {
  const { id } = useParams()
  const { data, error, loading } = usePolling(
    (signal) => api.decision(id, { signal }),
    8000,
    [id],
  )

  if (error && !data) {
    return (
      <>
        <PageHeader title="Investigation" />
        <div className="card">
          <EmptyState
            icon="search"
            title={`Decision #${id} not found`}
            hint="It may not have been scored yet, or the ID is wrong."
            action={<Link to="/investigation" className="btn-primary" style={{ marginTop: 6 }}>Back to investigation</Link>}
          />
        </div>
      </>
    )
  }

  if (!data) {
    return (
      <>
        <PageHeader title="Investigation" />
        <div className="inv">
          <div className="card card-pad"><Skeleton h={340} /></div>
          <div className="card card-pad"><Skeleton h={220} /></div>
        </div>
      </>
    )
  }

  const { event: ev, decision: dec, recommended_action, signals = [], features: f = {} } = data
  const meta = metaFor(dec.decision)
  const band = riskBand(dec.risk_score)
  const failed = ev.status === 'FAILED'
  const isLLM = dec.explanation_source === 'llm'

  return (
    <>
      <Link to="/investigation" className="inv__back">
        <Icon name="arrowLeft" size={15} strokeWidth={2.2} /> Investigation
      </Link>

      <PageHeader
        title={<span className="mono">{ev.transaction_id}</span>}
        subtitle={`Decision #${dec.id} · scored by ${dec.model_name || 'risk model'}`}
      />

      <div className="inv">
        {/* -------- main -------- */}
        <div className="stack">
          <section className="card inv__hero">
            <div className="inv__hero-top">
              <span className={`chip ${failed ? 'chip--danger' : 'chip--ok'} chip--sm`}>
                <Icon name={failed ? 'bolt' : 'check'} size={13} strokeWidth={2} />
                {ev.status}
              </span>
              {ev.failure_reason && (
                <span className="secondary" style={{ fontSize: 12.5 }}>
                  {ev.failure_reason.replaceAll('_', ' ').toLowerCase()}
                </span>
              )}
              <div className="inv__amount">
                <b className="tnum">{money(ev.amount, true)}</b>
                <span>{failed ? 'attempted' : 'captured'}</span>
              </div>
            </div>

            <div className="verdict">
              <div className="verdict__row">
                <StatusChip decision={dec.decision} />
                <span className="verdict__action">{recommended_action || meta.label}</span>
              </div>
              <div className="verdict__hint">{meta.gloss}</div>
            </div>

            <div style={{ marginTop: 18 }}>
              <div className="row-between" style={{ marginBottom: 8 }}>
                <span className="eyebrow">Risk score</span>
                <span className="eyebrow" style={{ color: `var(${band.varName})` }}>{band.label}</span>
              </div>
              <RiskMeter score={dec.risk_score} variant="block" />
            </div>

            <div className="explain">
              <div className="explain__label">
                <Icon name="sparkles" size={14} strokeWidth={2} />
                AI explanation
                <span className="explain__badge">{isLLM ? 'LLM-generated' : 'template'}</span>
              </div>
              <p className="explain__text">{dec.explanation || '—'}</p>
            </div>

            <div className="signals">
              <span className="eyebrow">Triggered signals</span>
              {signals.length === 0 ? (
                <div className="signals__none">No risk signals fired for this payment.</div>
              ) : (
                signals.map((s, i) => (
                  <div className="signal" key={i}>
                    <Icon name="alert" size={15} strokeWidth={2} />
                    <span>{s}</span>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>What the engine saw</h2><span className="muted" style={{ fontSize: 12 }}>feature snapshot</span></div>
            <div className="card-pad">
              <div className="feat">
                <FeatCell k="Amount vs typical" v={`${(f.amount_ratio_to_typical ?? 1).toFixed(2)}×`} flag={(f.amount_ratio_to_typical ?? 0) >= 3} />
                <FeatCell k="Recent failed attempts" v={num(f.recent_failed_count ?? 0)} flag={(f.recent_failed_count ?? 0) >= 2} />
                <FeatCell k="New device" v={f.is_new_device ? 'Yes' : 'No'} flag={f.is_new_device} />
                <FeatCell k="New payment method" v={f.is_new_payment_method ? 'Yes' : 'No'} flag={f.is_new_payment_method} />
                <FeatCell k="Unusual hour" v={f.is_unusual_hour ? 'Yes' : 'No'} flag={f.is_unusual_hour} />
                <FeatCell k="Customer history" v={f.customer_history_good ? 'Established' : 'Thin / poor'} flag={!f.customer_history_good} />
              </div>
              <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                Derived from this customer’s {num(f.prior_event_count ?? 0)} prior event(s) at scoring time.
              </p>
            </div>
          </section>
        </div>

        {/* -------- aside -------- */}
        <div className="stack">
          <section className="card card-pad">
            <div className="eyebrow" style={{ marginBottom: 10 }}>Recovery outlook</div>
            {dec.recovery_probability == null ? (
              <p className="muted" style={{ fontSize: 13 }}>Not applicable — the payment succeeded.</p>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span className="tnum" style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--ok)' }}>
                    {pct(dec.recovery_probability)}
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>likely to recover</span>
                </div>
                <div className="riskmeter__track" style={{ width: '100%', height: 10, marginTop: 10 }}>
                  <div className="riskmeter__fill" style={{ width: `${dec.recovery_probability * 100}%`, background: 'var(--ok)' }} />
                </div>
              </>
            )}
          </section>

          <section className="card">
            <div className="card-head"><h2>Payment details</h2></div>
            <div className="card-pad" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <div className="kv">
                <div className="kv__item">
                  <span className="kv__k">Customer</span>
                  <Link to={`/customers/${encodeURIComponent(ev.customer_id)}`} className="kv__v mono card-link">
                    {ev.customer_id} <Icon name="chevron" size={12} />
                  </Link>
                </div>
                <KV k="Merchant" v={ev.merchant_id} mono />
                <KV k="Method" v={ev.payment_method} />
                <KV k="Bank" v={ev.bank} />
                <KV k="Device" v={ev.device_id} mono />
                <KV k="Event time" v={fmtDateTime(ev.event_time)} />
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>Decision record</h2></div>
            <div className="card-pad" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <div className="kv">
                <KV k="Failure category" v={FAILURE_LABEL[dec.failure_category] || dec.failure_category || '—'} />
                <KV k="Scored by" v={dec.model_name} />
                <KV k="Explanation" v={isLLM ? 'LLM-generated' : 'Template fallback'} />
                <KV k="Decided at" v={fmtDateTime(dec.created_at)} />
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
