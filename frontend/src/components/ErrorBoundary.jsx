import { Component } from 'react'
import { Icon } from './Icon.jsx'

// Last-resort safety net. React only calls componentDidCatch for errors
// thrown while rendering — it can't catch async/event-handler errors (those
// are handled per-page via usePolling + an .errbar, which is deliberate:
// this boundary is specifically for the case those can't cover, an
// unexpected crash mid-render, so the dashboard shows a recoverable card
// instead of going to a blank white screen.
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary] render crash:', error, info?.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: 'var(--canvas)' }}>
        <div className="card card-pad" style={{ maxWidth: 440, textAlign: 'center' }}>
          <Icon name="alert" size={28} strokeWidth={1.75} style={{ color: 'var(--danger)', marginBottom: 12 }} />
          <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>Something went wrong</h2>
          <p className="muted" style={{ fontSize: 13.5, marginBottom: 18 }}>
            This screen hit an unexpected error. The rest of PaySentinel is unaffected — reloading this page will
            recover it. If it keeps happening, note what you clicked right before this appeared.
          </p>
          <button className="btn-primary" style={{ margin: '0 auto' }} onClick={() => window.location.reload()}>
            Reload <Icon name="refresh" size={14} strokeWidth={2} />
          </button>
        </div>
      </div>
    )
  }
}
