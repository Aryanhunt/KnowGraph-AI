/**
 * Sidebar — the navigation rail.
 *
 * Visual structure matches the improve-know-graph-ai-ui prototype one-for-one
 * (.sidebar / .brand / .workspace-picker / .nav-group / .nav-item / .local-card),
 * but every item is a real react-router NavLink and the document count comes
 * from the API — nothing is decorative.
 */

import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  BookOpen, LayoutDashboard, Files, Network, MessageSquare, Search,
  Layers, ClipboardCheck, Route, ChartNoAxesCombined, GitCompareArrows,
  Telescope, Settings, Sprout, ShieldCheck, CircleHelp,
} from 'lucide-react'
import { documentsApi } from '../services'
import { useToast } from '../context/ToastContext'

const GROUPS = [
  {
    label: 'Workspace',
    items: [
      { title: 'Overview', to: '/', icon: LayoutDashboard, end: true },
      { title: 'My documents', to: '/documents', icon: Files, count: true },
      { title: 'Knowledge graph', to: '/graph', icon: Network, graphHome: true },
      { title: 'Ask my knowledge', to: '/chat', icon: MessageSquare, spark: true },
      { title: 'Search', to: '/search', icon: Search },
    ],
  },
  {
    label: 'Learn & Explore',
    items: [
      { title: 'Flashcards', to: '/flashcards', icon: Layers },
      { title: 'Quizzes', to: '/quiz', icon: ClipboardCheck },
      { title: 'Learning path', to: '/graph?view=learning-path', icon: Route },
      { title: 'Analytics', to: '/analytics', icon: ChartNoAxesCombined },
    ],
  },
  {
    label: 'Research',
    items: [
      { title: 'Compare documents', to: '/compare', icon: GitCompareArrows },
      { title: 'Research mode', to: '/research', icon: Telescope },
    ],
  },
]

export default function Sidebar({ user }) {
  const toast = useToast()
  const [docCount, setDocCount] = useState(null)

  const location = useLocation()
  const onGraphPage = location.pathname === '/graph'
  const isLearningPathView = onGraphPage && location.search.includes('view=learning-path')

  useEffect(() => {
    let alive = true
    documentsApi
      .stats()
      .then(({ data }) => {
        if (alive) setDocCount(data?.total_documents ?? null)
      })
      .catch(() => {}) // the badge is optional; a dead API must not break the nav
    return () => {
      alive = false
    }
  }, [])

  const initial = (user?.full_name || user?.email || 'P').trim().charAt(0).toUpperCase()

  return (
    <>
      <aside className="sidebar" aria-label="Main navigation">
        <NavLink className="brand" to="/">
          <span className="brand-symbol">
            <BookOpen size={23} strokeWidth={1.7} />
          </span>
          <span>
            knowgraph<span className="brand-dot">.</span>
          </span>
          <span className="brand-ai">AI</span>
        </NavLink>


        <NavLink className="workspace-picker" to="/settings">
          <span className="workspace-avatar">{initial}</span>
          <span>
            {user?.full_name || 'Personal workspace'}
            <small>{user?.email || 'Just for your curious mind'}</small>
          </span>
        </NavLink>

        <nav>
          {GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <p>{group.label}</p>
              {group.items.map((item) => (
                <NavLink
                  key={item.title}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `nav-item${isActive ? ' nav-active' : ''}`
                  }
                >
                  <item.icon size={17} strokeWidth={1.7} />
                  <span>{item.title}</span>
                  {item.count && docCount != null ? (
                    <span className="nav-count">{docCount}</span>
                  ) : null}
                  {item.spark ? <span className="nav-spark">✧</span> : null}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="local-card">
            <div className="local-icon">
              <ShieldCheck size={17} />
            </div>
            <div>
              <strong>Your knowledge. Yours.</strong>
              <p>Built to live on your device.</p>
            </div>
          </div>

          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-item${isActive ? ' nav-active' : ''}`}
          >
            <Settings size={17} strokeWidth={1.7} />
            <span>Settings</span>
          </NavLink>
          <button
            type="button"
            className="nav-item"
            onClick={() =>
              toast.info(
                'Getting started',
                'Upload a document, then ask your knowledge or open the graph. Everything runs locally.',
              )
            }
          >
            <CircleHelp size={17} strokeWidth={1.7} />
            <span>Help &amp; getting started</span>
            <span className="help-arrow">↗</span>
          </button>

          <div className="sidebar-foot">
            <span>
              <Sprout size={13} /> Made for a curious mind
            </span>
          </div>
        </div>
      </aside>
    </>
  )
}
