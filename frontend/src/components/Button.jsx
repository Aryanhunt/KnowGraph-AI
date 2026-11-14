/**
 * Button — the single button primitive.
 *
 * Variants/sizes come from the design system (`components/ui.css`), so the visual
 * language can change without editing this component or its callers.
 */

import './ui.css'

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  block = false,
  loading = false,
  disabled = false,
  type = 'button',
  icon = null,
  className = '',
  ...rest
}) {
  const classes = [
    'kg-btn',
    `kg-btn--${variant}`,
    size === 'sm' ? 'kg-btn--sm' : size === 'lg' ? 'kg-btn--lg' : '',
    block ? 'kg-btn--block' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button type={type} className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <span className="kg-spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  )
}

/** A row of buttons with consistent spacing. */
export function ButtonGroup({ children }) {
  return <div className="kg-btn-group">{children}</div>
}