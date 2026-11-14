/**
 * Small feedback primitives: Spinner, LoadingBlock, EmptyState and Alert.
 *
 * Alert is the component that carries the backend's `hint` to the user, which is
 * how messages like "Ollama is not running. Please start Ollama and try again."
 * reach the screen (brief §22).
 */

import './forms.css'

export function Spinner({ large = false, className = '' }) {
  return <span className={`kg-spinner${large ? ' kg-spinner--lg' : ''} ${className}`.trim()} aria-hidden="true" />
}

export function LoadingBlock({ message = 'Loading…' }) {
  return (
    <div className="kg-loading-block" role="status">
      <Spinner />
      <span>{message}</span>
    </div>
  )
}

export function EmptyState({ title, description, action, icon = '◦' }) {
  return (
    <div className="kg-empty">
      <div style={{ fontSize: '1.6rem', lineHeight: 1 }} aria-hidden="true">
        {icon}
      </div>
      <div className="kg-empty__title">{title}</div>
      {description ? <div className="kg-text-sm">{description}</div> : null}
      {action}
    </div>
  )
}

export function Alert({ tone = 'info', title, hint, children, actions }) {
  return (
    <div className={`kg-alert kg-alert--${tone}`} role="alert">
      <div className="kg-alert__body kg-grow">
        {title ? <span className="kg-alert__title">{title}</span> : null}
        {hint ? <span className="kg-alert__hint">{hint}</span> : null}
        {children}
      </div>
      {actions ? <div className="kg-row-wrap">{actions}</div> : null}
    </div>
  )
}