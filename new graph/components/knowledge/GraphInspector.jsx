'use client'

import { ArrowRight, BookOpen, CircleDot, Compass, FileText, ShieldCheck, X } from 'lucide-react'
import { displayRelation } from './graph-theme'

export default function GraphInspector({ graph, selectedSlug, selectedEdge, onSelect, onClear, isPreview }) {
  const node = graph.nodes.find((item) => item.id === selectedSlug)
  const related = graph.edges.filter((edge) => edge.source === selectedSlug || edge.target === selectedSlug)
  const byId = new Map(graph.nodes.map((item) => [item.id, item]))
  return <aside className="kg-inspector" aria-label="Graph inspector">
    <div className="kg-inspector-heading"><span><Compass size={15} /> {node ? 'Concept details' : selectedEdge ? 'Relationship details' : 'Your discovery starts here'}</span>{(node || selectedEdge) && <button aria-label="Close inspector" onClick={onClear}><X size={14} /></button>}</div>
    {node ? <>
      <div className="kg-inspector-body"><span className="kg-eyebrow">{node.subject || 'CONCEPT'}</span><h2>{node.label}</h2><p>{node.definition || 'No definition recorded for this concept.'}</p><div className="kg-detail-stats"><span><b>{related.length}</b> connections</span><span><b>{node.document_count || 0}</b> sources</span></div></div>
      <div className="kg-inspector-section"><h3>Connected concepts <span>{related.length}</span></h3><div className="kg-related-list">{related.map((edge, index) => {
        const incoming = edge.target === selectedSlug
        const id = incoming ? edge.source : edge.target
        return <button key={edge.id || index} onClick={() => onSelect(id)}><CircleDot size={13} /><span>{byId.get(id)?.label || id}<small>{incoming ? 'Incoming' : 'Outgoing'} · {displayRelation(edge.relation)}</small></span><ArrowRight size={12} /></button>
      })}{!related.length && <p>No connections match the current filters.</p>}</div></div>
      <div className="kg-inspector-section"><h3><FileText size={12} /> Found in</h3>{(node.documents || []).length ? node.documents.map((document, i) => <p className="kg-source" key={i}>{document.title || document.document_title || 'Untitled source'}</p>) : <p>No source information in this graph export.</p>}</div>
    </> : selectedEdge ? <>
      <div className="kg-inspector-body"><span className="kg-eyebrow">DIRECTED RELATIONSHIP</span><h2>{byId.get(selectedEdge.source)?.label || selectedEdge.source}</h2><div className="kg-relation-direction"><ArrowRight size={14} />{displayRelation(selectedEdge.relation)}</div><h2>{byId.get(selectedEdge.target)?.label || selectedEdge.target}</h2><div className="kg-detail-stats"><span><b>{Math.round(Number(selectedEdge.confidence || 0) * 100)}%</b> confidence</span></div><span className="kg-status-pill"><ShieldCheck size={12} />{selectedEdge.verification_status || 'uncertain'}</span></div>
      <div className="kg-inspector-section"><h3>Supporting evidence</h3>{Array.isArray(selectedEdge.evidence) && selectedEdge.evidence.length ? selectedEdge.evidence.map((item, i) => <blockquote key={i}>{typeof item === 'string' ? item : item.snippet || item.document_title}</blockquote>) : <p>No supporting evidence in this graph export.</p>}<p className="kg-preview-note">Verification actions remain in your existing app.</p></div>
    </> : <>
      <div className="kg-inspector-empty"><span className="kg-inspector-illustration"><NetworkIllustration /></span><h2>A little curiosity.<br />A lot of connections.</h2><p>Select a concept to explore its meaning, sources, and how it connects to everything else.</p></div>
      <div className="kg-inspector-section"><h3>Try a starting point</h3>{[...graph.nodes].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 3).map((item) => <button className="kg-starting-point" key={item.id} onClick={() => onSelect(item.id)}><CircleDot size={12} /><span>{item.label}</span><ArrowRight size={12} /></button>)}</div>
      <div className="kg-inspector-tip"><BookOpen size={16} /><div><strong>Follow the connections</strong><p>Click a concept, then use focus depth to explore one or two steps beyond it.</p></div></div>
    </>}
    {isPreview && <div className="kg-inspector-preview"><span className="kg-live-dot" /> Illustrative data · not your documents</div>}
  </aside>
}
function NetworkIllustration() {
  return <Compass size={34} strokeWidth={1} />
}
