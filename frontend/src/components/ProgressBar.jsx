/**
 * ProgressBar — used by the upload/processing UI and the knowledge-progress view.
 *
 * `value` is a real 0-100 number produced by the backend (processing progress) or
 * by counting recorded answers (topic accuracy). Nothing here is decorative
 * guesswork (brief §11/§15).
 */

import './forms.css'

export default function ProgressBar({ value = 0, tone = 'primary', label = true, caption = null }) {
  const clamped = Math.max(0, Math.min(100, Number(value) || 0))
  const toneClass = tone && tone !== 'primary' ? ` kg-progress__fill--${tone}` : ''

  return (
    <div>
      {label ? (
        <div className="kg-progress__label">
          <span>{caption || ''}</span>
          <span>{clamped}%</span>
        </div>
      ) : null}
      <div
        className="kg-progress"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={caption || 'Progress'}
      >
        <div className={`kg-progress__fill${toneClass}`} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  )
}