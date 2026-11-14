/**
 * DocumentCard — one document in the library, with live processing status.
 *
 * Shows exactly what the backend knows: file type, size, pages, chunks, whether
 * OCR was used and the current pipeline stage (brief §4, §5).
 */

import Badge from './Badge'
import Button from './Button'
import StatusPill from './StatusPill'
import './DocumentCard.css'

const FILE_ICONS = {
  pdf: 'PDF',
  docx: 'DOC',
  txt: 'TXT',
  md: 'MD',
  png: 'IMG',
  jpg: 'IMG',
  jpeg: 'IMG',
  webp: 'IMG',
  tif: 'IMG',
  tiff: 'IMG',
  bmp: 'IMG',
}

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(value)
  }
}

export default function DocumentCard({
  document,
  selected = false,
  selectable = false,
  onToggleSelect,
  onOpen,
  onReprocess,
  onDelete,
}) {
  const item = document || {}
  const icon = FILE_ICONS[item.file_type] || (item.file_type || 'FILE').toUpperCase()
  const isReady = item.processing_status === 'completed'
  const isFailed = item.processing_status === 'failed'

  return (
    <div className="kg-doc-card">
      <div className="kg-doc-card__top">
        {selectable ? (
          <label className="kg-checkbox kg-doc-card__check">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect?.(item.id)}
              aria-label={`Select ${item.title}`}
            />
          </label>
        ) : null}

        <div className={`kg-doc-card__icon kg-doc-card__icon--${(item.file_type || 'file').slice(0, 4)}`}>
          {icon}
        </div>

        <div className="kg-grow">
          <button type="button" className="kg-doc-card__title" onClick={() => onOpen?.(item)}>
            {item.title || item.original_filename || 'Untitled document'}
          </button>
          <div className="kg-text-xs kg-text-muted kg-truncate">{item.original_filename}</div>
        </div>

        <StatusPill
          status={item.processing_status}
          stageLabel={item.stage_label}
          progress={item.progress}
          error={item.processing_error}
          compact
        />
      </div>

      {item.summary ? <p className="kg-doc-card__summary kg-clamp-3">{item.summary}</p> : null}

      {isFailed && item.processing_error ? (
        <div className="kg-doc-card__error" role="alert">
          {item.processing_error}
        </div>
      ) : null}

      <div className="kg-row-wrap kg-doc-card__meta">
        <Badge tone="neutral">{item.file_size_label || '—'}</Badge>
        <Badge tone="neutral">{item.page_count || 0} page(s)</Badge>
        <Badge tone="neutral">{item.chunk_count || 0} chunks</Badge>
        {item.ocr_used ? (
          <Badge tone="warning" title="This document needed OCR on at least one page">
            OCR
          </Badge>
        ) : null}
        {item.subject ? <Badge tone="primary">{item.subject}</Badge> : null}
        {item.is_research_paper ? <Badge tone="info">Research paper</Badge> : null}
        {item.summary_method ? (
          <Badge tone={item.summary_method === 'llm' ? 'success' : 'neutral'}>
            summary: {item.summary_method}
          </Badge>
        ) : null}
      </div>

      {(item.topics || []).length ? (
        <div className="kg-row-wrap kg-doc-card__topics">
          {(item.topics || []).slice(0, 6).map((topic) => (
            <Badge key={topic} tone="neutral">
              {topic}
            </Badge>
          ))}
        </div>
      ) : null}

      <div className="kg-doc-card__footer">
        <span className="kg-text-xs kg-text-muted">Uploaded {formatDate(item.upload_date)}</span>
        <div className="kg-row-wrap">
          {isReady || isFailed ? (
            <Button size="sm" variant="secondary" onClick={() => onOpen?.(item)}>
              Open
            </Button>
          ) : null}
          {onReprocess ? (
            <Button size="sm" variant="ghost" onClick={() => onReprocess(item)}>
              Reprocess
            </Button>
          ) : null}
          {onDelete ? (
            <Button size="sm" variant="ghost" onClick={() => onDelete(item)}>
              Delete
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}