import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { StatusChip } from '../components/StatusChip.jsx'
import { RiskMeter } from '../components/RiskMeter.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { api } from '../api/client.js'
import { metaFor } from '../lib/decisions.js'
import { money } from '../lib/format.js'
import './pages.css'

const METHODS = ['UPI', 'CARD', 'NETBANKING', 'WALLET']

const PRESETS = {
  typical: { label: 'Typical payment', customer_id: 'CUST_7', amount: 2200, payment_method: 'UPI', device_id: 'DEVICE_7' },
  anomalous: { label: 'Large amount, new device', customer_id: 'CUST_7', amount: 95000, payment_method: 'CARD', device_id: 'NEW_DEVICE_A1' },
  cardtest: { label: 'Small card test', customer_id: 'CUST_18', amount: 120, payment_method: 'CARD', device_id: 'NEW_DEVICE_C9' },
}

export function LiveCheck() {
  const [form, setForm] = useState(PRESETS.typical)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const run = async (e) => {
    e?.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const body = {
        customer_id: form.customer_id.trim() || 'CUST_1',
        amount: Number(form.amount) || 0,
        payment_method: form.payment_method,
        device_id: form.device_id.trim() || undefined,
      }
      setResult(await api.assess(body))
    } catch (err) {
      setError(err.message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const meta = result && metaFor(result.decision)

  return (
    <>
      <PageHeader
        title="Live check"
        subtitle="The pre-payment call. A checkout or PSP posts an attempt and gets an action back before the money moves — POST /assess."
      />

      <div className="inv">
        {/* form */}
        <form className="card card-pad checkform" onSubmit={run}>
          <div className="checkform__presets">
            {Object.entries(PRESETS).map(([k, p]) => (
              <button type="button" key={k} className="fpill" onClick={() => { setForm(p); setResult(null) }}>
                {p.label}
              </button>
            ))}
          </div>

          <label className="field">
            <span>Customer ID</span>
            <input className="idfield" value={form.customer_id} onChange={(e) => set('customer_id', e.target.value)} />
          </label>

          <label className="field">
            <span>Amount (₹)</span>
            <input className="idfield" inputMode="decimal" value={form.amount}
              onChange={(e) => set('amount', e.target.value.replace(/[^0-9.]/g, ''))} />
          </label>

          <div className="field">
            <span>Payment method</span>
            <div className="seg">
              {METHODS.map((m) => (
                <button type="button" key={m} className={`seg__btn ${form.payment_method === m ? 'is-on' : ''}`}
                  onClick={() => set('payment_method', m)}>{m}</button>
              ))}
            </div>
          </div>

          <label className="field">
            <span>Device ID</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="idfield" value={form.device_id} onChange={(e) => set('device_id', e.target.value)} />
              <button type="button" className="fpill" onClick={() => set('device_id', `NEW_DEVICE_${Math.random().toString(36).slice(2, 6).toUpperCase()}`)}>
                New device
              </button>
            </div>
          </label>

          <button className="btn-primary" type="submit" disabled={loading} style={{ marginTop: 6, justifyContent: 'center' }}>
            {loading ? 'Checking…' : <>Run check <Icon name="bolt" size={15} strokeWidth={2.2} /></>}
          </button>
        </form>

        {/* verdict */}
        <div className="stack">
          {error && (
            <div className="errbar"><Icon name="alert" size={16} /> {error}</div>
          )}

          {!result && !error && (
            <div className="card">
              <EmptyState icon="shield" title="No check run yet"
                hint="Pick a preset or fill the form, then Run check to see the verdict." />
            </div>
          )}

          {result && (
            <section className="card inv__hero">
              <div className="inv__hero-top">
                <StatusChip decision={result.decision} />
                <span className={`chip chip--sm ${result.safe ? 'chip--ok' : 'chip--warn'}`}>
                  <Icon name={result.safe ? 'check' : 'shield'} size={13} strokeWidth={2} />
                  {result.safe ? 'Safe to proceed' : 'Not cleared'}
                </span>
                <div className="inv__amount">
                  <b className="tnum">{money(form.amount)}</b>
                  <span>{form.payment_method} · {form.customer_id}</span>
                </div>
              </div>

              <div className="verdict">
                <div className="verdict__row">
                  <span className="verdict__action">{result.recommended_action || meta.label}</span>
                </div>
                <div className="verdict__hint">{meta.gloss}</div>
              </div>

              <div style={{ marginTop: 18 }}>
                <div className="row-between" style={{ marginBottom: 8 }}>
                  <span className="eyebrow">Composite risk</span>
                </div>
                <RiskMeter score={result.composite_risk} variant="block" />
                <div className="rbd" style={{ marginTop: 12 }}>
                  <div className="rbd__row"><span className="rbd__label">Transaction model</span>
                    <div className="rbd__track"><div className="rbd__fill" style={{ width: `${(result.ml_risk ?? 0) * 100}%`, background: 'var(--accent)' }} /></div>
                    <span className="rbd__val tnum">{(result.ml_risk ?? 0).toFixed(2)}</span></div>
                  <div className="rbd__row"><span className="rbd__label">Behavioural</span>
                    <div className="rbd__track"><div className="rbd__fill" style={{ width: `${(result.behavioral_risk ?? 0) * 100}%`, background: 'var(--alt)' }} /></div>
                    <span className="rbd__val tnum">{(result.behavioral_risk ?? 0).toFixed(2)}</span></div>
                  <div className="rbd__row"><span className="rbd__label">Network</span>
                    <div className="rbd__track"><div className="rbd__fill" style={{ width: `${(result.network_risk ?? 0) * 100}%`, background: 'var(--danger)' }} /></div>
                    <span className="rbd__val tnum">{(result.network_risk ?? 0).toFixed(2)}</span></div>
                </div>
              </div>

              <div className="explain">
                <div className="explain__label">
                  <Icon name="layers" size={14} strokeWidth={2} /> Decision explanation
                </div>
                <p className="explain__text">{result.explanation_sections?.summary || result.explanation}</p>
                {result.explanation_sections?.why_this_action && (
                  <dl className="explain__grid">
                    <dt>What the model saw</dt><dd>{result.explanation_sections.what_the_model_saw}</dd>
                    <dt>What the network saw</dt><dd>{result.explanation_sections.what_the_network_saw}</dd>
                    <dt>Why this action</dt><dd>{result.explanation_sections.why_this_action}</dd>
                  </dl>
                )}
              </div>

              {result.signals?.length > 0 && (
                <div className="signals">
                  <span className="eyebrow">Triggered signals</span>
                  {result.signals.map((s, i) => (
                    <div className="signal" key={i}><Icon name="alert" size={15} strokeWidth={2} /><span>{s}</span></div>
                  ))}
                </div>
              )}

              <Link to={`/investigation/${result.decision_id}`} className="card-link" style={{ marginTop: 16 }}>
                Open full investigation <Icon name="chevron" size={13} />
              </Link>
            </section>
          )}
        </div>
      </div>
    </>
  )
}
