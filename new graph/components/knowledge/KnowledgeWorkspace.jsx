'use client'

import { useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { ArrowDownToLine, BookOpen, Check, ChevronRight, CircleHelp, FileJson, GitBranch, Home, Layers, Menu, Network, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-react'
import GraphInspector from './GraphInspector'
import { previewGraph, filterGraph } from './preview-data'
import './workspace.css'
const GraphPanel = dynamic(() => import('./GraphPanel'), { ssr: false, loading: () => <div className="kg-loading">Preparing graph explorer…</div> })

export default function KnowledgeWorkspace() {
  const [graph, setGraph] = useState(previewGraph)
  const [isPreview, setIsPreview] = useState(true)
  const [verification, setVerification] = useState('all')
  const [confidence, setConfidence] = useState(0)
  const [topic, setTopic] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [edge, setEdge] = useState(null)
  const [view, setView] = useState('graph')
  const [help, setHelp] = useState(false)
  const [menu, setMenu] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef(null)
  const visible = useMemo(() => filterGraph(graph, { verification, confidence, topic, query }), [graph, verification, confidence, topic, query])
  const topics = [...new Set(graph.nodes.map((node) => node.subject).filter(Boolean))].sort()
  const selectedSlug = visible.nodes.some((node) => node.id === selected) ? selected : null
  const selectedEdge = visible.edges.includes(edge) ? edge : null
  function selectNode(slug) { setSelected(slug); setEdge(null) }
  function resetFilters() { setVerification('all'); setConfidence(0); setTopic(''); setQuery(''); selectNode(null) }
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
      for (const edge of data.edges) if (!edge || !ids.has(edge.source) || !ids.has(edge.target) || (edge.relation != null && typeof edge.relation !== 'string')) throw new Error('Every relationship must refer to existing concepts and use a text relation.')
      setGraph(data); setIsPreview(false); resetFilters(); setError('')
    } catch (error) { setError(error.message || 'Could not read this graph export.') }
  }
  function exportGraph() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(visible, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = isPreview ? 'example-knowledge-graph.json' : 'knowledge-graph.json'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <div className="kg-workspace">
    <aside className={`kg-sidebar${menu ? ' kg-sidebar--open' : ''}`}>
      <a className="kg-brand" href="/" aria-label="KnowGraph home"><span className="kg-brand-symbol"><Network size={21} strokeWidth={1.5} /></span><span>KnowGraph<span className="kg-brand-ai">AI</span></span></a>
      <div className="kg-workspace-switch"><span className="kg-workspace-avatar">P</span><div>Personal workspace<small>Your connected knowledge</small></div></div>
      <nav aria-label="Knowledge explorer"><span className="kg-nav-caption">WORKSPACE</span><a className="kg-nav-active" href="/" aria-current="page"><Network size={17} />Knowledge graph</a><span className="kg-nav-caption kg-nav-caption--second">EXPLORE YOUR GRAPH</span><button className={view === 'graph' ? 'kg-nav-selected' : ''} onClick={() => { setView('graph'); setMenu(false) }}><GitBranch size={16} />Graph explorer</button><button className={view === 'concepts' ? 'kg-nav-selected' : ''} onClick={() => { setView('concepts'); setMenu(false) }}><Layers size={16} />Concept library<span className="kg-nav-count">{graph.nodes.length}</span></button><button className={view === 'relationships' ? 'kg-nav-selected' : ''} onClick={() => { setView('relationships'); setMenu(false) }}><GitBranch size={16} />Relationships</button></nav>
      <div className="kg-sidebar-bottom"><div className="kg-local-card"><span><ShieldCheck size={15} />Your knowledge, connected</span><p>Find the bigger picture in the details you already know.</p></div><button className="kg-help-button" onClick={() => setHelp(!help)}><CircleHelp size={16} />Explorer guide<ChevronRight size={13} /></button><div className="kg-sidebar-foot">KNOWGRAPH AI<span>Component preview</span></div></div>
    </aside>
    {menu && <button className="kg-menu-scrim" aria-label="Close menu" onClick={() => setMenu(false)} />}
    <div className="kg-workspace-main">
      <header className="kg-topbar"><button className="kg-mobile-menu" aria-label="Open menu" onClick={() => setMenu(!menu)}><Menu size={19} /></button><div className="kg-breadcrumb"><Home size={13} /><ChevronRight size={11} /><span>Workspace</span><ChevronRight size={11} /><strong>Knowledge graph</strong></div><span className="kg-preview-badge"><span />{isPreview ? 'Preview data' : 'Imported graph'}</span></header>
      <main className="kg-main-content">
        <div className="kg-heading-row"><div><div className="kg-eyebrow">SEE THE BIGGER PICTURE</div><h1>Knowledge <em>graph</em></h1><p>Less scattered information. More meaningful connections.</p></div><div className="kg-page-actions"><button className="kg-page-button" onClick={() => fileInput.current?.click()}><FileJson size={14} />Import JSON</button><button className="kg-page-button kg-page-button--primary" onClick={exportGraph}><ArrowDownToLine size={14} />Export</button><input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={importGraph} /></div></div>
        <div className="kg-page-tabs"><button aria-pressed={view === 'graph'} onClick={() => setView('graph')}><Network size={14} />Graph explorer</button><button aria-pressed={view === 'concepts'} onClick={() => setView('concepts')}><Layers size={14} />Concepts<span>{graph.nodes.length}</span></button><button aria-pressed={view === 'relationships'} onClick={() => setView('relationships')}><GitBranch size={14} />Relationships<span>{graph.edges.length}</span></button></div>
        {help && <section className="kg-help-panel"><div><h2>Make space for discovery</h2><p>Drag to orbit in 3D, right-drag to pan, and scroll to zoom. Select a concept to focus its neighborhood or a connection to inspect its evidence. Use the relationship legend to hide noisy connections. Your existing page can use this component with its current graph data and callbacks.</p></div><button aria-label="Close guide" onClick={() => setHelp(false)}><X size={16} /></button></section>}
        {error && <div className="kg-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error"><X size={14} /></button></div>}
        <section className="kg-filter-bar" aria-label="Graph filters"><div className="kg-filter-top"><label className="kg-search"><Search size={15} /><input placeholder="Find a concept or connection…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search concepts" />{query && <button aria-label="Clear search" onClick={() => setQuery('')}><X size={13} /></button>}</label><label className="kg-filter-select"><BookOpen size={13} /><select aria-label="Filter by topic" value={topic} onChange={(event) => setTopic(event.target.value)}><option value="">All topics</option>{topics.map((item) => <option key={item}>{item}</option>)}</select></label><label className="kg-filter-select"><ShieldCheck size={13} /><select aria-label="Relationship visibility" value={verification} onChange={(event) => setVerification(event.target.value)}><option value="all">All relationships</option><option value="verified">Verified only</option><option value="inferred">Verified + inferred</option></select></label></div><div className="kg-filter-bottom"><label><SlidersHorizontal size={12} />Min. confidence<input type="range" min="0" max="1" step="0.05" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} aria-label="Minimum confidence" /><output>{Math.round(confidence * 100)}%</output></label><button onClick={resetFilters}>Reset filters</button></div></section>
        <div className="kg-explorer-layout"><div className="kg-graph-column">
          {view === 'graph' ? <GraphPanel graph={visible} selectedSlug={selectedSlug} centerOnSlug={selectedSlug} onSelectNode={selectNode} onSelectEdge={(edge) => { setEdge(edge); setSelected(null) }} height={460} /> : <section className="kg-library"><div className="kg-library-heading"><h2>{view === 'concepts' ? 'Concept library' : 'Relationships'}</h2><span>{view === 'concepts' ? visible.nodes.length : visible.edges.length} shown</span></div>{view === 'concepts' ? visible.nodes.map((node) => <button className="kg-library-row" key={node.id} onClick={() => selectNode(node.id)}><span className="kg-concept-icon"><Network size={15} /></span><span><strong>{node.label}</strong><small>{node.subject || 'Uncategorized'}</small></span><ChevronRight size={14} /></button>) : visible.edges.map((edge, i) => <button className="kg-library-row" key={edge.id || i} onClick={() => { setEdge(edge); setSelected(null) }}><span className="kg-concept-icon"><GitBranch size={15} /></span><span><strong>{graph.nodes.find((node) => node.id === edge.source)?.label} → {graph.nodes.find((node) => node.id === edge.target)?.label}</strong><small>{(edge.relation || 'related_to').replaceAll('_', ' ')} · {Math.round((edge.confidence || 0) * 100)}% confidence</small></span>{edge.verification_status === 'verified' && <Check size={14} />}</button>)}{!(view === 'concepts' ? visible.nodes : visible.edges).length && <div className="kg-graph-empty"><h3>No matches</h3><p>Try a different search or reset the filters.</p></div>}</section>}
          <p className="kg-below-graph"><ShieldCheck size={12} />{isPreview ? 'Example graph for UI preview. Your backend is not connected here.' : 'Imported JSON is held in memory for this preview; it is not saved.'}<button onClick={() => setHelp(!help)}>How to explore<ChevronRight size={11} /></button></p>
        </div><GraphInspector graph={visible} selectedSlug={selectedSlug} selectedEdge={selectedEdge} onSelect={selectNode} onClear={() => { setSelected(null); setEdge(null) }} isPreview={isPreview} /></div>
        <footer className="kg-workspace-footer"><span>A clearer view of what you know.</span><span>Made for curious minds.</span></footer>
      </main>
    </div>
  </div>
}
