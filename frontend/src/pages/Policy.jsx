import { PageHeader } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { pct } from '../lib/format.js'
import './pages.css'

const FEATURE_LABEL = {
  amount_ratio_to_typical: 'Amount vs. customer’s typical',
  amount: 'Absolute amount',
  recent_failed_count: 'Recent failed attempts',
  is_new_device: 'New device',
  is_new_payment_method: 'New payment method',
  is_unusual_hour: 'Unusual hour',
}

const CATEGORY_LABEL = {
  temporary: 'Temporary', payment_method: 'Payment method',
  user_related: 'User-related', suspicious: 'Suspicious',
}

function Bars({ rows, format = (v) => v }) {
  const max = Math.max(...rows.map((r) => r.value), 0.0001)
  return (
    <div className="bd">
      {rows.map((r) => (
        <div className="bd__row" key={r.key}>
          <span style={{ fontSize: 12.5, fontWeight: 500 }}>{r.label}</span>
          <div className="bd__track">
            <div className="bd__fill" style={{ width: `${(r.value / max) * 100}%`, background: r.color || 'var(--accent)' }} />
          </div>
          <div className="bd__num">{format(r.value)}</div>
        </div>
      ))}
    </div>
  )
}

export function Policy() {
  const { data, loading, error } = usePolling((signal) => api.policy({ signal }), 30000)

  return (
    <>
      <PageHeader
        title="Decision policy"
        subtitle="The ML model recommends; this fixed policy decides. Both are shown here in full."
      />

      {error && !data && (
        <div className="errbar"><Icon name="alert" size={16} /> {error.message}</div>
      )}

      {loading && !data ? (
        <div className="stack"><div className="card card-pad"><Skeleton h={140} /></div><div className="card card-pad"><Skeleton h={260} /></div></div>
      ) : data ? (
        <div className="stack">
          <blockquote className="principle-quote">
            <Icon name="lock" size={16} strokeWidth={2} />
            <span>“{data.principle}”</span>
          </blockquote>

          <section className="card">
            <div className="card-head"><h2>The policy</h2><span className="muted" style={{ fontSize: 12 }}>evaluated top to bottom</span></div>
            <div className="card-pad">
              <ol className="rules">
                {data.rules.map((r) => (
                  <li className="rule" key={r.order}>
                    <span className="rule__n">{r.order}</span>
                    <div className="rule__body">
                      <div className="rule__cond">
                        <code>{r.condition}</code>
                        <Icon name="chevron" size={14} className="muted" />
                        <StatusChip decision={r.outcome} size="sm" />
                      </div>
                      <div className="rule__why">{r.rationale}</div>
                    </div>
                  </li>
                ))}
              </ol>
              <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                Thresholds: HOLD above <b>{data.thresholds.hold_above}</b>, VERIFY band{' '}
                <b>{data.thresholds.verify_band[0]}–{data.thresholds.verify_band[1]}</b>, RETRY only below{' '}
                <b>{data.thresholds.retry_below}</b>.
              </p>
            </div>
          </section>

          <div className="two-col" style={{ marginTop: 0 }}>
            <section className="card">
              <div className="card-head"><h2>How the model scores</h2><span className="muted" style={{ fontSize: 12 }}>{data.model.name}</span></div>
              <div className="card-pad">
                {data.model.feature_importances ? (
                  <Bars
                    format={(v) => pct(v, 1)}
                    rows={Object.entries(data.model.feature_importances)
                      .sort((a, b) => b[1] - a[1])
                      .map(([k, v]) => ({ key: k, label: FEATURE_LABEL[k] || k, value: v }))}
                  />
                ) : <p className="muted" style={{ fontSize: 13 }}>Linear model — no per-feature importance.</p>}
                <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                  Feature importance from the trained Random Forest. The amount-vs-typical ratio and
                  the raw amount carry most of the signal.
                </p>
              </div>
            </section>

            <section className="card">
              <div className="card-head"><h2>Recovery base rates</h2></div>
              <div className="card-pad">
                <Bars
                  format={(v) => pct(v)}
                  rows={Object.entries(data.recovery_base_rates)
                    .filter(([k]) => k !== 'none')
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, v]) => ({ key: k, label: CATEGORY_LABEL[k] || k, value: v, color: 'var(--ok-bar)' }))}
                />
                <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
                  Starting point for the recovery-probability estimate, before adjusting for risk
                  score and retry history.
                </p>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </>
  )
}
