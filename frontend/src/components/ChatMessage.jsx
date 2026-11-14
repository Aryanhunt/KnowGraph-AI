/**
 * ChatMessage — one turn of the conversation (brief §7, §8).
 *
 * The most important visual rule: it must be obvious whether an answer came from
 * the user's documents or from General AI. That is driven by the backend's
 * `based_on_documents` flag, never guessed by the frontend.
 */

import Badge from './Badge'
import { SourceList } from './SourceCitation'
import './ChatMessage.css'

/**
 * Minimal, safe "markdown" renderer.
 *
 * Supports **bold**, `inline code`, bullet lists and numbered lists — the only
 * formatting the prompts ask the model to produce. Text is returned as React
 * elements (no dangerouslySetInnerHTML), so model output cannot inject HTML.
 */
function renderInline(text, keyPrefix) {
  const parts = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let lastIndex = 0
  let match
  let index = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index))
    const token = match[0]
    index += 1
    if (token.startsWith('**')) {
      parts.push(<strong key={`${keyPrefix}-b${index}`}>{token.slice(2, -2)}</strong>)
    } else {
      parts.push(
        <code key={`${keyPrefix}-c${index}`} className="kg-mono">
          {token.slice(1, -1)}
        </code>,
      )
    }
    lastIndex = match.index + token.length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

function renderContent(content) {
  const lines = String(content || '').split('\n')
  const blocks = []
  let list = null

  lines.forEach((line, lineIndex) => {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)$/)

    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      const text = ordered ? numbered[2] : bullet[1]
      if (!list || list.ordered !== ordered) {
        list = { ordered, items: [] }
        blocks.push(list)
      }
      list.items.push(text)
      return
    }

    list = null
    if (line.trim() === '') {
      blocks.push({ spacer: true, key: `sp-${lineIndex}` })
      return
    }
    blocks.push({ text: line, key: `p-${lineIndex}` })
  })

  return blocks.map((block, position) => {
    if (block.spacer) return <div key={block.key} className="kg-msg__spacer" />
    if (block.items) {
      const Tag = block.ordered ? 'ol' : 'ul'
      return (
        <Tag key={`list-${position}`} className="kg-msg__list">
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item, `li-${position}-${itemIndex}`)}</li>
          ))}
        </Tag>
      )
    }
    return (
      <p key={block.key} className="kg-msg__paragraph">
        {renderInline(block.text, block.key)}
      </p>
    )
  })
}

export default function ChatMessage({ message, pending = false }) {
  const item = message || {}
  const isUser = item.role === 'user'
  const fromDocuments = item.based_on_documents !== false

  return (
    <div className={`kg-msg kg-msg--${isUser ? 'user' : 'assistant'}`}>
      <div className="kg-msg__avatar" aria-hidden="true">
        {isUser ? '🧑' : '🤖'}
      </div>

      <div className="kg-msg__bubble">
        <div className="kg-msg__head">
          <span className="kg-text-xs kg-text-muted">{isUser ? 'You' : 'KnowGraph AI'}</span>
          {!isUser ? (
            fromDocuments ? (
              <Badge tone="success" title="Answer built from your uploaded documents">
                Based on your documents
              </Badge>
            ) : (
              <Badge tone="warning" title="No document retrieval was used for this answer">
                General AI — not from your documents
              </Badge>
            )
          ) : null}
          {item.mode ? <Badge tone="neutral">{item.mode}</Badge> : null}
        </div>

        <div className="kg-msg__content">
          {pending ? (
            <span className="kg-text-muted kg-text-sm">Thinking with the local model…</span>
          ) : (
            renderContent(item.content)
          )}
        </div>

        {!isUser && (item.sources || []).length ? <SourceList sources={item.sources} /> : null}

        {!isUser && item.retrieval?.hits !== undefined ? (
          <div className="kg-text-xs kg-text-muted kg-msg__meta">
            retrieved {item.retrieval.hits} chunk(s)
            {item.retrieval.top_score !== undefined && item.retrieval.top_score !== null
              ? ` · best score ${Number(item.retrieval.top_score).toFixed(3)}`
              : ''}
            {item.model ? ` · model ${item.model}` : ''}
          </div>
        ) : null}
      </div>
    </div>
  )
}