/**
 * Tabs — controlled tab strip used by the document and research pages.
 *
 * Kept fully controlled (no internal state) so the URL/query string can own the
 * active tab and a page can be linked to directly.
 */

import './ui.css'

export default function Tabs({ tabs = [], active, onChange, className = '' }) {
  return (
    <div className={`kg-tabs ${className}`.trim()} role="tablist">
      {tabs.map((tab) => {
        const id = tab.id ?? tab.value ?? tab
        const label = tab.label ?? tab
        const isActive = id === active
        return (
          <button
            key={String(id)}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`kg-tab${isActive ? ' kg-tab--active' : ''}`}
            onClick={() => onChange?.(id)}
          >
            {label}
            {tab.count !== undefined ? (
              <span className="kg-text-xs" style={{ marginLeft: 'var(--kg-space-1)' }}>
                ({tab.count})
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}