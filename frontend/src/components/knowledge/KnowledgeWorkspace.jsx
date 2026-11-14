/**
 * KnowledgeWorkspace — the integrated knowledge-graph page.
 *
 * Exact port of the "new graph" prototype UI (graph explorer tabs,
 * heading, page tabs, help panel, filters, graph/library views,
 * below-graph bar, inspector, footer + collapsible in-page menu) wired to the real
 * KnowGraph AI backend API instead of preview-only data:
 * * Real graph data fetched from /api/graph (falls back to preview data).
 * * Client-side filtering (verification, confidence, topic, search) on the
 *   full graph payload so filter changes are instant.
 * * Concept detail (/api/graph/concepts/:slug), edge evidence
 *   (/api/graph/relations/evidence), verify/reject
 *   (/api/graph/relations/verify), learning path
 *   (/api/graph/learning-path), relationship-file upload
 *   (/api/graph/upload-relations) all preserved from the old Graph page.
 * * JSON import/export additionally applies filters locally for demo data.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowDownToLine, BookOpen, Check, ChevronRight, CircleHelp, FileJson, GitBranch,
  Home, Layers, Menu, Network, Search, ShieldCheck, SlidersHorizontal, Upload, X,
} from 'lucide-react'

import { graphApi } from '../../services'
import { useToast } from '../../context/ToastContext'

const GraphPanel = lazy(() => import('./GraphPanel'))
import GraphInspector from './GraphInspector'
import { previewGraph, filterGraph } from './preview-data'
import './workspace.css'

const VERIFICATION_MODES = [
  { value: 'all', label: 'All relationships' },
  { value: 'verified', label: 'Verified only' },
  { value: 'inferred', label: 'Verified + inferred' },
]

export default function KnowledgeWorkspace() {
  const { fromError, success } = useToast()

  // ---- Core graph data (from backend; preview until loaded) ----
  const [graph, setGraph] = useState(previewGraph)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [backendConnected, setBackendConnected] = useState(false)
  const [status, setStatus] = useState(null)        // graph status (counts)
  const [isPreview, setIsPreview] = useState(true)

  // ---- Filters (client-side on full graph) ----
  const [verification, setVerification] = useState('all')
  const [confidence, setConfidence] = useState(0)
  const [topic, setTopic] = useState('')
  const [query, setQuery] = useState('')

  // ---- Selection ----
  const [selected, setSelected] = useState(null)     // node slug
  const [edge, setEdge] = useState(null)            // edge object

  // ---- New-prototype UI state (restored 1:1) ----
  const [view, setView] = useState('graph')
  const [help, setHelp] = useState(false)
  const [menu, setMenu] = useState(false)
  const fileInput = useRef(null)

  // ---- Concept detail (loaded on demand from API) ----
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // ---- Edge evidence / verification ----
  const [report, setReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [acting, setActing] = useState(false)

  // ---- Learning path ----
  const [path, setPath] = useState(null)
  const [pathTarget, setPathTarget] = useState('')
  const [pathLoading, setPathLoading] = useState(false)

  // ---- Relationship upload ----
  const [uploadingRelations, setUploadingRelations] = useState(false)
  const relationFileRef = useRef(null)

  // ---- Filter the visible graph client-side ----
  const visible = useMemo(
    () => filterGraph(graph, { verification, confidence, topic, query }),
    [graph, verification, confidence, topic, query],
  )

  const topics = useMemo(
    () => [...new Set(graph.nodes.map((node) => node.subject).filter(Boolean))].sort(),
    [graph],
  )

  const selectedSlug = visible.nodes.some((node) => node.id === selected) ? selected : null
  const selectedEdge = visible.edges.includes(edge) ? edge : null

  // ---- Selection helpers ----
  function selectNode(slug) { setSelected(slug); setEdge(null) }
  function selectEdge(edgeObj) { setEdge(edgeObj); setSelected(null) }
  function clearAll() { setSelected(null); setEdge(null) }
  function resetFilters() { setVerification('all'); setConfidence(0); setTopic(''); setQuery(''); selectNode(null) }

  // ---- Load the full graph from the backend (old process, preserved) ----
  const loadGraph = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [{ data }, { data: counts }] = await Promise.all([
        // Fetch everything; client-side filters narrow it down.
        graphApi.graph({ limit: 120, verification: 'all', min_confidence: 0 }),
        graphApi.status(),
      ])
      setGraph(data)
      setStatus(counts)
      setIsPreview(false)
      setBackendConnected(true)
      resetFilters()
    } catch (err) {
      setError('Could not load the knowledge graph from the backend — showing example data.')
      setIsPreview(true)
      setBackendConnected(false)
      fromError(err, 'Could not load the knowledge graph')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => { loadGraph() }, [loadGraph])

  // ---- Concept detail (on node select, backend when connected) ----
  useEffect(() => {
    if (!selected) { setDetail(null); setPathTarget(''); return }
    if (!backendConnected) {
      const node = graph.nodes.find((item) => item.id === selected)
      setPathTarget(node?.label || selected)
      return
    }
    setDetailLoading(true)
    let cancelled = false
    graphApi.concept(selected)
      .then(({ data }) => { if (!cancelled) { setDetail(data); setPathTarget(data.label || selected) } })
      .catch((err) => { if (!cancelled) fromError(err, 'Could not load the concept') })
      .finally(() => { if (!cancelled) setDetailLoading(false) })
    return () => { cancelled = true }
  }, [selected, backendConnected, graph, fromError])

  // ---- Edge evidence (on edge select, backend when connected) ----
  useEffect(() => {
    if (!edge) { setReport(null); return }
    if (!backendConnected) return
    setReportLoading(true)
    let cancelled = false
    graphApi.relationEvidence(edge.source, edge.target, edge.relation)
      .then(({ data }) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) fromError(err, 'Could not load the relationship evidence') })
      .finally(() => { if (!cancelled) setReportLoading(false) })
    return () => { cancelled = true }
  }, [edge, backendConnected, fromError])

  // ---- New-prototype JSON import (demo data; kept exactly) ----
  async function importGraph(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      if (file.size > 5_000_000) throw new Error('Choose a JSON export smaller than 5 MB.')
      const input = JSON.parse(await file.text())
      const data = input.data || input
      if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error('Use a graph export containing nodes and edges arrays.')
      if (data.nodes.length > 300 || data.edges.length > 1500) throw new Error('For a readable preview, import up to 300 concepts and 1,500 relationships.')
      const ids = new Set()
      for (const node of data.nodes) {
        if (!node || typeof node.id !== 'string' || ids.has(node.id) || (node.label != null && typeof node.label !== 'string') || (node.subject != null && typeof node.subject !== 'string')) throw new Error('Every concept needs a unique string id and text label.')
        ids.add(node.id)
      }
      for (const edgeObj of data.edges) if (!edgeObj || !ids.has(edgeObj.source) || !ids.has(edgeObj.target) || (edgeObj.relation != null && typeof edgeObj.relation !== 'string')) throw new Error('Every relationship must refer to existing concepts and use a text relation.')
      setGraph(data); setIsPreview(true); setBackendConnected(false); resetFilters(); setError('')
    } catch (importError) { setError(importError.message || 'Could not read this graph export.') }
  }

  // ---- New-prototype JSON export (kept exactly) ----
  function exportGraph() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(visible, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = isPreview ? 'example-knowledge-graph.json' : 'knowledge-graph.json'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  // ---- Learning path (old process, preserved) ----
  async function buildPath() {
    const target = (pathTarget || selected || '').trim()
    if (!target) return
    if (!backendConnected) { setError('Learning paths need the backend connection. Reload the graph first.'); return }
    setPathLoading(true)
    setPath(null)
    try {
      const { data } = await graphApi.learningPath(target, true)
      setPath(data)
    } catch (err) {
      fromError(err, 'Could not build the learning path')
    } finally {
      setPathLoading(false)
    }
  }

  // ---- Verify / reject edge (old process, preserved) ----
  async function verifyEdge(statusValue) {
    if (!selectedEdge) return
    if (!backendConnected) { setError('Verification needs the backend connection. Reload the graph first.'); return }
    setActing(true)
    try {
      const { data } = await graphApi.verifyRelation({
        source: selectedEdge.source, target: selectedEdge.target,
        relation: selectedEdge.relation, status: statusValue,
      })
      setReport(data)
      success(statusValue === 'verified' ? 'Relationship verified' : 'Relationship hidden (not deleted)')
      loadGraph()
    } catch (err) {
      fromError(err, 'Could not update the relationship')
    } finally {
      setActing(false)
    }
  }

  // ---- Relationship file upload (old process, preserved) ----
  async function handleRelationUpload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    setUploadingRelations(true)
    try {
      const { data } = await graphApi.uploadRelations(file)
      const stored = data?.edges_stored ?? 0
      const unresolved = data?.edges_unresolved ?? 0
      if (stored > 0) { success(`Added ${stored} relationship${stored === 1 ? '' : 's'} to the graph.`); loadGraph() }
      if (unresolved > 0) {
        const sample = Object.keys(data?.unmatched_sources || {}).concat(Object.keys(data?.unmatched_targets || {})).slice(0, 4)
        fromError(new Error(`${unresolved} edge(s) skipped — concepts not found: ${sample.join(', ')}${sample.length >= 4 ? '…' : ''}`), 'Some relationships could not be matched')
      }
      if (stored === 0 && unresolved === 0) { fromError(new Error('No edges could be read from that file.'), 'Nothing imported') }
    } catch (err) {
      fromError(err, 'Could not upload the relationship file')
    } finally {
      setUploadingRelations(false)
    }
  }

  if (loading && !graph?.nodes?.length) {
    return (
      <div className="kg-workspace">
        <main className="kg-workspace-main">
          <div className="kg-topbar"><h1 className="kg-page-title">Knowledge Graph</h1></div>
          <div className="kg-main-content">
            <div className="kg-graph__canvas-wrap">
              <div className="kg-loading">Loading your knowledge graph…</div>
            </div>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="kg-workspace kg-workspace--embedded">
      <div className="kg-workspace-main">
        <header className="kg-topbar"><div className="kg-breadcrumb"><Home size={13} /><ChevronRight size={11} /><span>Workspace</span><ChevronRight size={11} /><strong>Knowledge graph</strong></div><div className="kg-topbar-actions">{backendConnected ? <span className="kg-preview-badge"><span />{status?.concept_count ?? graph.nodes.length} concepts · {status?.relation_count ?? graph.edges.length} relations</span> : <span className="kg-preview-badge"><span />{isPreview ? 'Preview data' : 'Imported graph'}</span>}<button className="kg-toolbar-toggle" type="button" aria-expanded={menu} aria-controls="kg-graph-menu" aria-label={menu ? 'Hide knowledge-graph menu' : 'Show knowledge-graph menu'} onClick={() => setMenu(!menu)}><Menu size={17} />Menu</button></div></header>
        {menu && (
          <nav id="kg-graph-menu" className="kg-embedded-menu" aria-label="Knowledge explorer">
            <span className="kg-nav-caption">EXPLORE YOUR GRAPH</span>
            <div className="kg-embedded-menu-row">
              <button className={view === 'graph' ? 'kg-nav-selected' : ''} onClick={() => { setView('graph'); setMenu(false) }}><GitBranch size={16} />Graph explorer</button>
              <button className={view === 'concepts' ? 'kg-nav-selected' : ''} onClick={() => { setView('concepts'); setMenu(false) }}><Layers size={16} />Concept library<span className="kg-nav-count">{graph.nodes.length}</span></button>
              <button className={view === 'relationships' ? 'kg-nav-selected' : ''} onClick={() => { setView('relationships'); setMenu(false) }}><GitBranch size={16} />Relationships</button>
              <button onClick={() => { setHelp(!help); setMenu(false) }}><CircleHelp size={16} />Explorer guide<ChevronRight size={13} /></button>
            </div>
          </nav>
        )}
        <main className="kg-main-content">
          <div className="kg-heading-row"><div><div className="kg-eyebrow">SEE THE BIGGER PICTURE</div><h1>Knowledge <em>graph</em></h1><p>Less scattered information. More meaningful connections.</p></div><div className="kg-page-actions"><button className="kg-page-button" onClick={() => fileInput.current?.click()}><FileJson size={14} />Import JSON</button><button className="kg-page-button kg-page-button--primary" onClick={exportGraph}><ArrowDownToLine size={14} />Export</button><input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={importGraph} /></div></div>
          <div className="kg-page-tabs"><button aria-pressed={view === 'graph'} onClick={() => setView('graph')}><Network size={14} />Graph explorer</button><button aria-pressed={view === 'concepts'} onClick={() => setView('concepts')}><Layers size={14} />Concepts<span>{graph.nodes.length}</span></button><button aria-pressed={view === 'relationships'} onClick={() => setView('relationships')}><GitBranch size={14} />Relationships<span>{graph.edges.length}</span></button></div>
          {help && <section className="kg-help-panel"><div><h2>Make space for discovery</h2><p>Drag to orbit in 3D, right-drag to pan, and scroll to zoom. Select a concept to focus its neighborhood or a connection to inspect its evidence. Use the relationship legend to hide noisy connections. Your existing page can use this component with its current graph data and callbacks.</p></div><button aria-label="Close guide" onClick={() => setHelp(false)}><X size={16} /></button></section>}
          {error && <div className="kg-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error"><X size={14} /></button></div>}
          <section className="kg-filter-bar" aria-label="Graph filters"><div className="kg-filter-top"><label className="kg-search"><Search size={15} /><input placeholder="Find a concept or connection…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search concepts" />{query && <button aria-label="Clear search" onClick={() => setQuery('')}><X size={13} /></button>}</label><label className="kg-filter-select"><BookOpen size={13} /><select aria-label="Filter by topic" value={topic} onChange={(event) => setTopic(event.target.value)}><option value="">All topics</option>{topics.map((item) => <option key={item}>{item}</option>)}</select></label><label className="kg-filter-select"><ShieldCheck size={13} /><select aria-label="Relationship visibility" value={verification} onChange={(event) => setVerification(event.target.value)}>{VERIFICATION_MODES.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}</select></label></div><div className="kg-filter-bottom"><label><SlidersHorizontal size={12} />Min. confidence<input type="range" min="0" max="1" step="0.05" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} aria-label="Minimum confidence" /><output>{Math.round(confidence * 100)}%</output></label><div className="kg-row-wrap" style={{ gap: 'var(--kg-space-2)' }}><button onClick={resetFilters}>Reset filters</button>{backendConnected && <button className="kg-graph-button kg-graph-button--secondary" onClick={loadGraph} title="Reload the graph from the backend"><Layers size={14} /> Refresh</button>}{backendConnected && <button className="kg-graph-button kg-graph-button--secondary" onClick={() => relationFileRef.current?.click()} disabled={uploadingRelations} title="Upload a PDF/TXT/JSON/JSONL/CSV file listing concept-to-concept relationships"><Upload size={14} />{uploadingRelations ? 'Uploading…' : 'Upload relationships'}</button>}</div></div></section>
          <input ref={relationFileRef} type="file" accept=".pdf,.txt,.json,.jsonl,.csv" style={{ display: 'none' }} onChange={handleRelationUpload} />
          <div className="kg-explorer-layout"><div className="kg-graph-column">
            {view === 'graph' ? (visible.nodes.length > 0 ? (
              <Suspense fallback={<div className="kg-graph__canvas-wrap"><div className="kg-loading">Preparing graph explorer…</div></div>}>
                <GraphPanel graph={visible} selectedSlug={selectedSlug} centerOnSlug={selectedSlug} onSelectNode={selectNode} onSelectEdge={selectEdge} height={460} />
              </Suspense>
            ) : (
              <div className="kg-graph__canvas-wrap">
                <div className="kg-graph-empty">
                  <Network size={32} />
                  <h3>No concepts found</h3>
                  <p>{query || topic || verification !== 'all' || confidence > 0 ? 'Try adjusting the filters above.' : 'Upload documents to build your knowledge graph.'}</p>
                </div>
              </div>
            )) : <section className="kg-library"><div className="kg-library-heading"><h2>{view === 'concepts' ? 'Concept library' : 'Relationships'}</h2><span>{view === 'concepts' ? visible.nodes.length : visible.edges.length} shown</span></div>{view === 'concepts' ? visible.nodes.map((node) => <button className="kg-library-row" key={node.id} onClick={() => selectNode(node.id)}><span className="kg-concept-icon"><Network size={15} /></span><span><strong>{node.label}</strong><small>{node.subject || 'Uncategorized'}</small></span><ChevronRight size={14} /></button>) : visible.edges.map((edgeObj, i) => <button className="kg-library-row" key={edgeObj.id || i} onClick={() => { setEdge(edgeObj); setSelected(null) }}><span className="kg-concept-icon"><GitBranch size={15} /></span><span><strong>{graph.nodes.find((node) => node.id === edgeObj.source)?.label} → {graph.nodes.find((node) => node.id === edgeObj.target)?.label}</strong><small>{(edgeObj.relation || 'related_to').replaceAll('_', ' ')} · {Math.round((edgeObj.confidence || 0) * 100)}% confidence</small></span>{edgeObj.verification_status === 'verified' && <Check size={14} />}</button>)}{!(view === 'concepts' ? visible.nodes : visible.edges).length && <div className="kg-graph-empty"><h3>No matches</h3><p>Try a different search or reset the filters.</p></div>}</section>}
            <p className="kg-below-graph"><ShieldCheck size={12} />{isPreview ? 'Example graph for UI preview. Your backend is not connected here.' : 'Imported JSON is held in memory for this preview; it is not saved.'}<button onClick={() => setHelp(!help)}>How to explore<ChevronRight size={11} /></button></p>

            {/* ---- Learning path (old process, preserved) ---- */}
            <section className="kg-learning-path">
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--kg-space-2)', marginBottom: 'var(--kg-space-2)' }}>
                <BookOpen size={15} />
                <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600 }}>Learning path</h3>
              </div>
              <p className="kg-text-xs kg-text-muted" style={{ margin: 0, marginBottom: 'var(--kg-space-2)' }}>
                Prerequisites already ordered by the graph.
              </p>
              <div style={{ display: 'flex', gap: 'var(--kg-space-2)', alignItems: 'flex-end', marginBottom: 'var(--kg-space-2)' }}>
                <input type="text" className="kg-input" placeholder="e.g. BCNF" value={pathTarget} onChange={(e) => setPathTarget(e.target.value)} style={{ flex: 1 }} />
                <button className="kg-graph-button" onClick={buildPath} disabled={pathLoading || !pathTarget.trim()}>
                  {pathLoading ? 'Building…' : 'Build revision plan'}
                </button>
              </div>
              {path ? (
                <div className="kg-stack-sm">
                  {(path.steps || []).map((step, index) => (
                    <div key={`${step.slug || step.topic}-${index}`} className="kg-row-wrap" style={{ gap: 'var(--kg-space-2)' }}>
                      <span className="kg-badge kg-badge--primary">{index + 1}. {step.topic}</span>
                      <span className="kg-text-xs kg-text-muted">{step.reason}</span>
                    </div>
                  ))}
                  <p className="kg-text-xs kg-text-muted" style={{ margin: 0 }}>
                    {path.note ? `${path.note} — ` : ''}{path.method}
                  </p>
                </div>
              ) : null}
            </section>

            {backendConnected && isPreview === false && (
              <p className="kg-below-graph" style={{ flexWrap: 'wrap', fontSize: '0.8rem' }}>
                <ShieldCheck size={12} />
                Live backend data ({status?.concept_count ?? graph.nodes.length} concepts · {status?.relation_count ?? graph.edges.length} relations).
                <button onClick={loadGraph} style={{ marginLeft: 'auto' }}>Reload backend data</button>
              </p>
            )}
          </div><GraphInspector graph={visible} selectedSlug={selectedSlug} selectedEdge={selectedEdge} onSelect={selectNode} onClear={clearAll} isPreview={isPreview} detail={detail} detailLoading={detailLoading} edgeReport={report} edgeReportLoading={reportLoading} onVerifyEdge={verifyEdge} acting={acting} /></div>
          <footer className="kg-workspace-footer"><span>A clearer view of what you know.</span><span>Made for curious minds.</span></footer>
        </main>
      </div>
    </div>
  )
}
