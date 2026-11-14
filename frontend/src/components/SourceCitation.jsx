/**
 * SourceCitation — one clickable source under an answer or a search result
 * (brief §7, §15).
 *
 * Shows the document title and page, plus the retrieval score *only* when the
 * backend actually produced one (`score` is the cosine similarity or the RRF
 * score) — no invented relevance numbers.
 */

import { Link } from 'react-router-dom'
import Badge from './Badge'
import './SourceCitation.css'

export default function SourceCitation({ source, index, relevance, showScore = false }) {
  const item = source || {}
  const target =
    item.document_id && item.page_number
      ? `/documents/${item.document_id}?page=${item.page_number}`
      : item.document_id
        ? `/documents/${item.document_id}`
        : null

  const label = `${item.title || 'Untitled document'}${item.page_number ? ` — page ${item.page_number}` : ''}`

  const body = (
    <>
      <span className="kg-citation__icon" aria-hidden="true">
        📄
      </span>
      <span className="kg-citation__main">
        <span className="kg-citation__label kg-truncate">{label}</span>
        {item.snippet ? <span className="kg-citation__snippet kg-clamp-2">{item.snippet}</span> : null}
      </span>
      <span className="kg-citation__meta">
        {item.cited ? <Badge tone="success">cited</Badge> : null}
        {relevance ? <Badge tone="neutral">{relevance}</Badge> : null}
        {item.source_type ? <Badge tone="neutral">{item.source_type}</Badge> : null}
        {showScore && typeof item.score === 'number' ? (
          <Badge tone="neutral" title="Retrieval score returned by the search engine">
            {item.score.toFixed(3)}
          </Badge>
        ) : null}
      </span>
    </>
  )

  if (!target) {
    return (
      <div className="kg-citation">
        {index !== undefined ? <span className="kg-citation__index">[{index}]</span> : null}
        {body}
      </div>
    )
  }

  return (
    <Link className="kg-citation kg-citation--link" to={target}>
      {index !== undefined ? <span className="kg-citation__index">[{index}]</span> : null}
      {body}
    </Link>
  )
}

/** A titled list of citations (used by the chat answer and search results). */
export function SourceList({ sources = [], title = 'Sources', showScore = false }) {
  if (!sources.length) return null
  return (
    <div className="kg-sources">
      <div className="kg-text-xs kg-text-muted">{title}</div>
      <div className="kg-stack-sm">
        {sources.map((source, position) => (
          <SourceCitation
            key={source.chunk_id || source.document_id + position}
            source={source}
            index={source.index ?? position + 1}
            relevance={source.relevance}
            showScore={showScore}
          />
        ))}
      </div>
    </div>
  )
}