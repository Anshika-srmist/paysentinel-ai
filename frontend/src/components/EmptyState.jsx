import { Icon } from './Icon.jsx'

export function EmptyState({ icon = 'activity', title, hint, action }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center',
      gap: 10, padding: '48px 24px', color: 'var(--ink-secondary)',
    }}>
      <span style={{
        display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12,
        background: 'var(--surface-sunken)', color: 'var(--ink-muted)', border: '1px solid var(--border)',
      }}>
        <Icon name={icon} size={20} />
      </span>
      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{title}</div>
      {hint && <div className="muted" style={{ maxWidth: 320, fontSize: 13 }}>{hint}</div>}
      {action}
    </div>
  )
}
