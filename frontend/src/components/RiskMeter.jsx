import { riskBand } from '../lib/decisions.js'
import './RiskMeter.css'

/**
 * Compact risk-score readout: a segmented track that fills to `score`,
 * coloured by band, with the numeric value alongside. Used in stream rows
 * and (larger) on the investigation page.
 */
export function RiskMeter({ score, variant = 'inline' }) {
  const band = riskBand(score)
  const pctFill = score == null ? 0 : Math.max(2, Math.min(100, score * 100))
  return (
    <div className={`riskmeter riskmeter--${variant}`} title={`Risk score ${score == null ? 'n/a' : score.toFixed(4)}`}>
      <div className="riskmeter__track">
        <div
          className="riskmeter__fill"
          style={{ width: `${pctFill}%`, background: `var(${band.varName})` }}
        />
      </div>
      <div className="riskmeter__value">
        <span className="tnum" style={{ color: `var(${band.varName})` }}>
          {score == null ? '—' : score.toFixed(2)}
        </span>
        {variant === 'block' && <span className="riskmeter__band">{band.label}</span>}
      </div>
    </div>
  )
}
