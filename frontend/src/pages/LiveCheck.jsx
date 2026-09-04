import { useEffect, useMemo, useState } from 'react'
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
const NEW_CUSTOMER = '__new__'

function freshId(prefix) {
  return `${prefix}_${Math.random().toString(36).slice(2, 7).toUpperCase()}`
}

export function LiveCheck() {
  const [customers, setCustomers] = useState([])
  const [custState, setCustState] = useState('loading') // loading | ok | error
  const [picked, setPicked] = useState(NEW_CUSTOMER)
  const [form, setForm] = useState({ customer_id: freshId('CUST_NEW'), amount: 2200, payment_method: 'UPI', device_id: freshId('DEVICE') })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.customers({}).then((rows) => { setCustomers(rows); setCustState('ok') })
      .catch(() => setCustState('error'))
  }, [])

  const baseline = useMemo(
    () => customers.find((c) => c.customer_id === form.customer_id),
    [customers, form.customer_id],
  )

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const pickCustomer = (id) => {
    setPicked(id)
    setResult(null)
    if (id === NEW_CUSTOMER) {
      setForm({ customer_id: freshId('CUST_NEW'), amount: 2200, payment_method: 'UPI', device_id: freshId('DEVICE') })
      return
    }
    const c = customers.find((x) => x.customer_id === id)
    setForm({
      customer_id: id,
      amount: c?.typical_amount ? Math.round(c.typical_amount) : 2200,
      payment_method: c?.usual_payment_method || 'UPI',
      device_id: c?.usual_device || freshId('DEVICE'),
    })
  }

  const applyPreset = (name) => {
    setResult(null)
    if (name === 'typical') {
      if (picked === NEW_CUSTOMER) return
      set('amount', baseline?.typical_amount ? Math.round(baseline.typical_amount) : 2200)
      set('device_id', baseline?.usual_device || form.device_id)
      set('payment_method', baseline?.usual_payment_method || 'UPI')
    } else if (name === 'spike') {
      const base = (picked !== NEW_CUSTOMER && baseline?.typical_amount) || 2000
      set('amount', Math.round(base * 30))
      set('device_id', freshId('NEW_DEVICE'))
      set('payment_method', 'CARD')
    } else if (name === 'newcust_big') {
      pickCustomer(NEW_CUSTOMER)
      setForm((f) => ({ ...f, amount: 65000, payment_method: 'CARD' }))
    }
  }

  const run = async (e) => {
    e?.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const body = {
        customer_id: form.customer_id.trim(),
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
        subtitle="The pre-payment call, against real customer history — POST /assess. Pick a real customer so the model has a baseline to judge against, or test a brand-new one."
      />

      <div className="inv">
        {/* form */}
        <form className="card card-pad checkform" onSubmit={run}>
          <div className="field">
            <span>Customer</span>
            {custState === 'error' ? (
              <p className="muted" style={{ fontSize: 12.5 }}>Couldn’t load customers — check the API.</p>
            ) : (
              <select className="idfield" value={picked} onChange={(e) => pickCustomer(e.target.value)} disabled={custState === 'loading'}>
                <option value={NEW_CUSTOMER}>+ New customer (no history — cold start)</option>
                {customers.map((c) => (
                  <option key={c.customer_id} value={c.customer_id}>
                    {c.customer_id} — {c.total_events} txns{c.typical_amount ? ` · typ. ₹${Math.round(c.typical_amount).toLocaleString('en-IN')}` : ''}{c.history_good ? ' · established' : ''}
                  </option>
                ))}
              </select>
            )}
            {picked !== NEW_CUSTOMER && baseline ? (
              <p className="fieldnote">
                Real customer, {baseline.total_events} prior payments · usually {baseline.usual_payment_method} from <span className="mono">{baseline.usual_device}</span>
                {baseline.history_good ? ' · established history' : ' · thin history'}. Values below are scored against this baseline.
              </p>
            ) : (
              <p className="fieldnote">No prior history — the model falls back to neutral defaults for this one, which is itself a valid test.</p>
            )}
          </div>

          <div className="checkform__presets">
            <button type="button" className="fpill" disabled={picked === NEW_CUSTOMER} onClick={() => applyPreset('typical')}>Typical for them</button>
            <button type="button" className="fpill" onClick={() => applyPreset('spike')}>Spike + new device</button>
            <button type="button" className="fpill" onClick={() => applyPreset('newcust_big')}>New customer, big first payment</button>
          </div>

          <label className="field">
            <span>Customer ID</span>
            <input className="idfield mono" value={form.customer_id} onChange={(e) => set('customer_id', e.target.value)} />
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
              <input className="idfield mono" value={form.device_id} onChange={(e) => set('device_id', e.target.value)} />
              <button type="button" className="fpill" onClick={() => set('device_id', freshId('NEW_DEVICE'))}>
                New device
              </button>
            </div>
          </label>

          <button className="btn-primary" type="submit" disabled={loading || !form.customer_id.trim() || !(Number(form.amount) > 0)} style={{ marginTop: 6, justifyContent: 'center' }}>
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
              <EmptyState icon="shield" title="Ready to assess a payment"
                hint="Pick a real customer (or a new one), set an amount and device, then Run check to generate risk, behavioural and policy analysis." />
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
