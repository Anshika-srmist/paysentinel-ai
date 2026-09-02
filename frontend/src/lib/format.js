const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})
const inrPrecise = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export const money = (n, precise = false) =>
  n == null ? '—' : (precise ? inrPrecise : inr).format(Number(n))

export const compactMoney = (n) => {
  if (n == null) return '—'
  const v = Number(n)
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`
  return inr.format(v)
}

export const pct = (n, digits = 0) =>
  n == null ? '—' : `${(Number(n) * 100).toFixed(digits)}%`

export const num = (n) => (n == null ? '—' : new Intl.NumberFormat('en-IN').format(Number(n)))

export function timeAgo(iso) {
  if (!iso) return ''
  const then = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).getTime()
  const s = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export const shortId = (id) => (id ? id.replace(/^TXN_/, '') : '')
