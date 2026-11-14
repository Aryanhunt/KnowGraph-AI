/**
 * Modal — accessible-enough dialog: Escape closes, backdrop click closes, body
 * scroll is locked while open, focus moves into the dialog.
 */

import { useEffect, useRef } from 'react'
import './forms.css'

export default function Modal({ open, title, onClose, children, footer, width }) {
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    function onKeyDown(event) {
      if (event.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKeyDown)

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panelRef.current?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="kg-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.()
      }}
    >
      <div
        className="kg-modal"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : 'Dialog'}
        tabIndex={-1}
        ref={panelRef}
        style={width ? { width } : undefined}
      >
        <div className="kg-modal__header">
          <div className="kg-modal__title">{title}</div>
          <button type="button" className="kg-modal__close" onClick={onClose} aria-label="Close dialog">
            ×
          </button>
        </div>
        <div className="kg-modal__body">{children}</div>
        {footer ? <div className="kg-modal__footer">{footer}</div> : null}
      </div>
    </div>
  )
}