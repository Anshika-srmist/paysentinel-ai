import { NavLink } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Icon } from './Icon.jsx'
import { api } from '../api/client.js'
import './AppShell.css'

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/stream', label: 'Live stream', icon: 'activity' },
  { to: '/check', label: 'Live check', icon: 'bolt' },
  { to: '/investigation', label: 'Investigation', icon: 'search' },
  { to: '/policy', label: 'Policy', icon: 'layers' },
]

function ApiStatus() {
  const [state, setState] = useState({ status: 'checking', model: null })
  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const h = await api.health()
        if (alive) setState({ status: 'ok', model: h.model_name })
      } catch {
        if (alive) setState({ status: 'down', model: null })
      }
    }
    check()
    const t = setInterval(check, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  return (
    <div className={`apistatus apistatus--${state.status}`}>
      <span className="apistatus__dot" />
      <div>
        <div className="apistatus__line">
          {state.status === 'ok' ? 'API connected' : state.status === 'down' ? 'API unreachable' : 'Connecting…'}
        </div>
        {state.model && <div className="apistatus__sub">Scoring model · {state.model}</div>}
      </div>
    </div>
  )
}

export function AppShell({ children }) {
  const [navOpen, setNavOpen] = useState(false)
  return (
    <div className="shell">
      <aside className={`shell__nav ${navOpen ? 'is-open' : ''}`}>
        <div className="brand">
          <span className="brand__mark">
            <Icon name="shield" size={19} strokeWidth={2.1} />
          </span>
          <span className="brand__text">
            <span className="brand__name">Pay<span>Sentinel</span></span>
            <em>AI Risk Manager</em>
          </span>
        </div>

        <nav className="nav" onClick={() => setNavOpen(false)}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav__item ${isActive ? 'is-active' : ''}`}
            >
              <Icon name={item.icon} size={18} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="shell__nav-foot">
          <ApiStatus />
        </div>
      </aside>

      <button className="shell__scrim" hidden={!navOpen} onClick={() => setNavOpen(false)} aria-label="Close menu" />

      <div className="shell__main">
        <button className="shell__burger" onClick={() => setNavOpen((v) => !v)} aria-label="Menu">
          <Icon name="layers" size={20} />
        </button>
        {children}
      </div>
    </div>
  )
}

/** Header row used at the top of every page. */
export function PageHeader({ title, subtitle, right }) {
  return (
    <header className="pagehead">
      <div>
        <h1 className="pagehead__title">{title}</h1>
        {subtitle && <p className="pagehead__sub">{subtitle}</p>}
      </div>
      {right && <div className="pagehead__right">{right}</div>}
    </header>
  )
}

export function LiveBadge({ lastUpdated, onRefresh, stale }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const secs = lastUpdated ? Math.round((Date.now() - lastUpdated) / 1000) : null
  return (
    <div className="livebadge">
      <span className={`livebadge__pill ${stale ? 'is-stale' : ''}`}>
        <span className="livebadge__dot" />
        {stale ? 'Reconnecting' : 'Live'}
      </span>
      {secs != null && <span className="livebadge__time">updated {secs === 0 ? 'now' : `${secs}s ago`}</span>}
      {onRefresh && (
        <button className="livebadge__refresh" onClick={onRefresh} title="Refresh now">
          <Icon name="refresh" size={15} strokeWidth={2} />
        </button>
      )}
    </div>
  )
}
