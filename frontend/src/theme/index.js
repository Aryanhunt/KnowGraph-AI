/**
 * Theme module (brief §17).
 *
 * Components import token *names* from here instead of hard-coding colours, so a
 * redesign changes `tokens.css` and nothing else. `readToken` is used by libraries
 * that cannot consume CSS variables directly (the Cytoscape graph, for example,
 * needs concrete colour strings).
 */

export const THEMES = ['light', 'dark']

/** Status → token name mapping used by badges, pills and progress bars. */
export const STATUS_TOKENS = {
  success: '--kg-success',
  warning: '--kg-warning',
  danger: '--kg-danger',
  info: '--kg-info',
  neutral: '--kg-muted',
  primary: '--kg-primary',
}

/** Document processing status → badge tone + label (kept in sync with the API). */
export const PROCESSING_STATUS = {
  queued: { tone: 'info', label: 'Queued' },
  extracting_text: { tone: 'info', label: 'Extracting text' },
  running_ocr: { tone: 'warning', label: 'Running OCR' },
  cleaning_text: { tone: 'info', label: 'Cleaning text' },
  creating_chunks: { tone: 'info', label: 'Creating chunks' },
  generating_embeddings: { tone: 'info', label: 'Generating embeddings' },
  extracting_topics: { tone: 'info', label: 'Extracting topics' },
  building_knowledge_graph: { tone: 'info', label: 'Building knowledge graph' },
  completed: { tone: 'success', label: 'Completed' },
  failed: { tone: 'danger', label: 'Failed' },
}

/** Knowledge-gap labels → tone (brief §11 uses plain language, not scores). */
export const TOPIC_STATUS_TONES = {
  Strong: 'success',
  'Needs Revision': 'warning',
  'Frequently Missed': 'danger',
  'Recently Studied': 'info',
  'Not Yet Studied': 'neutral',
}

/** Relation types → colour used by the graph panel (brief §9). */
export const RELATION_COLORS = {
  related_to: '#64748b',
  prerequisite_of: '#4f46e5',
  part_of: '#0f766e',
  explains: '#0ea5e9',
  requires: '#b45309',
  example_of: '#16a34a',
  contrasts_with: '#b91c1c',
}

/** Read a CSS custom property from the DOM (falls back to a literal value). */
export function readToken(name, fallback = '#4f46e5') {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name)
  return (value || '').trim() || fallback
}

/** Convenience: resolve a status tone name (``success``) to an actual colour. */
export function toneColor(tone) {
  return readToken(STATUS_TOKENS[tone] || STATUS_TOKENS.neutral)
}

export function statusMeta(status) {
  return PROCESSING_STATUS[status] || { tone: 'neutral', label: status || 'Unknown' }
}