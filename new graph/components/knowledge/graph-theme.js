export const RELATION_COLORS = {
  requires: '#bd765a', prerequisite_of: '#bd765a', depends_on: '#bd765a',
  causes: '#bd765a', is_a: '#7b91b2', type_of: '#7b91b2', explains: '#9b83ac',
  example_of: '#b09563', used_for: '#9b83ac', application_of: '#9b83ac',
  part_of: '#6b9982', component_of: '#6b9982', contains: '#6b9982',
  contrasts_with: '#b09563', related_to: '#9a968c', defines: '#7b91b2',
}
export function readToken(name, fallback) {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}
export function displayRelation(relation = 'related_to') {
  return relation.replaceAll('_', ' ')
}
