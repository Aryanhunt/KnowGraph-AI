'use client'

import { Component, forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { Billboard, Html, Line, OrbitControls } from '@react-three/drei'
import { Quaternion, Vector3 } from 'three'
import { spatialLayout, visibleNeighborhood } from './graph-layout'
import { readToken } from './graph-theme'

class SceneBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <div className="kg-graph-empty"><h3>3D is unavailable in this browser</h3><p>You can still explore every concept in the 2D view.</p><button type="button" className="kg-graph-button" onClick={this.props.onFallback}>Switch to 2D</button></div>
    return this.props.children
  }
}

const CameraRig = forwardRef(function CameraRig({ radius, nodes, centerOnSlug }, ref) {
  const { camera, size, invalidate } = useThree()
  const controls = useRef(null)
  const fit = () => {
    const distance = radius / Math.sin((camera.fov * Math.PI / 180) / 2) * Math.max(1, size.height / size.width) * 1.12
    controls.current?.target.set(0, 0, 0)
    camera.position.set(distance * 0.12, distance * 0.08, distance)
    camera.near = 0.1
    camera.far = Math.max(12000, distance * 8)
    camera.updateProjectionMatrix()
    controls.current?.update()
    invalidate()
  }
  useImperativeHandle(ref, () => ({
    fit,
    zoomBy(factor) {
      const target = controls.current?.target || new Vector3()
      camera.position.sub(target).multiplyScalar(1 / factor).add(target)
      controls.current?.update()
      invalidate()
    },
  }))
  useEffect(fit, [radius, size.width, size.height])
  useEffect(() => {
    const node = nodes.find((item) => item.id === centerOnSlug)
    if (!node || !controls.current) return
    const target = new Vector3(node.x, node.y, node.z)
    const offset = camera.position.clone().sub(controls.current.target)
    controls.current.target.copy(target)
    camera.position.copy(target).add(offset)
    controls.current.update()
    invalidate()
  }, [centerOnSlug, nodes, camera, invalidate])
  return <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.12} minDistance={35} maxDistance={radius * 18} enablePan />
})

function Concept({ node, color, dimmed, selected, showLabel, onSelect }) {
  const [hovered, setHovered] = useState(false)
  const radius = node.size * 0.24
  return <group position={[node.x, node.y, node.z]}>
    <mesh onClick={(event) => { event.stopPropagation(); onSelect?.(node.id) }} onPointerOver={(event) => { event.stopPropagation(); setHovered(true) }} onPointerOut={() => setHovered(false)}>
      <sphereGeometry args={[radius, 24, 20]} />
      <meshStandardMaterial color={color} roughness={0.4} metalness={0.08} transparent opacity={dimmed ? 0.16 : 1} emissive={color} emissiveIntensity={hovered || selected ? 0.22 : 0.06} />
    </mesh>
    {(selected || hovered) && <Billboard><mesh><ringGeometry args={[radius * 1.4, radius * 1.55, 48]} /><meshBasicMaterial color={color} transparent opacity={0.65} depthWrite={false} /></mesh></Billboard>}
    {(showLabel || selected || hovered) && !dimmed && <Html position={[0, -radius - 6, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: 'none' }}>
      <button type="button" className={`kg-node-label${selected ? ' kg-node-label--selected' : ''}`} style={{ pointerEvents: 'auto' }} onClick={(event) => { event.stopPropagation(); onSelect?.(node.id) }} title={node.tooltip}>{node.label}</button>
    </Html>}
  </group>
}

function Connection({ edge, source, target, dimmed, selected, onSelect }) {
  const [hovered, setHovered] = useState(false)
  const start = new Vector3(source.x, source.y, source.z)
  const end = new Vector3(target.x, target.y, target.z)
  const direction = end.clone().sub(start).normalize()
  const arrowPosition = start.clone().lerp(end, 0.72)
  const rotation = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), direction)
  const opacity = dimmed ? 0.055 : hovered || selected ? 0.95 : 0.34
  const color = selected ? readToken('--kg-primary', '#bd765a') : edge.color
  const click = (event) => { event.stopPropagation(); onSelect?.(edge.raw) }
  return <group>
    <Line points={[start, end]} color={color} lineWidth={hovered || selected ? 2 : 1} transparent opacity={opacity} dashed={edge.verification_status !== 'verified' || edge.lineStyle === 'dashed'} dashSize={4} gapSize={3} onClick={click} onPointerOver={(event) => { event.stopPropagation(); setHovered(true) }} onPointerOut={() => setHovered(false)} />
    {edge.targetArrow !== 'none' && <mesh position={arrowPosition} quaternion={rotation} onClick={click}><coneGeometry args={[2.1, 6, 8]} /><meshBasicMaterial color={color} transparent opacity={opacity} /></mesh>}
    {hovered && <Html position={start.clone().lerp(end, 0.5)} center zIndexRange={[30, 20]} style={{ pointerEvents: 'none' }}><span className="kg-edge-label">{edge.relation.replaceAll('_', ' ')} · {Math.round(edge.confidence * 100)}%</span></Html>}
  </group>
}

const GraphScene3D = forwardRef(function GraphScene3D({ elements, layoutMode, hiddenRelations, selectedSlug, centerOnSlug, depth, showLabels, onSelectNode, onSelectEdge, onFallback }, ref) {
  const layout = useMemo(() => spatialLayout(elements, layoutMode), [elements, layoutMode])
  console.log('[v0] Graph spatial scale', layout.radius, layout.nodes.slice(0, 2))
  const visibleEdges = useMemo(() => layout.edges.filter((edge) => !hiddenRelations.has(edge.relation)), [layout.edges, hiddenRelations])
  const neighborhood = useMemo(() => visibleNeighborhood(selectedSlug, depth, visibleEdges), [selectedSlug, depth, visibleEdges])
  const byId = useMemo(() => new Map(layout.nodes.map((node) => [node.id, node])), [layout.nodes])
  const palette = { hub: readToken('--kg-primary', '#bd765a'), mid: readToken('--kg-secondary', '#6b9982'), leaf: '#7b91b2', isolated: '#9a968c' }
  const important = [...layout.nodes].sort((a, b) => b.degree - a.degree).slice(0, 24).map((node) => node.id)
  return <SceneBoundary onFallback={onFallback}>
    <Canvas frameloop="demand" dpr={[1, 1.75]} camera={{ fov: 42, position: [0, 0, 800], far: 12000 }} gl={{ antialias: true, alpha: true }} onPointerMissed={() => { onSelectNode?.(null); onSelectEdge?.(null) }} fallback={<div className="kg-graph-empty"><p>WebGL is unavailable.</p><button type="button" onClick={onFallback}>Use 2D view</button></div>}>
      <ambientLight intensity={1.8} />
      <directionalLight position={[150, 250, 400]} intensity={2.8} />
      <CameraRig ref={ref} radius={layout.radius} nodes={layout.nodes} centerOnSlug={centerOnSlug} />
      {visibleEdges.map((edge) => <Connection key={edge.id} edge={edge} source={byId.get(edge.source)} target={byId.get(edge.target)} dimmed={neighborhood && (!neighborhood.has(edge.source) || !neighborhood.has(edge.target))} selected={selectedSlug && (edge.source === selectedSlug || edge.target === selectedSlug)} onSelect={onSelectEdge} />)}
      {layout.nodes.map((node) => <Concept key={node.id} node={node} color={palette[node.colorKey] || node.colorKey} selected={selectedSlug === node.id} dimmed={neighborhood && !neighborhood.has(node.id)} showLabel={showLabels && (layout.nodes.length < 35 || important.includes(node.id))} onSelect={onSelectNode} />)}
    </Canvas>
  </SceneBoundary>
})
export default GraphScene3D
