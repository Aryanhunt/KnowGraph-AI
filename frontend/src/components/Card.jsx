/**
 * Card — the container used by every page.
 *
 * Composable parts (Header/Title/Subtitle/Footer) keep layouts consistent, and all
 * visual styling comes from the design system rather than from page code.
 */

import './ui.css'

export default function Card({
  children,
  interactive = false,
  flat = false,
  large = false,
  className = '',
  onClick,
  ...rest
}) {
  const classes = [
    'kg-card',
    interactive ? 'kg-card--interactive' : '',
    flat ? 'kg-card--flat' : '',
    large ? 'kg-card--lg' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={classes}
      onClick={onClick}
      role={interactive && onClick ? 'button' : undefined}
      tabIndex={interactive && onClick ? 0 : undefined}
      onKeyDown={
        interactive && onClick
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') onClick(event)
            }
          : undefined
      }
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({ title, subtitle, actions, children }) {
  return (
    <div className="kg-card__header">
      <div className="kg-grow">
        {title ? <div className="kg-card__title">{title}</div> : null}
        {subtitle ? <p className="kg-card__subtitle">{subtitle}</p> : null}
        {children}
      </div>
      {actions ? <div className="kg-row-wrap">{actions}</div> : null}
    </div>
  )
}

export function CardFooter({ children, left }) {
  return (
    <div className="kg-card__footer">
      <div className="kg-row-wrap">{left}</div>
      <div className="kg-row-wrap">{children}</div>
    </div>
  )
}