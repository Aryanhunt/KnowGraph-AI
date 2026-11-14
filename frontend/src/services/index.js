/**
 * Domain API modules (brief §20).
 *
 * Components never call `fetch` directly — they call these functions. Keeping the
 * endpoints in one place means the UI can be redesigned (or the API versioned)
 * without touching component code.
 *
 * Core modules live here; study/analytics/compare/research/system live in
 * `./study` and are re-exported below so there is still one import site.
 */

import { del, get, patch, post, postForm, request } from './api'

export { ApiError, describeError, getToken, setToken } from './api'
export * from './study'

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export const authApi = {
  register: (payload) => post('/auth/register', payload),
  login: (payload) => post('/auth/login', payload),
  me: () => get('/auth/me'),
  changePassword: (payload) => post('/auth/change-password', payload),
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------
export const documentsApi = {
  list: (query) => get('/documents', query),
  get: (id) => get(`/documents/${id}`),
  update: (id, payload) => patch(`/documents/${id}`, payload),
  remove: (id) => del(`/documents/${id}`),
  reprocess: (id) => post(`/documents/${id}/reprocess`),
  queue: () => get('/documents/queue'),
  subjects: () => get('/documents/subjects'),
  tags: () => get('/documents/tags'),
  stats: () => get('/documents/stats'),
  recent: (limit = 5) => get('/documents/recent', { limit }),
  pages: (id) => get(`/documents/${id}/pages`),
  page: (id, pageNumber) => get(`/documents/${id}/pages/${pageNumber}`),
  chunks: (id, limit = 50) => get(`/documents/${id}/chunks`, { limit }),

  // ---------------------------------------------------------------------------
  // OCR review & correction (quality pipeline).
  // ---------------------------------------------------------------------------
  ocrReview: (id) => get(`/documents/${id}/ocr/review`),
  ocrReviewPage: (id, pageNumber) => get(`/documents/${id}/ocr/review/${pageNumber}`),
  ocrSaveCorrection: (id, pageNumber, payload) =>
    request(`/documents/${id}/ocr/review/${pageNumber}/correction`, {
      method: 'PUT',
      body: payload,
    }),
  ocrResetCorrection: (id, pageNumber) =>
    request(`/documents/${id}/ocr/review/${pageNumber}/correction`, {
      method: 'DELETE',
    }),
  ocrMarkReviewed: (id, pageNumber) =>
    post(`/documents/${id}/ocr/review/${pageNumber}/review`),
  ocrRerunPage: (id, pageNumber) =>
    post(`/documents/${id}/ocr/review/${pageNumber}/rerun`),
  ocrReindex: (id, rebuildGraph = true) =>
    post(`/documents/${id}/ocr/reindex`, { rebuild_graph: rebuildGraph }),

  /**
   * Upload with real progress reporting.
   *
   * XHR (not fetch) is used here because it is the only browser API that exposes
   * upload progress events, which the UI needs during a large scanned PDF.
   */
  upload: (file, { subject, onProgress } = {}) => {
    const form = new FormData()
    form.append('file', file)
    if (subject) form.append('subject', subject)
    if (!onProgress) return postForm('/documents', form)

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/documents')
      const token = window.localStorage.getItem('knowgraph.token')
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100))
        }
      }
      xhr.onload = () => {
        let parsed = {}
        try {
          parsed = JSON.parse(xhr.responseText || '{}')
        } catch {
          reject(new Error('The server returned an unreadable response.'))
          return
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve({ data: parsed.data, meta: parsed.meta })
        } else {
          reject(
            Object.assign(new Error(parsed?.error?.message || 'Upload failed'), parsed?.error || {}),
          )
        }
      }
      xhr.onerror = () => reject(new Error('Cannot reach the backend during upload.'))
      xhr.send(form)
    })
  },
}

// ---------------------------------------------------------------------------
// Search (brief §15)
// ---------------------------------------------------------------------------
export const searchApi = {
  run: (payload) => post('/search', payload),
  pages: (query, documentId) => get('/search/pages', { q: query, document_id: documentId }),
  history: () => get('/search/history'),
}

// ---------------------------------------------------------------------------
// Chat — RAG and General AI (brief §7, §8)
// ---------------------------------------------------------------------------
export const chatApi = {
  modes: () => get('/chat/modes'),
  /** Long timeout: CPU-only local inference can take a while on a big question. */
  ask: (payload) => post('/chat/ask', payload, { timeoutMs: 300000 }),
  sessions: () => get('/chat/sessions'),
  session: (id) => get('/chat/sessions/' + id),
  removeSession: (id) => del(`/chat/sessions/${id}`),
}

// ---------------------------------------------------------------------------
// Knowledge graph (brief §9, §12)
// ---------------------------------------------------------------------------
export const graphApi = {
  graph: (query) => get('/graph', query),
  status: () => get('/graph/status'),
  concepts: (query) => get('/graph/concepts', query),
  concept: (slug) => get(`/graph/concepts/${slug}`),
  learningPath: (target, explain = true) =>
    get('/graph/learning-path', { target, explain: explain ? 'true' : 'false' }),
  relations: (query) => get('/graph/relations', query),
  relationEvidence: (source, target, relation) =>
    get('/graph/relations/evidence', { source, target, relation }),
  verifyRelation: (payload) => post('/graph/relations/verify', payload),

  /**
   * Upload a relationship file (PDF/TXT/JSON/JSONL/CSV) that states which concepts
   * relate to which others. The backend matches labels against existing
   * concepts (so "AI" and "Artificial Intelligence" resolve to the same node)
   * and stores matched edges as verified, high-confidence relations.
   */
  uploadRelations: (file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm('/graph/upload-relations', form)
  },
}

export { request }