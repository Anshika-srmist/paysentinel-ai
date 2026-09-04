// Talks to the PaySentinel FastAPI backend.
//
// Dev: leave VITE_API_BASE_URL unset — requests go to /api/* and Vite proxies
//   them to http://localhost:8000 (see vite.config.js).
// Prod: set VITE_API_BASE_URL to the deployed backend origin.

const BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || '/api'

async function request(path, { signal, method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    signal,
    method,
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail.slice(0, 160)}` : ''}`)
  }
  return res.json()
}

export const api = {
  base: BASE,
  health: (opts) => request('/health', opts),
  stats: (opts) => request('/stats/summary', opts),
  decisions: ({ limit = 60, offset = 0, decision, ...opts } = {}) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (decision) q.set('decision', decision)
    return request(`/decisions?${q}`, opts)
  },
  decision: (id, opts) => request(`/decisions/${id}`, opts),
  payments: ({ limit = 60, offset = 0, ...opts } = {}) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return request(`/payments?${q}`, opts)
  },
  assess: (body, opts = {}) => request('/assess', { ...opts, method: 'POST', body }),
  policy: (opts) => request('/policy', opts),
  customers: ({ limit = 100, ...opts } = {}) => request(`/customers?limit=${limit}`, opts),
  customer: (id, opts) => request(`/customers/${encodeURIComponent(id)}`, opts),
  modelMetrics: (opts) => request('/model/metrics', opts),
  analytics: (opts) => request('/analytics', opts),
  economics: ({ fraudLoss, declineCost, ...opts } = {}) => {
    const q = new URLSearchParams()
    if (fraudLoss != null) q.set('avg_fraud_loss', String(fraudLoss))
    if (declineCost != null) q.set('avg_false_decline_cost', String(declineCost))
    return request(`/analytics/economics${q.toString() ? `?${q}` : ''}`, opts)
  },
  networkGraph: (opts) => request('/network/graph', opts),
  networkClusters: (opts) => request('/network/clusters', opts),
  networkEntity: (kind, ref, opts) => request(`/network/entity/${kind}/${encodeURIComponent(ref)}`, opts),
  scenarios: (opts) => request('/simulate/scenarios', opts),
  runScenario: (name, opts = {}) => request('/simulate/scenario', { ...opts, method: 'POST', body: { name } }),
}
