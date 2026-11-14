/**
 * GraphInspector — the right-hand side panel.
 *
 * Renders one of three states:
 *   1. No selection -> a welcoming "start here" view.
 *   2. A node is selected -> concept detail (definition, related concepts, sources).
 *   3. An edge is selected -> relationship evidence with verify / reject actions.
 *
 * When `detail` / `edgeReport` are supplied (fetched from the backend API), they
 * take priority over the raw graph data so the inspector always shows the richest
 * available information.
 */

import { ArrowRight, BookOpen, CircleDot, Compass, FileText, ShieldCheck, X, Network } from 'lucide-react'
import { displayRelation } from './graph-theme'

export default function GraphInspector({
  graph,
  selectedSlug,
  selectedEdge,
  onSelect,
  onClear,
  isPreview,
  detail,
  detailLoading,
  edgeReport,
  edgeReportLoading,
  onVerifyEdge,
  acting,
}) {
  // Use API-loaded detail when available, otherwise fall back to the graph node.
  const node = detail || graph.nodes.find((item) => item.id === selectedSlug)
  const related = (detail && detail.related && detail.related.length)
    ? detail.related
    : graph.edges.filter((edge) => edge.source === selectedSlug || edge.target === selectedSlug)

  const byId = new Map(graph.nodes.map((item) => [item.id, item]))

  return (
    <aside className="kg-inspector" aria-label="Graph inspector">
      <div className="kg-inspector-heading">
        <span>
          <Compass size={15} />
          {' '}
          {node ? 'Concept details' : selectedEdge ? 'Relationship details' : 'Your discovery starts here'}
        </span>
        {(node || selectedEdge) && (
          <button aria-label="Close inspector" onClick={onClear}>
            <X size={14} />
          </button>
        )}
      </div>

      {node ? (
        <>
          <div className="kg-inspector-body">
            <span className="kg-eyebrow">
              {(detail ? detail.subject : node.subject) || 'CONCEPT'}
            </span>
            <h2>{detail ? detail.label : node.label}</h2>
            {detailLoading ? (
              <p className="kg-text-sm kg-text-muted">Loading…</p>
            ) : (
              <p>{detail ? (detail.definition || node.definition) : (node.definition || 'No definition recorded for this concept.')}</p>
            )}
            <div className="kg-detail-stats">
              <span>
                <b>{related.length}</b>
                <small>connections</small>
              </span>
              <span>
                <b>{(detail || node).document_count || 0}</b>
                <small>sources</small>
              </span>
            </div>
          </div>

          <div className="kg-inspector-section">
            <h3>Connected concepts <span>{related.length}</span></h3>
            <div className="kg-related-list">
              {related.map((item, index) => {
                const isApi = !!item.slug
                const id = isApi
                  ? item.slug
                  : (item.target === selectedSlug ? item.source : item.source === selectedSlug ? item.target : item.id)
                const label = isApi ? item.label : (byId.get(id)?.label || id)
                const relation = item.relation
                const direction = isApi ? item.direction : (item.target === selectedSlug ? 'incoming' : 'outgoing')
                return (
                  <button key={isApi ? `${item.slug}-${index}` : (item.id || index)} onClick={() => onSelect(id)}>
                    <CircleDot size={13} />
                    <span>
                      {label}
                      <small>{direction} · {displayRelation(relation)}</small>
                    </span>
                    <ArrowRight size={12} />
                  </button>
                )
              })}
              {!related.length && <p>No connections match the current filters.</p>}
            </div>
          </div>

          <div className="kg-inspector-section">
            <h3><FileText size={12} /> Found in</h3>
            {(() => {
              const sources = detail ? detail.sources : node.documents || []
              if (!sources || !sources.length) return <p>No source information in this graph export.</p>
              // Collapse duplicate document+page rows into one line per document.
              const byDoc = new Map()
              sources.forEach((item) => {
                const id = item.document_id || item.title || item.document_title
                const entry = byDoc.get(id) || { title: item.title || item.document_title || 'Untitled source', pages: new Set() }
                if (item.page_number) entry.pages.add(item.page_number)
                byDoc.set(id, entry)
              })
              return Array.from(byDoc.values()).map((doc, i) => {
                const pages = Array.from(doc.pages).sort((a, b) => a - b).slice(0, 12)
                return (
                  <p className="kg-source" key={i}>
                    {doc.title}
                    {pages.length ? ` — pages ${pages.join(', ')}` : ''}
                  </p>
                )
              })
            })()}
          </div>
        </>
      ) : selectedEdge ? (
        <>
          <div className="kg-inspector-body">
            <span className="kg-eyebrow">DIRECTED RELATIONSHIP</span>
            {edgeReport ? (
              <>
                <h2>{edgeReport.source.label || edgeReport.source.slug}</h2>
                <div className="kg-relation-direction">
                  <ArrowRight size={14} />
                  {displayRelation(edgeReport.relation)}
                </div>
                <h2>{edgeReport.target.label || edgeReport.target.slug}</h2>
              </>
            ) : (
              <>
                <h2>{byId.get(selectedEdge.source)?.label || selectedEdge.source}</h2>
                <div className="kg-relation-direction">
                  <ArrowRight size={14} />
                  {displayRelation(selectedEdge.relation)}
                </div>
                <h2>{byId.get(selectedEdge.target)?.label || selectedEdge.target}</h2>
              </>
            )}
            <div className="kg-detail-stats">
              <span>
                <b>{Math.round(Number(edgeReport ? edgeReport.confidence : selectedEdge.confidence || 0) * 100)}%</b>
                <small>confidence</small>
              </span>
            </div>
            <span className="kg-status-pill">
              <ShieldCheck size={12} />
              {edgeReport ? edgeReport.verification_status || 'uncertain' : selectedEdge.verification_status || 'uncertain'}
            </span>
          </div>

          <div className="kg-inspector-section">
            <h3>Supporting evidence</h3>
            {edgeReportLoading ? (
              <p>Loading evidence…</p>
            ) : (
              <EvidenceList
                items={edgeReport ? edgeReport.evidence : (selectedEdge.evidence || selectedEdge.documents)}
                isEdge={!!edgeReport}
                rawEdge={selectedEdge}
              />
            )}
          </div>

          <div className="kg-inspector-section">
            <h3><ShieldCheck size={12} /> Verification</h3>
            <div style={{ display: 'flex', gap: 'var(--kg-space-2)', flexWrap: 'wrap' }}>
              <button
                className="kg-graph-button kg-graph-button--primary"
                onClick={() => onVerifyEdge('verified')}
                disabled={acting}
              >
                {acting ? 'Saving…' : 'Verify'}
              </button>
              <button
                className="kg-graph-button kg-graph-button--secondary"
                onClick={() => onVerifyEdge('rejected')}
                disabled={acting}
              >
                {acting ? 'Saving…' : 'Hide (reject)'}
              </button>
            </div>
            <p className="kg-text-xs kg-text-muted" style={{ marginTop: 'var(--kg-space-2)' }}>
              Verifying strengthens the relationship. Rejecting hides it (the edge is not deleted).
            </p>
          </div>
        </>
      ) : (
        <>
          <div className="kg-inspector-empty">
            <span className="kg-inspector-illustration"><NetworkIllustration /></span>
            <h2>A little curiosity.<br />A lot of connections.</h2>
            <p>Select a concept to explore its meaning, sources, and how it connects to everything else.</p>
          </div>
          <div className="kg-inspector-section">
            <h3>Try a starting point</h3>
            {[...graph.nodes]
              .sort((a, b) => (b.score || 0) - (a.score || 0))
              .slice(0, 3)
              .map((item) => (
                <button className="kg-starting-point" key={item.id} onClick={() => onSelect(item.id)}>
                  <CircleDot size={12} />
                  <span>{item.label}</span>
                  <ArrowRight size={12} />
                </button>
              ))}
          </div>
          <div className="kg-inspector-tip">
            <BookOpen size={16} />
            <div>
              <strong>Follow the connections</strong>
              <p>Click a concept, then use focus depth to explore one or two steps beyond it.</p>
            </div>
          </div>
        </>
      )}

      {isPreview && (
        <div className="kg-inspector-preview">
          <span className="kg-live-dot" /> Illustrative data · not your documents
        </div>
      )}
    </aside>
  )
}

function EvidenceList({ items, isEdge, rawEdge }) {
  if (!items || items.length === 0) {
    // Fallback: try to show edge documents from the graph data
    if (rawEdge && rawEdge.documents && rawEdge.documents.length > 0) {
      return rawEdge.documents.map((item, i) => (
        <blockquote key={i}>
          {item.title || item.document_title || 'No snippet available'}
          {item.page_number ? ` (page ${item.page_number})` : ''}
        </blockquote>
      ))
    }
    return <p>No supporting evidence in this graph export.</p>
  }
  return items.map((item, i) => (
    <blockquote key={i}>
      {item.snippet ? `"${item.snippet}"` : (item.document_title || item.title || 'No snippet available')}
      {item.document_title && !item.snippet ? ` — ${item.document_title}` : ''}
      {item.page_number ? ` (page ${item.page_number})` : ''}
    </blockquote>
  ))
}

function NetworkIllustration() {
  return <Network size={34} strokeWidth={1} />
}
