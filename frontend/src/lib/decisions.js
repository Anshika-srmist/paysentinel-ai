// One source of truth for how each decision reads: label, colour role, icon,
// and a one-line gloss. Order = escalation order (used for the Overview
// breakdown and the Live Stream filter row).

export const DECISION_ORDER = ['APPROVE', 'RETRY', 'OFFER_ALTERNATIVE', 'VERIFY', 'HOLD']

export const DECISION_META = {
  APPROVE: {
    label: 'Approve',
    role: 'ok',
    icon: 'check',
    gloss: 'Low risk, no signals — let it through.',
  },
  RETRY: {
    label: 'Retry',
    role: 'info',
    icon: 'refresh',
    gloss: 'Temporary failure, low risk — safe to retry automatically.',
  },
  OFFER_ALTERNATIVE: {
    label: 'Offer alternative',
    role: 'alt',
    icon: 'swap',
    gloss: 'Payment method failed for a trusted customer — suggest another.',
  },
  VERIFY: {
    label: 'Verify',
    role: 'warn',
    icon: 'shield',
    gloss: 'Elevated risk — step-up verification before proceeding.',
  },
  HOLD: {
    label: 'Hold',
    role: 'danger',
    icon: 'stop',
    gloss: 'High risk — block and route to a human analyst.',
  },
}

export const metaFor = (decision) =>
  DECISION_META[decision] || { label: decision || '—', role: 'muted', icon: 'dot', gloss: '' }

// risk score -> which risk colour + a word
export function riskBand(score) {
  if (score == null) return { key: 'unknown', label: 'Unknown', varName: '--ink-muted' }
  if (score >= 0.9) return { key: 'high', label: 'Critical', varName: '--risk-high' }
  if (score >= 0.3) return { key: 'mid', label: 'Elevated', varName: '--risk-mid' }
  return { key: 'low', label: 'Low', varName: '--risk-low' }
}

export const FAILURE_LABEL = {
  temporary: 'Temporary',
  payment_method: 'Payment method',
  user_related: 'User-related',
  suspicious: 'Suspicious',
  none: '—',
}
