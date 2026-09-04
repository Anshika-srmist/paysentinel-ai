import { useMemo, useState } from 'react'
import { PageHeader } from '../components/AppShell.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { DECISION_ORDER, metaFor } from '../lib/decisions.js'
import { money, num, pct, compactMoney } from '../lib/format.js'
import './pages.css'

const BAR_VAR = { ok: '--ok-bar', info: '--info-bar', warn: '--warn-bar', alt: '--alt-bar', danger: '--danger-bar', muted: '--ink-muted' }
const bandColor = (lo) => (lo >= 0.9 ? 'var(--danger-bar)' : lo >= 0.3 ? 'var(--warn-bar)' : 'var(--ok-bar)')

function Metric({ label, value, hint, strong }) {
  return (
    <div className={`card tile ${strong ? 'tile--accent' : ''}`}>
      <div className="tile__label">{label}</div>
      <div className="tile__value tnum" style={strong ? {} : { color: 'var(--ink)' }}>{value}</div>
      {hint && <div className="tile__sub">{hint}</div>}
    </div>
  )
}

export function Analytics() {
  const metrics = usePolling((signal) => api.modelMetrics({ signal }), 60000)
  const an = usePolling((signal) => api.analytics({ signal }), 15000)
  const [fraudLoss, setFraudLoss] = useState(38000)
  const [declineCost, setDeclineCost] = useState(520)
  const eco = usePolling(
    (signal) => api.economics({ fraudLoss, declineCost, signal }),
    600000,
    [fraudLoss, declineCost],
  )
  const [thr, setThr] = useState(null)

  const m = metrics.data
  const selected = useMemo(
    () => m?.models?.find((x) => x.model === m.selected_model),
    [m],
  )
  const sweepPoint = useMemo(() => {
    if (!m?.threshold_sweep?.length) return null
    const t = thr ?? 0.5
    return m.threshold_sweep.reduce((best, p) =>
      Math.abs(p.threshold - t) < Math.abs(best.threshold - t) ? p : best)
  }, [m, thr])

  return (
    <>
      <PageHeader
        title="Risk analytics"
        subtitle="Held-out model performance, false-positive economics, and where risk is concentrated. Financial figures are simulated."
      />

      {metrics.error && !m && (
        <div className="errbar"><Icon name="alert" size={16} /> Model metrics unavailable — run <code className="mono">python ml/train.py</code>.</div>
      )}

      {/* --- headline metrics --- */}
      {metrics.loading && !m ? (
        <div className="tiles">{Array.from({ length: 5 }).map((_, i) => <div className="card tile" key={i}><Skeleton h={56} /></div>)}</div>
      ) : selected && (
        <>
          <div className="tiles">
            <Metric label="Precision" value={selected.precision.toFixed(2)} hint="of flags that were fraud" />
            <Metric label="Recall" value={selected.recall.toFixed(2)} hint="of fraud that was caught" />
            <Metric label="F1" value={selected.f1.toFixed(2)} />
            <Metric label="PR-AUC" value={selected.pr_auc.toFixed(2)} hint="lead metric (imbalanced)" strong />
            <Metric label="False-positive rate" value={pct(selected.false_positive_rate, 1)} hint="of legit payments" />
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            {m.selected_model} · {m.evaluation} · {num(m.dataset.training_records)} train / {num(m.dataset.test_records)} test rows ·
            positive rate {pct(m.dataset.positive_rate)} · imbalance: {m.imbalance_handling}.
          </p>
        </>
      )}

      {/* --- model comparison + confusion matrix --- */}
      {m && (
        <div className="two-col">
          <section className="card">
            <div className="card-head"><h2>Model comparison</h2><span className="muted" style={{ fontSize: 12 }}>held-out test set</span></div>
            <div className="card-pad" style={{ overflowX: 'auto' }}>
              <table className="atable">
                <thead><tr><th>Model</th><th>P</th><th>R</th><th>F1</th><th>PR-AUC</th><th>FPR</th></tr></thead>
                <tbody>
                  {m.models.map((x) => (
                    <tr key={x.model} className={x.model === m.selected_model ? 'is-selected' : ''}>
                      <td>{x.model.replace(' + class weighting', '').replace(' (baseline)', '')}
                        {x.model === m.selected_model && <span className="picktag">selected</span>}</td>
                      <td className="tnum">{x.precision.toFixed(2)}</td>
                      <td className="tnum">{x.recall.toFixed(2)}</td>
                      <td className="tnum">{x.f1.toFixed(2)}</td>
                      <td className="tnum">{x.pr_auc.toFixed(2)}</td>
                      <td className="tnum">{pct(x.false_positive_rate, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 11.5, marginTop: 8 }}>
                Random Forest is selected on PR-AUC — same recall as the baseline at a fraction of the false-positive rate.
              </p>
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>Confusion matrix</h2><span className="muted" style={{ fontSize: 12 }}>{m.selected_model.split(' + ')[0]}</span></div>
            <div className="card-pad">
              {selected && (
                <div className="cmatrix">
                  <div className="cm cm--tp"><span>{num(selected.confusion_matrix.tp)}</span><em>True positive · fraud caught</em></div>
                  <div className="cm cm--fp"><span>{num(selected.confusion_matrix.fp)}</span><em>False positive · legit flagged</em></div>
                  <div className="cm cm--fn"><span>{num(selected.confusion_matrix.fn)}</span><em>False negative · fraud missed</em></div>
                  <div className="cm cm--tn"><span>{num(selected.confusion_matrix.tn)}</span><em>True negative · legit cleared</em></div>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* --- threshold analysis --- */}
      {m?.threshold_sweep?.length > 0 && (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="card-head"><h2>Threshold analysis</h2><span className="muted" style={{ fontSize: 12 }}>trade recall against false positives</span></div>
          <div className="card-pad">
            <input type="range" min="0.1" max="0.9" step="0.05" value={sweepPoint?.threshold ?? 0.5}
              onChange={(e) => setThr(Number(e.target.value))} className="thrslider" />
            {sweepPoint && (
              <div className="thrgrid">
                <div><span className="tnum">{sweepPoint.threshold.toFixed(2)}</span><em>threshold</em></div>
                <div><span className="tnum">{sweepPoint.precision.toFixed(2)}</span><em>precision</em></div>
                <div><span className="tnum">{sweepPoint.recall.toFixed(2)}</span><em>recall</em></div>
                <div><span className="tnum">{num(sweepPoint.fraud_captured)}</span><em>fraud caught</em></div>
                <div><span className="tnum">{num(sweepPoint.false_positives)}</span><em>false positives</em></div>
                <div><span className="tnum">{num(sweepPoint.fraud_missed)}</span><em>fraud missed</em></div>
              </div>
            )}
            <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
              The policy engine holds at 0.90 and verifies from 0.30 — this shows what moving that line would cost.
            </p>
          </div>
        </section>
      )}

      {/* --- decision economics --- */}
      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Decision economics</h2><span className="muted" style={{ fontSize: 12 }}>simulation assumptions</span></div>
        <div className="card-pad">
          <div className="ecoassume">
            <label>Avg. fraud loss (₹)
              <input type="number" value={fraudLoss} min={0} step={1000}
                onChange={(e) => setFraudLoss(Number(e.target.value) || 0)} className="idfield" />
            </label>
            <label>Avg. false-decline cost (₹)
              <input type="number" value={declineCost} min={0} step={20}
                onChange={(e) => setDeclineCost(Number(e.target.value) || 0)} className="idfield" />
            </label>
          </div>
          {eco.loading && !eco.data ? <Skeleton h={90} /> : eco.data && (
            <>
              <div className="ecoledger">
                <div className="ecoledger__row">
                  <span className="ecoledger__sign" style={{ color: 'var(--ok)' }}>+</span>
                  <span className="ecoledger__label">Fraud loss prevented<em>{num(eco.data.fraud_cases_detected)} caught × {money(eco.data.assumptions.avg_fraud_loss)}</em></span>
                  <span className="ecoledger__val tnum" style={{ color: 'var(--ok)' }}>{money(eco.data.estimated_prevented_loss)}</span>
                </div>
                <div className="ecoledger__row">
                  <span className="ecoledger__sign" style={{ color: 'var(--danger)' }}>−</span>
                  <span className="ecoledger__label">False-decline cost<em>{num(eco.data.false_positives)} wrong declines × {money(eco.data.assumptions.avg_false_decline_cost)}</em></span>
                  <span className="ecoledger__val tnum" style={{ color: 'var(--danger)' }}>{money(eco.data.estimated_false_positive_cost)}</span>
                </div>
                <div className="ecoledger__row ecoledger__row--total">
                  <span className="ecoledger__sign">=</span>
                  <span className="ecoledger__label">Net impact vs. no fraud detection</span>
                  <span className="ecoledger__val tnum" style={{ color: 'var(--accent-strong)' }}>{money(eco.data.net_estimated_impact)}</span>
                </div>
              </div>
              <div className="ecogap">
                <Icon name="alert" size={14} strokeWidth={2} />
                <span>
                  <b>Coverage gap:</b> {num(eco.data.fraud_cases_missed)} fraud cases scored below threshold and got through —
                  ≈ {money(eco.data.residual_missed_fraud_loss)} in residual exposure. This is what a better model would recover;
                  it is not a cost the system adds, so it is not in the net.
                </span>
              </div>
              <p className="muted" style={{ fontSize: 11.5, marginTop: 10 }}>
                {eco.data.net_formula}. Computed from the held-out confusion matrix ({eco.data.basis}). {eco.data.assumptions.note}
              </p>
            </>
          )}
        </div>
      </section>

      {/* --- risk distribution + top signals --- */}
      {an.data && (
        <div className="two-col">
          <section className="card">
            <div className="card-head"><h2>Composite risk distribution</h2><span className="muted" style={{ fontSize: 12 }}>{num(an.data.total_decisions)} decisions</span></div>
            <div className="card-pad">
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 120 }}>
                {an.data.risk_histogram.map((b, i) => {
                  const max = Math.max(...an.data.risk_histogram.map((x) => x.count), 1)
                  return (
                    <div key={i} title={`${b.lo.toFixed(1)}–${b.hi.toFixed(1)}: ${b.count}`}
                      style={{ flex: 1, height: `${(b.count / max) * 100}%`, minHeight: b.count ? 3 : 0, background: bandColor(b.lo), borderRadius: '3px 3px 0 0' }} />
                  )
                })}
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 6, fontSize: 10, color: 'var(--ink-muted)' }}>
                {an.data.risk_histogram.map((b, i) => <div key={i} style={{ flex: 1, textAlign: 'center' }}>{i % 2 === 0 ? b.lo.toFixed(1) : ''}</div>)}
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>Top risk signals</h2></div>
            <div className="card-pad">
              {an.data.top_signals.length === 0 ? <span className="muted" style={{ fontSize: 13 }}>No signals recorded yet.</span> : (
                <div className="bd">
                  {an.data.top_signals.map((s) => {
                    const max = Math.max(...an.data.top_signals.map((x) => x.count), 1)
                    return (
                      <div className="bd__row" key={s.signal}>
                        <span style={{ fontSize: 12.5 }}>{s.signal}</span>
                        <div className="bd__track"><div className="bd__fill" style={{ width: `${(s.count / max) * 100}%`, background: 'var(--alt-bar)' }} /></div>
                        <div className="bd__num">{num(s.count)}</div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* --- decision distribution --- */}
      {an.data && (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="card-head"><h2>Decision distribution</h2></div>
          <div className="card-pad">
            <div className="bd">
              {DECISION_ORDER.map((k) => {
                const by = an.data.decisions_by_action
                const total = Object.values(by).reduce((a, b) => a + b, 0) || 1
                const max = Math.max(1, ...Object.values(by))
                return (
                  <div className="bd__row" key={k}>
                    <StatusChip decision={k} size="sm" />
                    <div className="bd__track"><div className="bd__fill" style={{ width: `${((by[k] || 0) / max) * 100}%`, background: `var(${BAR_VAR[metaFor(k).role]})` }} /></div>
                    <div className="bd__num">{num(by[k] || 0)}<span className="bd__pct"> · {pct((by[k] || 0) / total)}</span></div>
                  </div>
                )
              })}
            </div>
          </div>
        </section>
      )}
    </>
  )
}
