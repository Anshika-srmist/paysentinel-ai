import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader, LiveBadge } from '../components/AppShell.jsx'
import { Icon } from '../components/Icon.jsx'
import { Skeleton } from '../components/Skeleton.jsx'
import { EmptyState } from '../components/EmptyState.jsx'
import { NetworkGraph } from '../components/NetworkGraph.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { api } from '../api/client.js'
import { money, num, compactMoney, timeAgo } from '../lib/format.js'
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

export function Network() {
  const graph = usePolling((signal) => api.networkGraph({ signal }), 10000)
  const clusters = usePolling((signal) => api.networkClusters({ signal }), 10000)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)

  const pick = async (node) => {
    setSelected(node.id)
    setDetail({ loading: true, node })
    try {
      const d = await api.networkEntity(node.type, node.ref)
      setDetail({ ...d, node })
    } catch {
      setDetail({ node, error: true })
    }
  }

  const s = clusters.data?.summary
  const cl = clusters.data?.clusters || []

  return (
    <>
      <PageHeader
        title="Payment network"
        subtitle="Relationships between customers, devices, merchants and payment activity — and where they concentrate risk."
        right={<LiveBadge lastUpdated={graph.lastUpdated} stale={graph.stale} onRefresh={() => { graph.refresh(); clusters.refresh() }} />}
      />

      <div className="tiles" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        {clusters.loading && !s ? (
          Array.from({ length: 4 }).map((_, i) => <div className="card tile" key={i}><Skeleton h={56} /></div>)
        ) : (
          <>
            <Tile label="Active clusters" value={num(s?.active_clusters)} sub="multi-account groups" />
            <Tile label="High-risk clusters" value={num(s?.high_risk_clusters)} sub="network risk ≥ 0.50" />
            <Tile label="Connected accounts" value={num(s?.connected_accounts)} sub="linked by a shared device" />
            <Tile label="Network exposure" accent value={compactMoney(s?.network_exposure)} sub={money(s?.network_exposure)} />
          </>
        )}
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <h2>Entity graph</h2>
            <span className="netlegend">
              <span><i style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-strong)' }} /> normal</span>
              <span><i style={{ background: 'var(--warn)' }} /> suspicious</span>
              <span><i style={{ background: 'var(--danger)' }} /> high risk</span>
            </span>
          </div>
          <div className="card-pad">
            {graph.loading && !graph.data ? <Skeleton h={280} /> : (
              <NetworkGraph data={graph.data} selected={selected} onSelect={pick} />
            )}
          </div>
        </section>

        <section className="card card-pad" style={{ alignSelf: 'start' }}>
          <div className="eyebrow" style={{ marginBottom: 10 }}>Selected entity</div>
          {!detail ? (
            <EmptyState icon="layers" title="Nothing selected"
              hint="Click a node in the graph to see its connections and activity." />
          ) : detail.loading ? (
            <Skeleton h={160} />
          ) : detail.error ? (
            <p className="muted" style={{ fontSize: 13 }}>Couldn’t load that entity.</p>
          ) : (
            <div>
              <div className="mono" style={{ fontWeight: 700, fontSize: 15 }}>{detail.ref}</div>
              <div className="muted" style={{ fontSize: 12, textTransform: 'capitalize' }}>{detail.type}</div>
              <div className="kv" style={{ marginTop: 12 }}>
                <div className="kv__item"><span className="kv__k">Connected accounts</span><span className="kv__v tnum">{num(detail.connected_accounts?.length)}</span></div>
                <div className="kv__item"><span className="kv__k">Transactions</span><span className="kv__v tnum">{num(detail.transactions)}</span></div>
                <div className="kv__item"><span className="kv__k">Volume</span><span className="kv__v tnum">{money(detail.volume)}</span></div>
              </div>
              {detail.connected_accounts?.length > 0 && (
                <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {detail.connected_accounts.slice(0, 8).map((c) => (
                    <Link key={c} to={`/customers/${encodeURIComponent(c)}`} className="tag mono">{c}</Link>
                  ))}
                </div>
              )}
              {detail.recent?.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div className="eyebrow" style={{ marginBottom: 6 }}>Recent activity</div>
                  {detail.recent.map((r) => (
                    <div key={r.transaction_id} className="minirow" style={{ gridTemplateColumns: '1fr auto', padding: '7px 8px' }}>
                      <div><span className="mono" style={{ fontSize: 12 }}>{r.transaction_id.replace(/^TXN_/, '')}</span>
                        <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>{timeAgo(r.event_time)}</span></div>
                      <span className="tnum" style={{ fontSize: 12.5, fontWeight: 600 }}>{money(r.amount)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Risk clusters</h2><span className="muted" style={{ fontSize: 12 }}>connected multi-account groups</span></div>
        <div className="card-pad">
          {clusters.loading && !cl.length ? <Skeleton h={120} /> : cl.length === 0 ? (
            <EmptyState icon="shield" title="No connected risk cluster"
              hint="Network analysis found no significant connected activity." />
          ) : (
            <div className="clgrid">
              {cl.map((c) => (
                <div key={c.cluster_id} className={`clcard ${c.status === 'under_review' ? 'is-hot' : ''}`}>
                  <div className="row-between">
                    <span className="mono" style={{ fontWeight: 700 }}>{c.cluster_id}</span>
                    <span className={`sevtag ${c.network_risk >= 0.5 ? 'sev--high' : 'sev--low'}`}>{c.network_risk.toFixed(2)}</span>
                  </div>
                  <div className="clcard__stats">
                    <span>{c.accounts} accounts</span><span>{c.devices} device{c.devices !== 1 ? 's' : ''}</span>
                    <span>{c.merchants} merchants</span><span>{c.transactions} txns</span>
                    <span>{compactMoney(c.volume)} volume</span>
                  </div>
                  <div className="clcard__foot">
                    <span className="muted" style={{ fontSize: 11, textTransform: 'capitalize' }}>{c.status.replace('_', ' ')}</span>
                    <span className="muted mono" style={{ fontSize: 11 }}>{c.members.slice(0, 3).join(' · ')}{c.members.length > 3 ? ' …' : ''}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  )
}
