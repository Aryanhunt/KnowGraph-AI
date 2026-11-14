/**
 * HTTP client for the KnowGraph AI backend (brief §20, §22).
 *
 * Responsibilities kept in exactly one place:
 * * base URL (`/api`, proxied by Vite in development),
 * * bearer-token handling and storage,
 * * unwrapping the `{ data, meta }` envelope,
 * * turning every failure into a single `ApiError` shape with `code`, `message`
 *   and `hint`, so components can render the backend's guidance verbatim
 *   ("Ollama is not running. Please start Ollama ...").
 */

const TOKEN_KEY = 'knowgraph.token'
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export class ApiError extends Error {
  constructor({ code, message, hint, details, status }) {
    super(message || 'Request failed')
    this.name = 'ApiError'
    this.code = code || 'request_failed'
    this.hint = hint || null
    this.details = details || null
    this.status = status || 0
  }
}

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token)
    else window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage disabled — the session simply will not persist */
  }
}

function buildUrl(path, query) {
  const base = path.startsWith('/api') ? path : `${API_BASE}${path}`
  if (!query) return base
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item))
    else params.append(key, value)
  })
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

async function parse(response) {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

/**
 * Core request helper.
 *
 * @returns {Promise<{data: any, meta: object|null}>}
 */
export async function request(path, options = {}) {
  const { method = 'GET', body, query, form, signal, timeoutMs } = options
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let payload
  if (form) {
    payload = form
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  // A long RAG answer can legitimately take a while on CPU-only inference.
  const controller = timeoutMs ? new AbortController() : null
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null

  let response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: payload,
      signal: signal || (controller ? controller.signal : undefined),
    })
  } catch (error) {
    clearTimeout(timer)
    const aborted = error?.name === 'AbortError'
    throw new ApiError({
      code: aborted ? 'request_timeout' : 'network_error',
      message: aborted
        ? 'The request took too long and was cancelled.'
        : 'Cannot reach the KnowGraph AI backend.',
      hint: 'Check that the backend is running on http://127.0.0.1:5000.',
    })
  }
  clearTimeout(timer)

  const parsed = await parse(response)

  if (!response.ok) {
    const envelope = parsed && parsed.error ? parsed.error : {}
    if (response.status === 401) setToken(null)
    throw new ApiError({
      code: envelope.code,
      message: envelope.message || `Request failed (HTTP ${response.status})`,
      hint: envelope.hint,
      details: envelope.details,
      status: response.status,
    })
  }

  return { data: parsed?.data ?? null, meta: parsed?.meta ?? null }
}

export const get = (path, query, options = {}) => request(path, { ...options, query })
export const post = (path, body, options = {}) => request(path, { ...options, method: 'POST', body })
export const patch = (path, body, options = {}) => request(path, { ...options, method: 'PATCH', body })
export const del = (path, options = {}) => request(path, { ...options, method: 'DELETE' })
export const postForm = (path, form, options = {}) => request(path, { ...options, method: 'POST', form })

/** Build an ApiError-free error message for display in toasts/alerts. */
export function describeError(error) {
  if (error instanceof ApiError) {
    return {
      title: error.message,
      hint: error.hint,
      code: error.code,
      status: error.status,
    }
  }
  return { title: error?.message || 'Something went wrong.', hint: null, code: 'unknown' }
}

export default { request, get, post, patch, del, postForm, getToken, setToken, ApiError, describeError }