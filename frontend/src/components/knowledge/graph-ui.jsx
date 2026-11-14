export function Button({ children, variant = 'secondary', size, className = '', ...props }) {
  return <button type="button" className={`kg-graph-button kg-graph-button--${variant} ${className}`} {...props}>{children}</button>
}
export function Badge({ children }) {
  return <span className="kg-graph-badge">{children}</span>
}
export function Select({ options, ...props }) {
  return <select className="kg-graph-select" {...props}>{options.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}</select>
}
export function EmptyState({ title, description }) {
  return <div className="kg-graph-empty"><h3>{title}</h3><p>{description}</p></div>
}