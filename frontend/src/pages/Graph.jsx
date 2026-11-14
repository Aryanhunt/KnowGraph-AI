/**
 * Graph page — interactive knowledge-graph explorer (brief §9, §12).
 *
 * Delegates all rendering to KnowledgeWorkspace, which combines the
 * 2D Cytoscape view and the new 3D (@react-three/fiber) view with the
 * real KnowGraph AI backend API.
 */

import KnowledgeWorkspace from '../components/knowledge/KnowledgeWorkspace'

export default function GraphPage() {
  return <KnowledgeWorkspace />
}
