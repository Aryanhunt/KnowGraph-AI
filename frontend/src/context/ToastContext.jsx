/**
 * Toast notifications.
 *
 * Used for background/async outcomes (upload finished, reprocessing started,
 * errors with a hint). Every toast can carry the backend's `hint` so the message
 * the user sees is the actionable one ("Ollama is not running...").
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import './Toast.css'

const ToastContext = createContext(null)

const DEFAULT_DURATION = 5000

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const counter = useRef(0)

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = useCallback(
    ({ title, hint = null, tone = 'info', duration = DEFAULT_DURATION }) => {
      counter.current += 1
      const id = counter.current
      setToasts((current) => [...current, { id, title, hint, tone }])
      if (duration > 0) setTimeout(() => dismiss(id), duration)
      return id
    },
    [dismiss],
  )

  // Consumers use this callback in load effects. Toast changes must not
  // recreate it, otherwise reporting a failed load immediately starts another.
  const fromError = useCallback(
    (error, fallback = 'Request failed') =>
      push({
        title: error?.message || fallback,
        hint: error?.hint || null,
        tone: 'danger',
        duration: 8000,
      }),
    [push],
  )

  const value = useMemo(
    () => ({
      toasts,
      dismiss,
      push,
      success: (title, hint) => push({ title, hint, tone: 'success' }),
      error: (title, hint) => push({ title, hint, tone: 'danger', duration: 8000 }),
      warn: (title, hint) => push({ title, hint, tone: 'warning', duration: 7000 }),
      info: (title, hint) => push({ title, hint, tone: 'info' }),
      /** Render an ApiError (or any Error) with its hint attached. */
      fromError,
    }),
    [toasts, dismiss, push, fromError],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="kg-toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`kg-toast kg-toast--${toast.tone}`}>
            <div className="kg-toast__body">
              <strong>{toast.title}</strong>
              {toast.hint ? <span className="kg-toast__hint">{toast.hint}</span> : null}
            </div>
            <button
              type="button"
              className="kg-toast__close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}

export default ToastContext