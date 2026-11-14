/**
 * Badge — small status/count label. Tones map to design tokens, so restyling is
 * a theme change, not a component change.
 */

import './ui.css'

export default function Badge({ children, tone = 'neutral', className = '', title }) {
  return (
    <span className={`kg-badge kg-badge--${tone} ${className}`.trim()} title={title}>
      {children}
    </span>
  )
}

/** A badge with a coloured dot, used for live/processing states. */
export function DotBadge({ children, tone = 'neutral', pulse = false }) {
  return (
    <Badge tone={tone}>
      <span className={`kg-dot${pulse ? ' kg-dot--pulse' : ''}`} aria-hidden="true" />
      {children}
    </Badge>
  )
}