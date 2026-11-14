/**
 * ErrorBoundary — catches render-time crashes and shows the actual error.
 *
 * Without this, any uncaught exception inside a page unmounts the whole React
 * tree and the user sees a blank screen (the "everything goes black" symptom)
 * with zero diagnostics. With it, the error message and component stack are
 * rendered, plus a Reload button.
 *
 * React class component — hooks-based error boundaries do not exist.
 */

import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Also surface it as a toast if the provider is above this boundary.
    this.props.onError?.(error, info)
    if (typeof console !== 'undefined') {
      console.error('Render error caught by ErrorBoundary:', error, info?.componentStack)
    }
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>Something went wrong</h1>
            <p className="kg-subtitle">
              The page crashed while rendering. The error details below help diagnose it.
            </p>
          </div>
        </div>

        <div
          className="kg-card"
          style={{ borderColor: 'var(--kg-danger)', background: 'var(--kg-danger-soft)' }}
        >
          <strong style={{ color: 'var(--kg-danger)' }}>
            {error?.message || String(error)}
          </strong>
          {info?.componentStack ? (
            <pre style={{ marginTop: 'var(--kg-space-3)', whiteSpace: 'pre-wrap' }}>
              {info.componentStack}
            </pre>
          ) : null}
        </div>

        <div className="kg-btn-group">
          <button
            type="button"
            className="kg-btn kg-btn--primary"
            onClick={() => this.setState({ error: null, info: null })}
          >
            Try again
          </button>
          <button
            type="button"
            className="kg-btn kg-btn--secondary"
            onClick={() => window.location.assign('/')}
          >
            Go to dashboard
          </button>
        </div>
      </div>
    )
  }
}
