 /**
 * GraphPanel — interactive knowledge-graph visualisation (brief §9).
 *
 * Cytoscape.js (bundled locally, no CDN) draws the concepts and typed relations.
 * Layouts: hierarchical (breadthfirst over prerequisite edges), radial
 * (concentric by importance), force-directed (cose) and clustered (compound
 * nodes per topic). Extras: search-focus centring, degree-capped node sizing,
 * zoom-aware labels, selected-neighbourhood focus with incoming/outgoing edge
 * distinction, relation + verification legend, a lightweight minimap, and
 * edge selection for the inspector panel.
 *
 * Cytoscape renders to <canvas>, so all graph visuals live in the Cytoscape
 * stylesheet below; GraphPanel.css only styles the HTML shell.
 */


import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { Box, Network, Maximize, Plus, Minus, RotateCcw, Focus, Eye, MousePointer2 } from 'lucide-react'
import { Badge, Button, Select, EmptyState } from './graph-ui'
import { RELATION_COLORS, readToken } from './graph-theme'
const GraphScene3D = lazy(() => import('./GraphScene3D'))
import './GraphPanel.css'

/* ===================================================================
 * Relation → line style
 * =================================================================== */
const RELATION_STYLES = {
  requires: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.9 },
  prerequisite_of: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.9 },
  depends_on: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.9 },
  causes: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.85 },
  is_a: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.85 },
  explains: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.85 },
  example_of: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.85 },
  used_for: { lineStyle: 'solid', targetArrow: 'triangle', sourceArrow: 'none', opacity: 0.8 },
  part_of: { lineStyle: 'dashed', targetArrow: 'none', sourceArrow: 'none', opacity: 0.8 },
  contrasts_with: { lineStyle: 'dotted', targetArrow: 'tee', sourceArrow: 'tee', opacity: 0.9 },
  related_to: { lineStyle: 'dashed', targetArrow: 'none', sourceArrow: 'none', opacity: 0.35 },
}
const DEFAULT_RELATION_STYLE = RELATION_STYLES.related_to

const SUBJECT_PALETTE = ['#bd765a', '#6b9982', '#7b91b2', '#b09563', '#9b83ac']

export const LAYOUT_MODES = [
  { value: 'auto', label: 'Auto (recommended)' },
  { value: 'hierarchical', label: 'Hierarchical' },
  { value: 'radial', label: 'Radial' },
  { value: 'force', label: 'Force-directed' },
]

export const COLOR_MODES = [
  { value: 'degree', label: 'By importance' },
  { value: 'topic', label: 'By topic / source' },
  { value: 'relationship', label: 'By relationship' },
]

export const VERIFICATION_MODES = [
  { value: 'verified', label: 'Verified only' },
  { value: 'inferred', label: 'Verified + inferred' },
  { value: 'all', label: 'All relationships' },
]

export const DEPTH_MODES = [
  { value: '1', label: '1 hop' },
  { value: '2', label: '2 hops' },
  { value: 'all', label: 'All' },
]

const CLASS_DIMMED = 'kg-dimmed'
const CLASS_HIGHLIGHTED = 'kg-highlighted'
const CLASS_FOCUS = 'kg-focus'
const CLASS_LABEL_HIDDEN = 'kg-label-hidden'
const CLASS_EDGE_HIDDEN = 'kg-edge-hidden'
const CLASS_EDGE_IN = 'kg-edge-in'
const CLASS_EDGE_OUT = 'kg-edge-out'
const INTERACTION_CLASSES = [CLASS_DIMMED, CLASS_HIGHLIGHTED, CLASS_FOCUS, CLASS_EDGE_IN, CLASS_EDGE_OUT]

const LABEL_ZOOM_HUB = 0.25
const LABEL_ZOOM_MID = 0.5
const LABEL_ZOOM_LEAF = 0.8
const LABEL_ZOOM_EDGE = 0.55

/* ===================================================================
 * Shared helpers
 * =================================================================== */
function truncate(text, max) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function pluralize(count, singular) {
  return `${count} ${singular}${count === 1 ? '' : 's'}`
}

function subjectIndex(key) {
  let hash = 0
  const text = String(key || '')
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) % 9973
  return hash % SUBJECT_PALETTE.length
}

function edgeEvidence(edge) {
  const rows = []
  const push = (title, page, snippet) => {
    const parts = []
    if (title) parts.push(String(title))
    if (page !== undefined && page !== null && page !== '') parts.push(`page ${page}`)
    if (parts.length) rows.push(parts.join(' — '))
    if (snippet) rows.push(`“${truncate(snippet, 90)}”`)
  }
  for (const document of edge?.documents || []) {
    push(document?.title || document?.document_title, document?.page_number ?? document?.page, document?.snippet)
  }
  const raw = edge?.evidence
  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (typeof item === 'string') push(item)
      else if (item && typeof item === 'object') {
        push(item.document_title || item.title, item.page_number ?? item.page, item.snippet)
      }
    }
  } else if (typeof raw === 'string' && raw.trim()) push(raw)
  if (edge?.snippet || edge?.page !== undefined) push(undefined, edge?.page, edge?.snippet)
  return [...new Set(rows)].slice(0, 3)
}

function nodeTooltip(node, degree) {
  const lines = [String(node.label || node.id)]
  lines.push(pluralize(degree, 'connection'))
  lines.push(pluralize(Number(node.document_count) || 0, 'document'))
  const mentions = Number(node.occurrences) || 0
  if (mentions) lines.push(pluralize(mentions, 'mention'))
  if (node.score !== undefined && node.score !== null) {
    lines.push(`Importance score ${Number(node.score).toFixed(2)}`)
  }
  if (node.subject) lines.push(`Subject: ${node.subject}`)
  if (node.definition) lines.push(`“${truncate(node.definition, 110)}”`)
  return lines.join('\n')
}

function edgeTooltip(edge, sourceLabel, targetLabel) {
  const lines = [`${sourceLabel} → ${targetLabel}`]
  lines.push(`${edge.relation || 'related_to'} · ${edge.method || 'cooccurrence'}`)
  const confidence = Number(edge.confidence)
  if (Number.isFinite(confidence) && confidence > 0) {
    lines.push(`Confidence ${(confidence * 100).toFixed(0)}% · ${edge.verification_status || 'uncertain'}`)
  }
  const evidence = edgeEvidence(edge)
  if (evidence.length) lines.push('Evidence:', ...evidence)
  else lines.push('No page evidence recorded for this relation.')
  return lines.join('\n')
}

/**
 * Build the layout configuration for the requested mode.
 *
 * `roots` are concepts with no incoming prerequisite/dependency edge — the
 * natural starting points for the hierarchical reading order.
 */
export function buildLayoutConfig(mode, { hasPrerequisites = false, roots = [], importance = () => 0 } = {}) {
  const common = { animate: false, fit: true, padding: 42, nodeDimensionsIncludeLabels: true }
  const effective = mode === 'auto' ? (hasPrerequisites ? 'hierarchical' : 'force') : mode
  switch (effective) {
    case 'hierarchical':
      return {
        ...common,
        name: 'breadthfirst',
        directed: true,
        roots: roots.length ? roots : undefined,
        spacingFactor: 1.6,
        avoidOverlap: true,
      }
    case 'radial':
      return {
        ...common,
        name: 'concentric',
        concentric: (node) => importance(node.id()) || 0,
        levelWidth: () => 0.6,
        minNodeSpacing: 70,
        avoidOverlap: true,
      }
    case 'force':
    default:
      return {
        ...common,
        name: 'cose',
        idealEdgeLength: 120,
        nodeRepulsion: 12000,
        edgeElasticity: 120,
        nestingFactor: 1.2,
        gravity: 0.9,
        nodeOverlap: 12,
        componentSpacing: 90,
        initialTemp: 220,
        coolingFactor: 0.95,
        minTemp: 1,
        numIter: 1500,
      }
  }
}

/* ===================================================================
 * Cytoscape stylesheet (this is the canvas "CSS")
 * =================================================================== */
function buildStyle(theme) {
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'font-family': theme.font,
        'font-size': 11,
        'font-weight': 600,
        color: theme.text,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 6,
        'text-wrap': 'wrap',
        'text-max-width': '120px',
        'text-outline-width': 2.5,
        'text-outline-color': theme.surface,
        'text-outline-opacity': 1,
        width: 'data(size)',
        height: 'data(size)',
        'background-color': 'data(color)',
        'border-width': 1.5,
        'border-color': theme.border,
        'border-opacity': 0.9,
      },
    },
    { selector: 'node.kg-hub', style: { 'border-width': 3, 'border-color': 'data(color)', 'border-opacity': 1 } },
    // Compound parent bubbles ("Clustered / topic" layout): tinted rectangles
    // that group concepts by source topic. Children keep their own styles.
    {
      selector: 'node.kg-cluster',
      style: {
        shape: 'round-rectangle',
        label: 'data(label)',
        'font-size': 12,
        'font-weight': 700,
        'text-valign': 'top',
        'text-halign': 'center',
        'text-margin-y': -14,
        'background-color': theme.surfaceAlt || '#e2e8f0',
        'background-opacity': 0.55,
        'background-blacken': -0.08,
        'border-width': 1.5,
        'border-style': 'dashed',
        'border-color': theme.border,
        'border-opacity': 0.8,
        padding: 26,
      },
    },
    { selector: 'node:selected', style: { 'border-width': 4, 'border-color': theme.secondary, 'border-opacity': 1 } },
    {
      selector: `node.${CLASS_FOCUS}`,
      style: { 'border-width': 4, 'border-color': theme.secondary, 'border-opacity': 1, 'z-index': 20 },
    },
    {
      selector: 'edge',
      style: {
        width: 'mapData(weight, 1, 4, 1, 3)',
        'curve-style': 'bezier',
        'line-style': 'data(lineStyle)',
        'line-color': 'data(color)',
        'arrow-scale': 0.9,
        'target-arrow-shape': 'data(targetArrow)',
        'target-arrow-color': 'data(color)',
        'source-arrow-shape': 'data(sourceArrow)',
        'source-arrow-color': 'data(color)',
        opacity: 'data(edgeOpacity)',
        label: 'data(label)',
        'font-family': theme.font,
        'font-size': 8,
        color: theme.muted,
        'text-rotation': 'autorotate',
        'text-outline-width': 2,
        'text-outline-color': theme.surface,
      },
    },
    // Outgoing edges of the focused node: slightly heavier, fully opaque.
    {
      selector: `edge.${CLASS_EDGE_OUT}`,
      style: { width: 3, opacity: 1, 'line-color': theme.secondary, 'target-arrow-color': theme.secondary, 'source-arrow-color': theme.secondary },
    },
    // Incoming edges: keep relation colour but emphasise width.
    { selector: `edge.${CLASS_EDGE_IN}`, style: { width: 2.5, opacity: 1 } },
    // ---- Zoom-aware labels (toggled by applyLabelVisibility) -------------
    { selector: `node.${CLASS_LABEL_HIDDEN}`, style: { 'text-opacity': 0 } },
    { selector: `edge.${CLASS_LABEL_HIDDEN}`, style: { 'text-opacity': 0 } },
    { selector: 'node:selected', style: { 'text-opacity': 1 } },
    { selector: `node.${CLASS_FOCUS}`, style: { 'text-opacity': 1 } },
    // ---- Legend / verification filter ------------------------------------
    { selector: `edge.${CLASS_EDGE_HIDDEN}`, style: { display: 'none' } },
    // ---- Focus / dim, last so they beat per-element values ----------------
    { selector: `.${CLASS_DIMMED}`, style: { opacity: 0.12 } },
    { selector: `.${CLASS_HIGHLIGHTED}`, style: { opacity: 1 } },
  ]
}

/* ===================================================================
 * Interaction helpers
 * =================================================================== */
function neighboursAtDepth(node, depth) {
  if (depth === 'all') return node.cy().elements()
  if (Number(depth) === 2) {
    return node.closedNeighborhood().union(node.neighborhood().neighborhood()).union(node)
  }
  return node.closedNeighborhood()
}

function applyFocus(instance, slug, depth = '1') {
  instance.edges().removeClass([CLASS_EDGE_IN, CLASS_EDGE_OUT])
  instance.elements().removeClass(INTERACTION_CLASSES)
  instance.elements().unselect()
  if (!slug) return

  const node = instance.getElementById(slug)
  if (!node || node.empty()) return

  const neighbourhood = neighboursAtDepth(node, depth)
  instance.elements().difference(neighbourhood).addClass(CLASS_DIMMED)
  neighbourhood.addClass(CLASS_HIGHLIGHTED)

  // Distinguish incoming vs outgoing edges relative to the focused node.
  node.connectedEdges().forEach((edge) => {
    edge.addClass(edge.target().id() === slug ? CLASS_EDGE_IN : CLASS_EDGE_OUT)
  })
  node.addClass(CLASS_FOCUS)
  node.select()
}

function applyLabelVisibility(instance) {
  const zoom = instance.zoom()
  const hideEdgeLabels = zoom < LABEL_ZOOM_EDGE
  instance.nodes().forEach((node) => {
    const hide = zoom < (node.data('labelZoom') || 0)
    if (node.hasClass(CLASS_LABEL_HIDDEN) !== hide) node.toggleClass(CLASS_LABEL_HIDDEN, hide)
  })
  instance.edges().forEach((edge) => {
    if (edge.hasClass(CLASS_LABEL_HIDDEN) !== hideEdgeLabels) {
      edge.toggleClass(CLASS_LABEL_HIDDEN, hideEdgeLabels)
    }
  })
}

function applyRelationFilter(instance, hiddenRelations) {
  instance.edges().forEach((edge) => {
    const hide = hiddenRelations.has(edge.data('relation'))
    if (edge.hasClass(CLASS_EDGE_HIDDEN) !== hide) edge.toggleClass(CLASS_EDGE_HIDDEN, hide)
  })
}

/* ---- Lightweight minimap (no extra dependency) ------------------------- */
function drawMinimap(canvas, instance) {
  const context = canvas?.getContext('2d')
  if (!context || !instance || instance.destroyed()) return
  const width = canvas.width
  const height = canvas.height
  const theme = getComputedStyle(document.documentElement)
  const surface = theme.getPropertyValue('--kg-surface-alt').trim() || '#f1f5f9'
  const accent = theme.getPropertyValue('--kg-primary').trim() || '#4f46e5'
  const border = theme.getPropertyValue('--kg-border-strong').trim() || '#94a3b8'

  context.clearRect(0, 0, width, height)
  context.fillStyle = surface
  context.fillRect(0, 0, width, height)

  const nodes = instance.nodes()
  if (!nodes.length) return
  const bb = instance.elements().boundingBox()
  const pad = 8
  const scale = Math.min((width - pad * 2) / Math.max(bb.w, 1), (height - pad * 2) / Math.max(bb.h, 1))
  const toMinimap = (x, y) => ({
    x: pad + (x - bb.x1) * scale,
    y: pad + (y - bb.y1) * scale,
  })

  context.fillStyle = accent
  nodes.forEach((node) => {
    const position = node.position()
    const { x, y } = toMinimap(position.x, position.y)
    context.beginPath()
    context.arc(x, y, 2, 0, Math.PI * 2)
    context.fill()
  })

  // Viewport rectangle.
  const zoom = instance.zoom()
  const pan = instance.pan()
  const view = toMinimap(-pan.x / zoom, -pan.y / zoom)
  const viewWidth = (instance.width() / zoom) * scale
  const viewHeight = (instance.height() / zoom) * scale
  context.strokeStyle = border
  context.lineWidth = 1.5
  context.strokeRect(view.x, view.y, viewWidth, viewHeight)
}

/* ===================================================================
 * Component
 * =================================================================== */
export default function GraphPanel({
  graph,
  onSelectNode,
  onSelectEdge,
  selectedSlug,
  centerOnSlug,
  height = 520,
}) {
  const containerRef = useRef(null)
  const wrapperRef = useRef(null)
  const minimapRef = useRef(null)
  const cyRef = useRef(null)
  const zoomFrameRef = useRef(0)
  const miniFrameRef = useRef(0)
  const [tooltip, setTooltip] = useState(null)
  const [hiddenRelations, setHiddenRelations] = useState(() => new Set())
  const sceneRef = useRef(null)
  const [dimension, setDimension] = useState('3d')
  const [showLabels, setShowLabels] = useState(true)
  const [layoutMode, setLayoutMode] = useState('force')
  const [colorMode, setColorMode] = useState('topic')
  const [depth, setDepth] = useState('1')
  const depthRef = useRef(depth)
  depthRef.current = depth
  const selectNodeRef = useRef(onSelectNode)
  selectNodeRef.current = onSelectNode
  const selectEdgeRef = useRef(onSelectEdge)
  selectEdgeRef.current = onSelectEdge

  const nodes = graph?.nodes || []
  const edges = graph?.edges || []

  const degrees = useMemo(() => {
    const map = new Map(nodes.map((node) => [node.id, 0]))
    for (const edge of edges) {
      if (map.has(edge.source)) map.set(edge.source, map.get(edge.source) + 1)
      if (map.has(edge.target)) map.set(edge.target, map.get(edge.target) + 1)
    }
    return map
  }, [nodes, edges])

  /** Importance blend: 70% degree, 30% stored score — capped, never runaway. */
  const importanceBySlug = useMemo(() => {
    const maxDegree = Math.max(1, ...degrees.values())
    const maxScore = Math.max(0.0001, ...nodes.map((node) => Number(node.score) || 0))
    const map = new Map()
    for (const node of nodes) {
      const degree = (degrees.get(node.id) || 0) / maxDegree
      const score = (Number(node.score) || 0) / maxScore
      map.set(node.id, 0.7 * degree + 0.3 * score)
    }
    return map
  }, [nodes, degrees])

  /** Root concepts for the hierarchical layout: no incoming dependency edge. */
  const roots = useMemo(() => {
    const hasIncoming = new Set()
    for (const edge of edges) {
      if (['prerequisite_of', 'requires', 'depends_on', 'part_of'].includes(edge.relation)) {
        hasIncoming.add(edge.target)
      }
    }
    const withoutIncoming = nodes.filter((node) => !hasIncoming.has(node.id))
    if (withoutIncoming.length) return withoutIncoming.map((node) => node.id)
    return [nodes[0]?.id].filter(Boolean)
  }, [nodes, edges])

  const hasPrerequisites = useMemo(
    () => edges.some((edge) => ['prerequisite_of', 'requires', 'depends_on'].includes(edge.relation)),
    [edges],
  )

  /** Topic key per node (first source-document title) for the clustered layout. */
  const clusterBySlug = useMemo(() => {
    const map = new Map()
    for (const node of nodes) {
      const topic = node.subject || node.documents?.[0]?.title || node.label || node.id
      map.set(node.id, topic)
    }
    return map
  }, [nodes])

  const elements = useMemo(() => {
    const maxDegree = Math.max(1, ...degrees.values())
    const labelBySlug = new Map(nodes.map((node) => [node.id, node.label || node.id]))
    const hasSubject = nodes.some((node) => node.subject)

    const labelZoomBySlug = new Map()
    const byImportance = [...nodes].sort(
      (a, b) => (importanceBySlug.get(b.id) || 0) - (importanceBySlug.get(a.id) || 0),
    )
    const lastIndex = Math.max(1, byImportance.length - 1)
    byImportance.forEach((node, index) => {
      const rank = index / lastIndex
      const gate = rank <= 0.15 ? LABEL_ZOOM_HUB : rank <= 0.5 ? LABEL_ZOOM_MID : LABEL_ZOOM_LEAF
      labelZoomBySlug.set(node.id, gate)
    })

    const topicBySlug = new Map()
    const useColorTopics = colorMode === 'topic' && (hasSubject || clusterBySlug.size > 0)
    if (useColorTopics) {
      for (const node of nodes) {
        const topic = node.subject || clusterBySlug.get(node.id)
        topicBySlug.set(node.id, topic)
      }
    }

    const nodeElements = nodes.map((node) => {
      const degree = degrees.get(node.id) || 0
      const ratio = degree / maxDegree
      let colorKey = 'isolated'
      if (ratio >= 0.6) colorKey = 'hub'
      else if (ratio >= 0.3) colorKey = 'mid'
      else if (ratio > 0) colorKey = 'leaf'
      if (useColorTopics && topicBySlug.has(node.id)) {
        colorKey = SUBJECT_PALETTE[subjectIndex(topicBySlug.get(node.id))]
      }
      if (colorMode === 'relationship') {
        const counts = new Map()
        for (const edge of edges) {
          if (edge.source === node.id || edge.target === node.id) {
            const relation = edge.relation || 'related_to'
            counts.set(relation, (counts.get(relation) || 0) + 1)
          }
        }
        const dominant = [...counts].sort((a, b) => b[1] - a[1])[0]?.[0]
        colorKey = RELATION_COLORS[dominant] || '#8c8a80'
      }
      const importance = importanceBySlug.get(node.id) || 0
      // Size follows importance but is capped (18 … 46 px).
      const size = Math.round(18 + Math.min(1, importance) * 28)
      return {
        data: {
          id: node.id,
          label: node.label || node.id,
          degree,
          size,
          colorKey,
          labelZoom: labelZoomBySlug.get(node.id) ?? LABEL_ZOOM_LEAF,
          tooltip: nodeTooltip(node, degree),
        },
        classes: ratio >= 0.6 ? 'kg-hub' : '',
      }
    })

    const edgeElements = edges.map((edge, index) => {
      const relation = edge.relation || 'related_to'
      const style = RELATION_STYLES[relation] || DEFAULT_RELATION_STYLE
      const uncertain = (edge.verification_status || 'uncertain') !== 'verified'
      return {
        data: {
          id: edge.id || `${edge.source}-${edge.target}-${index}`,
          source: edge.source,
          target: edge.target,
          relation,
          label: edge.label || relation,
          method: edge.method || 'cooccurrence',
          weight: Number(edge.weight) || 1,
          confidence: Number(edge.confidence) || 0,
          verification_status: edge.verification_status || 'uncertain',
          raw: edge,
          color: RELATION_COLORS[relation] || '#64748b',
          lineStyle: uncertain ? 'dashed' : style.lineStyle,
          targetArrow: style.targetArrow,
          sourceArrow: style.sourceArrow,
          edgeOpacity: style.opacity,
          tooltip: edgeTooltip(
            edge,
            labelBySlug.get(edge.source) || edge.source,
            labelBySlug.get(edge.target) || edge.target,
          ),
        },
      }
    })

    return [...nodeElements, ...edgeElements]
  }, [nodes, edges, degrees, importanceBySlug, colorMode, clusterBySlug, layoutMode])

  const rerunLayout = useCallback(() => {
    const instance = cyRef.current
    if (!instance) return
    const importance = (slug) => importanceBySlug.get(slug) || 0
    const config = buildLayoutConfig(layoutMode, { hasPrerequisites, roots, importance })
    instance
      .layout({ ...config, stop: () => applyLabelVisibility(instance) })
      .run()
  }, [layoutMode, hasPrerequisites, roots, importanceBySlug])

  // ---- Build (or rebuild) the Cytoscape instance when the data changes ----
  useEffect(() => {
    if (dimension !== '2d' || !containerRef.current || !nodes.length) return undefined

    const theme = {
      text: readToken('--kg-text', '#0f172a'),
      muted: readToken('--kg-muted', '#64748b'),
      border: readToken('--kg-border', '#e2e8f0'),
      surface: readToken('--kg-surface', '#ffffff'),
      surfaceAlt: readToken('--kg-surface-alt', '#f1f5f9'),
      secondary: readToken('--kg-secondary', '#0f766e'),
      font: readToken('--kg-font-sans', 'system-ui, sans-serif'),
    }
    const degreePalette = {
      hub: readToken('--kg-primary', '#4f46e5'),
      mid: readToken('--kg-secondary', '#0f766e'),
      leaf: readToken('--kg-info', '#1d4ed8'),
      isolated: readToken('--kg-muted', '#64748b'),
    }

    const instance = cytoscape({
      container: containerRef.current,
      elements: elements.map((element) =>
        element.data.source
          ? element
          : {
              ...element,
              data: {
                ...element.data,
                color:
                  colorMode !== 'degree'
                    ? element.data.colorKey
                    : degreePalette[element.data.colorKey] || element.data.colorKey,
              },
            },
      ),
      style: buildStyle(theme),
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.2,
      boxSelectionEnabled: false,
      autoungrabify: true,
    })

    let disposed = false
    cyRef.current = instance

    const showTooltip = (event) => {
      // Cluster bubbles are synthetic parents with no concept data — nothing to show.
      if (event.target.isParent && event.target.isParent()) return
      const text = event.target.data('tooltip')
      if (!text) return
      const point = event.renderedPosition
      const wrapperWidth = wrapperRef.current?.clientWidth || 0
      const wrapperHeight = wrapperRef.current?.clientHeight || 0
      setTooltip({
        text,
        tone: event.target.isNode() ? 'node' : 'edge',
        left: Math.max(8, Math.min(point.x + 14, Math.max(8, wrapperWidth - 300))),
        top: Math.max(8, Math.min(point.y + 14, Math.max(8, wrapperHeight - 150))),
      })
    }
    const hideTooltip = () => setTooltip(null)

    instance.on('tap', 'node', (event) => {
      // Cluster bubbles are synthetic compound parents ("cluster-0", …), not
      // concepts — selecting one must never query the backend for a slug that
      // does not exist. Focus the canvas on the cluster's children instead.
      const tapped = event.target
      if (tapped.isParent && tapped.isParent()) {
        selectNodeRef.current?.(null)
        const children = tapped.children()
        if (children.length) {
          instance.fit(children, 42)
        }
        return
      }
      selectNodeRef.current?.(tapped.id())
    })
    instance.on('tap', 'edge', (event) => {
      selectEdgeRef.current?.(event.target.data('raw') || null)
    })
    instance.on('tap', (event) => {
      if (event.target === instance) {
        selectNodeRef.current?.(null)
        selectEdgeRef.current?.(null)
      }
    })
    instance.on('mouseover', 'node', showTooltip)
    instance.on('mouseover', 'edge', showTooltip)
    instance.on('mouseout', 'node', hideTooltip)
    instance.on('mouseout', 'edge', hideTooltip)
    instance.on('pan', hideTooltip)

    const drawMini = () => {
      if (miniFrameRef.current) return
      miniFrameRef.current = requestAnimationFrame(() => {
        miniFrameRef.current = 0
        if (!disposed) drawMinimap(minimapRef.current, instance)
      })
    }
    const onZoom = () => {
      if (zoomFrameRef.current) return
      zoomFrameRef.current = requestAnimationFrame(() => {
        zoomFrameRef.current = 0
        if (disposed) return
        hideTooltip()
        applyLabelVisibility(instance)
      })
    }
    instance.on('zoom', onZoom)
    instance.on('viewport', drawMini)

    const importance = (slug) => importanceBySlug.get(slug) || 0
    const config = buildLayoutConfig(layoutMode, { hasPrerequisites, roots, importance })
    const layout = instance.layout({
      ...config,
      stop: () => {
        if (disposed) return
        applyLabelVisibility(instance)
        drawMini()
      },
    })
    layout.run()
    applyLabelVisibility(instance)
    // Fit once more after layout settles so there is no excessive empty space.
    instance.one('layoutstop', () => {
      if (!disposed) instance.fit(undefined, 42)
    })

    let observer = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        if (!disposed) {
          instance.resize()
          drawMini()
        }
      })
      observer.observe(containerRef.current)
    }

    return () => {
      disposed = true
      if (zoomFrameRef.current) cancelAnimationFrame(zoomFrameRef.current)
      if (miniFrameRef.current) cancelAnimationFrame(miniFrameRef.current)
      zoomFrameRef.current = 0
      miniFrameRef.current = 0
      if (observer) observer.disconnect()
      instance.destroy()
      cyRef.current = null
    }
  }, [elements, nodes.length, colorMode, dimension]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Re-run the layout when the mode changes (without a rebuild) --------
  useEffect(() => {
    const instance = cyRef.current
    if (!instance || !instance.nodes().length) return
    rerunLayout()
  }, [layoutMode, rerunLayout])

  // ---- Focus the selected node's neighbourhood ---------------------------
  useEffect(() => {
    const instance = cyRef.current
    if (!instance) return
    applyFocus(instance, selectedSlug, depthRef.current)
  }, [selectedSlug, elements])

  useEffect(() => {
    const instance = cyRef.current
    if (!instance) return
    applyFocus(instance, selectedSlug, depth)
  }, [depth, selectedSlug, elements])

  // ---- Legend / verification toggles --------------------------------------
  useEffect(() => {
    const instance = cyRef.current
    if (!instance) return
    applyRelationFilter(instance, hiddenRelations)
  }, [hiddenRelations, elements])

  // ---- Centre on a searched concept ---------------------------------------
  useEffect(() => {
    const instance = cyRef.current
    if (!instance || !centerOnSlug) return
    const node = instance.getElementById(centerOnSlug)
    if (!node || node.empty()) return
    applyFocus(instance, centerOnSlug, depthRef.current)
    instance.animate(
      { center: { eles: node }, zoom: Math.max(instance.zoom(), 1) },
      { duration: 350 },
    )
  }, [centerOnSlug, elements])

  function zoomBy(factor) {
    const instance = cyRef.current
    if (!instance) return
    instance.zoom({
      level: instance.zoom() * factor,
      renderedPosition: { x: instance.width() / 2, y: instance.height() / 2 },
    })
  }

  if (!nodes.length) {
    return (
      <EmptyState
        title="No concepts in the graph yet"
        description="Upload study material — concepts and their relationships are extracted automatically during processing."
      />
    )
  }

  const relationTypes = [...new Set(edges.map((edge) => edge.relation || 'related_to'))].sort()
  const activeHidden = relationTypes.filter((relation) => hiddenRelations.has(relation))

  function toggleRelation(relation) {
    setHiddenRelations((previous) => {
      const next = new Set(previous)
      if (next.has(relation)) next.delete(relation)
      else next.add(relation)
      return next
    })
  }

  return (
    <div className="kg-graph">
      <div className="kg-graph__toolbar">
        <div className="kg-graph__view-switch" aria-label="Graph dimension">
          <Button aria-pressed={dimension === '3d'} onClick={() => setDimension('3d')}><Box size={14} />3D view</Button>
          <Button aria-pressed={dimension === '2d'} onClick={() => setDimension('2d')}><Network size={14} />2D view</Button>
        </div>
        <div className="kg-graph__counts" aria-live="polite"><span><b>{nodes.length}</b> concepts</span><i /><span><b>{edges.filter((edge) => !hiddenRelations.has(edge.relation || 'related_to')).length}</b> relationships</span></div>
      </div>

      <div className="kg-graph__controls">
        <label><span>Layout</span><Select
          name="graph-layout"
          value={layoutMode}
          onChange={(event) => setLayoutMode(event.target.value)}
          options={LAYOUT_MODES}
          aria-label="Graph layout"
        /></label>
        <label><span>Colour</span><Select
          name="graph-color"
          value={colorMode}
          onChange={(event) => setColorMode(event.target.value)}
          options={COLOR_MODES}
          aria-label="Node colour"
        /></label>
        <label><span>Focus depth</span><Select
          name="graph-depth"
          value={depth}
          onChange={(event) => setDepth(event.target.value)}
          options={DEPTH_MODES}
          aria-label="Neighbourhood depth"
        /></label>
        <label className="kg-visually-hidden"><span>Select concept</span><select aria-label="Select concept" value={selectedSlug || ''} onChange={(event) => onSelectNode?.(event.target.value || null)}><option value="">All concepts</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.label || node.id}</option>)}</select></label>
      </div>

      <div className="kg-graph__canvas-wrap" style={{ height }} ref={wrapperRef}>
        <div className="kg-graph__canvas-heading"><span className="kg-live-dot" />{dimension === '3d' ? 'THREE-DIMENSIONAL EXPLORER' : 'TWO-DIMENSIONAL EXPLORER'}</div>
        {dimension === '3d' ? <Suspense fallback={<div className="kg-graph-empty">Preparing your 3D graph…</div>}>
          <GraphScene3D ref={sceneRef} elements={elements} layoutMode={layoutMode} hiddenRelations={hiddenRelations} selectedSlug={selectedSlug} centerOnSlug={centerOnSlug} depth={depth} showLabels={showLabels} onSelectNode={onSelectNode} onSelectEdge={onSelectEdge} onFallback={() => setDimension('2d')} />
        </Suspense> : <>
          <div className="kg-graph__canvas" ref={containerRef} role="img" aria-label="Interactive 2D knowledge graph. Use the concept selector for keyboard navigation." />
          <canvas ref={minimapRef} width={132} height={84} className="kg-graph__minimap" aria-hidden="true" />
        </>}
        <div className="kg-graph__floating-tools">
          <Button title="Zoom in" aria-label="Zoom in" onClick={() => dimension === '3d' ? sceneRef.current?.zoomBy(1.2) : zoomBy(1.2)}><Plus size={16} /></Button>
          <Button title="Zoom out" aria-label="Zoom out" onClick={() => dimension === '3d' ? sceneRef.current?.zoomBy(1 / 1.2) : zoomBy(1 / 1.2)}><Minus size={16} /></Button>
          <span />
          <Button title="Fit graph to view" aria-label="Fit graph to view" onClick={() => dimension === '3d' ? sceneRef.current?.fit() : cyRef.current?.fit(undefined, 42)}><Maximize size={15} /></Button>
          <Button title="Reset view" aria-label="Reset view" onClick={() => { onSelectNode?.(null); onSelectEdge?.(null); dimension === '3d' ? sceneRef.current?.fit() : cyRef.current?.fit(undefined, 42) }}><RotateCcw size={15} /></Button>
          {dimension === '3d' && <Button title="Toggle concept labels" aria-label="Show concept labels" aria-pressed={showLabels} onClick={() => setShowLabels(!showLabels)}><Eye size={15} /></Button>}
        </div>
        {selectedSlug && <Button className="kg-graph__clear-focus" onClick={() => { onSelectNode?.(null); onSelectEdge?.(null) }}><Focus size={13} /> Clear focus</Button>}
        <div className="kg-graph__gesture"><MousePointer2 size={12} /><span>{dimension === '3d' ? 'Drag to rotate' : 'Drag to pan'}</span><i />Scroll to zoom<i />Click to explore</div>
        {dimension === '3d' && <span className="kg-graph__axis" aria-hidden="true">Y<br />↗ Z　→ X</span>}
        {dimension === '2d' && tooltip ? (
          <div
            className={`kg-graph__tooltip kg-graph__tooltip--${tooltip.tone}`}
            style={{ left: tooltip.left, top: tooltip.top }}
            role="tooltip"
          >
            {tooltip.text}
          </div>
        ) : null}
      </div>

      {relationTypes.length ? (
        <div className="kg-graph__legend">
          <span className="kg-graph__legend-heading">Relationships</span>
          {relationTypes.map((relation) => {
            const lineStyle = (RELATION_STYLES[relation] || DEFAULT_RELATION_STYLE).lineStyle
            const hidden = hiddenRelations.has(relation)
            return (
              <button
                key={relation}
                type="button"
                className={`kg-graph__legend-item${hidden ? ' kg-graph__legend-item--off' : ''}`}
                onClick={() => toggleRelation(relation)}
                aria-pressed={!hidden}
                title={hidden ? `Show ${relation} connections` : `Hide ${relation} connections`}
              >
                <span
                  className="kg-graph__swatch"
                  style={{
                    borderTopColor: RELATION_COLORS[relation] || '#64748b',
                    borderTopStyle: lineStyle,
                  }}
                  aria-hidden="true"
                />
                <span>{relation.replaceAll('_', ' ')}</span>
              </button>
            )
          })}
          {activeHidden.length ? (
            <Button size="sm" variant="secondary" onClick={() => setHiddenRelations(new Set())}>
              Show all
            </Button>
          ) : null}
          <p className="kg-graph__legend-note">Larger nodes = more connections · Dashed lines = inferred or associative · Arrows show direction</p>
        </div>
      ) : null}
    </div>
  )
}
