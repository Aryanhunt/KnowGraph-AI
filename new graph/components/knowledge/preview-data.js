const concepts = [
  ['artificial-intelligence', 'Artificial intelligence', 'Foundations', 'The study of systems that perform tasks associated with human intelligence.'],
  ['machine-learning', 'Machine learning', 'Machine learning', 'Methods that learn patterns from data rather than relying only on explicit instructions.'],
  ['deep-learning', 'Deep learning', 'Neural networks', 'Machine learning using neural networks with multiple layers of learned representations.'],
  ['neural-networks', 'Neural networks', 'Neural networks', 'Connected computational units that learn transformations through adjustable weights.'],
  ['supervised-learning', 'Supervised learning', 'Machine learning', 'Learning from examples with known target labels.'],
  ['unsupervised-learning', 'Unsupervised learning', 'Machine learning', 'Discovering structure in data without target labels.'],
  ['reinforcement-learning', 'Reinforcement learning', 'Machine learning', 'Learning a policy through interaction and reward.'],
  ['natural-language', 'Natural language processing', 'Language & reasoning', 'Computational methods for understanding and generating human language.'],
  ['computer-vision', 'Computer vision', 'Neural networks', 'Methods for interpreting visual information.'],
  ['transformers', 'Transformers', 'Language & reasoning', 'Neural architectures built around attention mechanisms.'],
  ['attention', 'Attention mechanisms', 'Language & reasoning', 'Operations that weight the relevance of different input representations.'],
  ['gradient-descent', 'Gradient descent', 'Foundations', 'An iterative method that updates parameters in the direction of decreasing loss.'],
  ['backpropagation', 'Backpropagation', 'Neural networks', 'Efficient computation of gradients through a neural network.'],
  ['linear-algebra', 'Linear algebra', 'Foundations', 'The study of vectors, matrices, and linear transformations.'],
  ['probability', 'Probability', 'Foundations', 'Mathematical tools for reasoning under uncertainty.'],
  ['classification', 'Classification', 'Machine learning', 'Predicting a discrete label from an input.'],
  ['regression', 'Regression', 'Machine learning', 'Predicting a continuous value from an input.'],
  ['embeddings', 'Embeddings', 'Language & reasoning', 'Vector representations that capture meaningful similarities.'],
  ['knowledge-graphs', 'Knowledge graphs', 'Language & reasoning', 'Structured representations of entities and their typed relationships.'],
  ['decision-trees', 'Decision trees', 'Machine learning', 'Models that make predictions through a sequence of branching decisions.'],
  ['optimization', 'Optimization', 'Foundations', 'Finding parameter values that minimize or maximize an objective.'],
]
const links = [
  [1,0,'is_a'], [2,1,'is_a'], [3,2,'part_of'], [4,1,'is_a'], [5,1,'is_a'], [6,1,'is_a'],
  [7,0,'part_of'], [8,0,'part_of'], [9,2,'is_a'], [10,9,'part_of'], [2,3,'requires'],
  [12,11,'used_for'], [11,20,'is_a'], [3,13,'requires'], [1,14,'requires'], [15,4,'is_a'],
  [16,4,'is_a'], [17,7,'used_for'], [18,0,'part_of'], [19,15,'used_for'], [9,7,'used_for'],
  [3,12,'requires'], [8,2,'requires'], [6,14,'requires'], [17,9,'part_of'], [18,7,'related_to'],
  [5,17,'related_to'], [20,13,'requires'],
]
export const previewGraph = {
  nodes: concepts.map(([id, label, subject, definition], i) => ({ id, label, subject, definition, document_count: 1, occurrences: (i % 6) + 2, score: 1 / (i + 1), documents: [{ title: 'Example study notes (preview)' }] })),
  edges: links.map(([source, target, relation], i) => ({ id: `preview-${i}`, source: concepts[source][0], target: concepts[target][0], relation, confidence: i % 5 === 0 ? 0.65 : 0.95, verification_status: i % 5 === 0 ? 'inferred' : 'verified', method: 'preview', weight: 1, evidence: [{ document_title: 'Example study notes (preview)', snippet: `${concepts[source][1]} ${relation.replaceAll('_', ' ')} ${concepts[target][1]}.` }] })),
}

export function filterGraph(graph, { verification, confidence, topic, query }) {
  const nodes = graph.nodes.filter((node) => (!topic || node.subject === topic))
  const ids = new Set(nodes.map((node) => node.id))
  let edges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && Number(edge.confidence || 0) >= confidence && (verification === 'all' || (verification === 'verified' ? edge.verification_status === 'verified' : ['verified', 'inferred'].includes(edge.verification_status))))
  if (!query.trim()) return { nodes, edges }
  const matches = new Set(nodes.filter((node) => `${node.label} ${node.subject || ''}`.toLowerCase().includes(query.toLowerCase().trim())).map((node) => node.id))
  const neighborhood = new Set(matches)
  edges.forEach((edge) => { if (matches.has(edge.source) || matches.has(edge.target)) { neighborhood.add(edge.source); neighborhood.add(edge.target) } })
  edges = edges.filter((edge) => neighborhood.has(edge.source) && neighborhood.has(edge.target))
  return { nodes: nodes.filter((node) => neighborhood.has(node.id)), edges }
}
