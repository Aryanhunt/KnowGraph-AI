/**
 * Form controls: Field wrapper, Input, Textarea, Checkbox.
 *
 * Keeping them together avoids duplicating label/help/error handling, and all
 * styling lives in the design system.
 */

import './forms.css'

export function Field({ label, htmlFor, help, error, children }) {
  return (
    <div className="kg-field">
      {label ? (
        <label className="kg-label" htmlFor={htmlFor}>
          {label}
        </label>
      ) : null}
      {children}
      {error ? <span className="kg-error-text">{error}</span> : null}
      {!error && help ? <span className="kg-help">{help}</span> : null}
    </div>
  )
}

export function Input({ label, id, help, error, className = '', ...rest }) {
  const inputId = id || rest.name || undefined
  const input = (
    <input
      id={inputId}
      className={`kg-input${error ? ' kg-input--invalid' : ''} ${className}`.trim()}
      aria-invalid={error ? 'true' : undefined}
      {...rest}
    />
  )
  if (!label && !help && !error) return input
  return (
    <Field label={label} htmlFor={inputId} help={help} error={error}>
      {input}
    </Field>
  )
}

export function Textarea({ label, id, help, error, className = '', ...rest }) {
  const inputId = id || rest.name || undefined
  const control = (
    <textarea
      id={inputId}
      className={`kg-textarea${error ? ' kg-input--invalid' : ''} ${className}`.trim()}
      aria-invalid={error ? 'true' : undefined}
      {...rest}
    />
  )
  if (!label && !help && !error) return control
  return (
    <Field label={label} htmlFor={inputId} help={help} error={error}>
      {control}
    </Field>
  )
}

export function Checkbox({ label, id, className = '', ...rest }) {
  const inputId = id || rest.name || undefined
  return (
    <label className={`kg-checkbox ${className}`.trim()} htmlFor={inputId}>
      <input id={inputId} type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  )
}