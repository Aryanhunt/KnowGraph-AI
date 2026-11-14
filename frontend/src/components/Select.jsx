/**
 * Select — native select styled with design tokens.
 *
 * `options` accepts either an array of strings or `{ value, label }` objects,
 * keeping the call sites short.
 */

import { Field } from './Input'
import './forms.css'

export default function Select({
  label,
  id,
  help,
  error,
  options = [],
  placeholder,
  className = '',
  ...rest
}) {
  const selectId = id || rest.name || undefined
  const control = (
    <select
      id={selectId}
      className={`kg-select${error ? ' kg-input--invalid' : ''} ${className}`.trim()}
      {...rest}
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((option) => {
        const value = typeof option === 'string' ? option : option.value
        const text = typeof option === 'string' ? option : option.label ?? option.value
        return (
          <option key={String(value)} value={value}>
            {text}
          </option>
        )
      })}
    </select>
  )
  if (!label && !help && !error) return control
  return (
    <Field label={label} htmlFor={selectId} help={help} error={error}>
      {control}
    </Field>
  )
}