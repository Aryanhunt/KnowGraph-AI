/**
 * Study, analytics, comparison, research and system API modules.
 *
 * Split from `services/index.js` purely to keep each module small and readable;
 * both files are re-exported from `services/index.js` so components import from a
 * single place.
 */

import { del, get, patch, post } from './api'

// ---------------------------------------------------------------------------
// Study: flashcards + quizzes (brief §10)
// ---------------------------------------------------------------------------
export const studyApi = {
  // --- flashcards -----------------------------------------------------
  generateFlashcards: (payload) =>
    post('/study/flashcards/generate', payload, { timeoutMs: 300000 }),
  flashcards: (query) => get('/study/flashcards', query),
  flashcard: (id) => get(`/study/flashcards/${id}`),
  updateFlashcard: (id, payload) => patch(`/study/flashcards/${id}`, payload),
  reviewFlashcard: (id, outcome) => post(`/study/flashcards/${id}/review`, { outcome }),
  deleteFlashcard: (id) => del(`/study/flashcards/${id}`),

  // --- quizzes --------------------------------------------------------
  generateQuiz: (payload) => post('/study/quizzes/generate', payload, { timeoutMs: 300000 }),
  quizzes: (query) => get('/study/quizzes', query),
  quiz: (id, includeAnswers = false) =>
    get(`/study/quizzes/${id}`, { include_answers: includeAnswers }),
  submitQuiz: (id, answers) => post(`/study/quizzes/${id}/submit`, { answers }),
  quizAttempts: (id) => get(`/study/quizzes/${id}/attempts`),
  deleteQuiz: (id) => del(`/study/quizzes/${id}`),
}

// ---------------------------------------------------------------------------
// Analytics / knowledge gaps (brief §11)
// ---------------------------------------------------------------------------
export const analyticsApi = {
  dashboard: () => get('/analytics/dashboard'),
  knowledgeGaps: () => get('/analytics/knowledge-gaps'),
  progress: () => get('/analytics/progress'),
  topics: () => get('/analytics/topics'),
}

// ---------------------------------------------------------------------------
// Document comparison (brief §13)
// ---------------------------------------------------------------------------
export const compareApi = {
  compare: (documentIds) =>
    post('/compare', { document_ids: documentIds }, { timeoutMs: 300000 }),
}

// ---------------------------------------------------------------------------
// Research paper mode (brief §14)
// ---------------------------------------------------------------------------
export const researchApi = {
  actions: () => get('/research/actions'),
  extract: (documentId, useLlm = true) =>
    get(`/research/${documentId}`, { use_llm: useLlm ? 'true' : 'false' }),
  run: (documentId, action) =>
    post(`/research/${documentId}/action`, { action }, { timeoutMs: 300000 }),
  compare: (documentIds) =>
    post('/research/compare', { document_ids: documentIds }, { timeoutMs: 300000 }),
}

// ---------------------------------------------------------------------------
// System / health (local-first status surfaces)
// ---------------------------------------------------------------------------
export const systemApi = {
  health: () => get('/system/health'),
  config: () => get('/system/config'),
  supportedTypes: () => get('/system/supported-types'),
  session: () => get('/system/session'),
}