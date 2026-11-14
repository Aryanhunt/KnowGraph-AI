/**
 * Navbar — the top bar.
 *
 * Structure matches the improve-UI prototype (.topbar / .breadcrumb /
 * .topbar-right / .preview-indicator / .profile-avatar) while keeping the
 * app's real concerns: local-AI health, theme toggle, global search and the
 * profile menu with sign-out.
 */

import { Search, ChevronRight } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const TITLES = [
  { match: /^\/$/, title: 'Overview' },
  { match: /^\/documents\/[^/]+\/ocr/, title: 'OCR review' },
  { match: /^\/documents\/[^/]+/, title: 'Document' },
  { match: /^\/documents/, title: 'My documents' },
  { match: /^\/search/, title: 'Search' },
  { match: /^\/chat/, title: 'Ask my knowledge' },
  { match: /^\/graph/, title: 'Knowledge graph' },
  { match: /^\/flashcards/, title: 'Flashcards' },
  { match: /^\/quiz/, title: 'Quizzes' },
  { match: /^\/analytics/, title: 'Analytics' },
  { match: /^\/compare/, title: 'Compare documents' },
  { match: /^\/research/, title: 'Research mode' },
  { match: /^\/settings/, title: 'Settings' },
]

export default function Navbar({ health, onSearch }) {
  const { user, logout } = useAuth()
  const location = useLocation()

  const title = (TITLES.find((entry) => entry.match.test(location.pathname)) || {}).title || 'Overview'

  const allOk = health?.ok === true
  const anyKnown = health && (health.llm !== undefined || health.database !== undefined)
  const healthLabel = allOk ? 'Local AI ready' : anyKnown ? 'Local AI degraded' : 'Checking…'
  const healthTone = allOk ? '#80916b' : anyKnown ? '#b08968' : '#9a9f91'
  const healthTitle = anyKnown
    ? [
        `Ollama: ${health.llm?.available ? 'running' : 'not running'} (${health.llm?.model || '—'})`,
        `Embeddings: ${health.embeddings?.available ? 'ok' : 'not available'}`,
        `OCR: ${health.ocr?.available ? 'ok' : 'not available'}`,
        `Vector DB: ${health.vector_store?.available ? 'ok' : 'not available'}`,
        `MongoDB: ${health.database?.available ? 'connected' : 'not reachable'}`,
      ].join(' · ')
    : 'Checking local services…'

  const initial = (user?.full_name || user?.email || '?').trim().charAt(0).toUpperCase()

  return (
    <header className="topbar">
      <div className="breadcrumb">
        <span>{user?.full_name ? `${user.full_name}'s workspace` : 'Personal workspace'}</span>
        <ChevronRight size={13} />
        <strong>{title}</strong>
      </div>

      <div className="topbar-right">
        <span className="preview-indicator" title={healthTitle} style={{ cursor: 'help' }}>
          <span style={{ background: healthTone }} /> {healthLabel}
        </span>

        <button
          type="button"
          className="icon-button"
          onClick={onSearch}
          aria-label="Open global search"
          title="Search"
        >
          <Search size={16} />
        </button>

        {user ? (
          <details className="profile-details">
            <summary className="profile-avatar" title={user.full_name || user.email}>
              {initial}
            </summary>
            <div className="profile-menu">
              <div>
                <strong>{user.full_name}</strong>
              </div>
              <div className="profile-menu-email">{user.email}</div>
              <button
                type="button"
                className="btn btn-outline btn-block"
                onClick={logout}
              >
                Sign out
              </button>
            </div>
          </details>
        ) : null}
      </div>
    </header>
  )
}
