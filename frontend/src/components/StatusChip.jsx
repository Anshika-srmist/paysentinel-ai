import { Icon } from './Icon.jsx'
import { metaFor } from '../lib/decisions.js'
import './StatusChip.css'

/** Decision pill — always icon + label, never colour alone. */
export function StatusChip({ decision, size = 'md' }) {
  const meta = metaFor(decision)
  return (
    <span className={`chip chip--${meta.role} chip--${size}`}>
      <Icon name={meta.icon} size={size === 'sm' ? 13 : 15} strokeWidth={2} />
      {meta.label}
    </span>
  )
}
