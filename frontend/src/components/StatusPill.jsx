/**
 * StatusPill — document processing status with progress.
 *
 * Labels and tones come from `theme/index.js`, which mirrors the statuses the
 * backend reports, so the UI never invents its own vocabulary (brief §4).
 */

import { DotBadge } from './Badge'
import ProgressBar from './ProgressBar'
import { statusMeta } from '../theme'

export default function StatusPill({ status, stageLabel, progress, error, compact = false }) {
  const meta = statusMeta(status)
  const isRunning = status !== 'completed' && status !== 'failed'
  const percent = Math.round((Number(progress) || 0) * 100)

  return (
    <div className="kg-stack-sm" style={{ gap: 'var(--kg-space-1)' }}>
      <DotBadge tone={meta.tone} pulse={isRunning}>
        {stageLabel || meta.label}
      </DotBadge>

      {isRunning && !compact && percent > 0 ? (
        <ProgressBar value={percent} tone="info" label={false} />
      ) : null}

      {status === 'failed' && error ? (
        <span className="kg-text-xs" style={{ color: 'var(--kg-danger)' }}>
          {error}
        </span>
      ) : null}
    </div>
  )
}