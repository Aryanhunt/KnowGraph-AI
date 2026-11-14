import cytoscape from 'cytoscape'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force-3d'

export function spatialLayout(elements, mode) {
  const nodes = elements.filter((item) => !('source' in item.data)).map(({ data }, i) => ({
    ...data, x: Math.sin(i * 2.399) * 140, y: Math.cos(i * 2.399) * 140, z: Math.sin(i * 1.3) * 100,
  }))
  const ids = new Set(nodes.map((node) => node.id))
  const edges = elements.filter((item) => 'source' in item.data && ids.has(item.data.source) && ids.has(item.data.target))
  if (!nodes.length) return { nodes: [], edges: [], radius: 200 }
  const effective = mode === 'auto' ? (edges.some(({ data }) => ['requires', 'prerequisite_of', 'depends_on'].includes(data.relation)) ? 'hierarchical' : 'force') : mode
  if (effective === 'force') {
    const links = edges.map(({ data }) => ({ source: data.source, target: data.target }))
    const simulation = forceSimulation(nodes, 3).stop()
      .force('link', forceLink(links).id((node) => node.id).distance(100).strength(0.6))
      .force('charge', forceManyBody().strength(-360))
      .force('center', forceCenter(0, 0, 0))
      .force('collide', forceCollide().radius((node) => node.size + 15))
    for (let i = 0; i < 220; i++) simulation.tick()
    simulation.stop()
  } else {
    const instance = cytoscape({
      headless: true, styleEnabled: false,
      elements: [...nodes.map((node) => ({ data: { id: node.id, degree: node.degree } })), ...edges],
    })
    instance.layout(effective === 'radial' ? {
      name: 'concentric', concentric: (node) => node.data('degree'), levelWidth: () => 2,
      minNodeSpacing: 90, avoidOverlap: true, fit: false,
    } : {
      name: 'breadthfirst', directed: true, spacingFactor: 2.8, avoidOverlap: true, fit: false,
    }).run()
    nodes.forEach((node, i) => {
      const point = instance.getElementById(node.id).position()
      node.x = point.x
      node.y = -point.y
      node.z = effective === 'radial' ? Math.sin(i * 2.399) * 40 : Math.sin(i * 2.399) * 24
    })
    instance.destroy()
  }
  for (const axis of ['x', 'y', 'z']) {
    const center = nodes.reduce((sum, node) => sum + node[axis], 0) / nodes.length
    nodes.forEach((node) => { node[axis] -= center })
  }
  const radius = Math.max(110, ...nodes.map((node) => Math.hypot(node.x, node.y, node.z)))
  return { nodes, edges: edges.map(({ data }) => data), radius }
}

export function visibleNeighborhood(slug, depth, edges) {
  if (!slug || depth === 'all') return null
  const found = new Set([slug])
  let frontier = new Set([slug])
  for (let hop = 0; hop < Number(depth); hop++) {
    const next = new Set()
    edges.forEach((edge) => {
      if (frontier.has(edge.source)) next.add(edge.target)
      if (frontier.has(edge.target)) next.add(edge.source)
    })
    next.forEach((id) => found.add(id))
    frontier = next
  }
  return found
}
