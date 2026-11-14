/**
 * Dashboard — "what is happening in my knowledge".
 *
 * Visual structure matches the improve-know-graph-ai-ui prototype
 * (.dashboard-content / .page-heading-row / .hero-panel / .stats-grid /
 * .workspace-lower / .dashboard-footer) — but every number and row comes from
 * the real API. Nothing here is sample data (brief §11/§15).
 */

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Sprout, Plus, ArrowRight, BookOpen, FileText, Layers, ClipboardCheck,
  Search as SearchIcon, ArrowUpRight, Network,
} from 'lucide-react'
import { analyticsApi, documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Notebook from '../components/Notebook'
import StatusPill from '../components/StatusPill'
import { Alert, LoadingBlock } from '../components/Feedback'

const KIND_COLORS = {
  pdf: 'peach', docx: 'sand', doc: 'sand', md: 'lavender',
  txt: 'sage', png: 'sage', jpg: 'sage', jpeg: 'sage',
  webp: 'sage', tif: 'sage', tiff: 'sage', bmp: 'sage',
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { fromError } = useToast()
  const [summary, setSummary] = useState(null)
  const [inProgress, setInProgress] = useState([])
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')

  async function load() {
    try {
      const [{ data: dashboard }, { data: queue }] = await Promise.all([
        analyticsApi.dashboard(),
        documentsApi.queue(),
      ])
      setSummary(dashboard)
      setInProgress(queue)
      setError(null)
    } catch (error_) {
      setError(error_)
      fromError(error_, 'Could not load the dashboard')
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000) // documents finish while this page is open
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const documents = useMemo(() => {
    const rows = summary?.recent_documents || []
    const needle = query.trim().toLowerCase()
    if (!needle) return rows
    return rows.filter((row) =>
      `${row.title || ''} ${row.subject || ''} ${row.original_filename || ''}`
        .toLowerCase()
        .includes(needle),
    )
  }, [summary, query])

  if (error && !summary) {
    return (
      <main className="dashboard-content">
        <Alert tone="danger" title={error.message} hint={error.hint} />
      </main>
    )
  }
  if (!summary) {
    return (
      <main className="dashboard-content">
        <LoadingBlock message="Loading your knowledge…" />
      </main>
    )
  }

  const docStats = summary.documents || {}
  const flashcardCount = summary.flashcards?.total ?? 0
  const quizAttempts = summary.quizzes?.attempts ?? 0
  const quizAvg = summary.quizzes?.average_score

  const processing = docStats.processing_documents ?? inProgress.length
  const ready = Math.max(0, (docStats.total_documents ?? 0) - (docStats.failed_documents ?? 0) - processing)
  const readyLabel = processing > 0 ? `${processing} processing now` : `${ready} ready`

  const stats = [
    { icon: FileText, color: 'peach', value: docStats.total_documents ?? 0, label: 'Documents', note: readyLabel, to: '/documents' },
    { icon: BookOpen, color: 'sage', value: docStats.total_pages ?? 0, label: 'Pages indexed', note: `${docStats.total_chunks ?? 0} chunks`, to: '/documents' },
    { icon: Layers, color: 'lavender', value: flashcardCount, label: 'Flashcards', note: 'from your own text', to: '/flashcards' },
    { icon: ClipboardCheck, color: 'sand', value: quizAttempts, label: 'Quiz attempts', note: quizAvg != null ? `average ${quizAvg}%` : 'not started yet', to: '/quiz' },
  ]

  return (
    <main className="dashboard-content">
      {/* --- Heading row ------------------------------------------------- */}
      <section className="page-heading-row">
        <div>
          <div className="eyebrow">
            <Sprout size={14} /> A good day to grow
          </div>
          <h1>
            Your knowledge, connected<span>.</span>
          </h1>
          <p>A little clarity. A new connection. Your next big idea.</p>
        </div>
        <button
          type="button"
          className="btn btn-outline btn-lg"
          onClick={() => navigate('/documents?action=upload')}
        >
          <Plus size={14} /> Add document
        </button>
      </section>

      {/* --- Hero panel + notebook --------------------------------------- */}
      <section className="notebook-track" aria-label="Interactive knowledge notebook">
        <div className="hero-panel">
          <div className="hero-copy">
            <span className="hero-kicker">
              <span /> Your second brain, a little more human
            </span>
            <h2>
              Big ideas.<br />
              Small beginnings.<br />
              <em>All connected.</em>
            </h2>
            <p>
              Give your curiosity a place to live.<br />
              Turn everyday notes into a world of knowledge.
            </p>
            <div className="hero-actions">
              <button
                type="button"
                className="btn btn-primary btn-lg"
                onClick={() => navigate('/documents')}
              >
                Open my workspace <ArrowRight size={14} />
              </button>
              <span>One idea at a time.</span>
            </div>
            <span className="hero-footnote">
              <BookOpen size={13} /> A new chapter starts with you.
            </span>
          </div>
          <Notebook />
        </div>
        <div className="scroll-track-note">
          <span className="track-line" />
          <span>Keep scrolling. There&apos;s more between the covers.</span>
          <span className="track-line" />
        </div>
      </section>

      {/* --- Live processing --------------------------------------------- */}
      {inProgress.length ? (
        <section aria-label="Documents processing right now" style={{ marginBottom: 20 }}>
          <div className="document-list">
            {inProgress.map((document) => (
              <div key={document.id} className="document-row" style={{ cursor: 'default' }}>
                <Network size={18} />
                <div className="document-info">
                  <strong>{document.title}</strong>
                  <span>Processing…</span>
                </div>
                <StatusPill
                  status={document.processing_status}
                  stageLabel={document.stage_label}
                  progress={document.progress}
                  error={document.processing_error}
                  compact
                />
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {(docStats.failed_documents || 0) > 0 ? (
        <Alert
          tone="danger"
          title={`${docStats.failed_documents} document(s) failed to process.`}
          hint="Open the document list to see each reason and reprocess."
          actions={
            <button type="button" className="btn btn-outline" onClick={() => navigate('/documents')}>
              View documents
            </button>
          }
        />
      ) : null}

      {/* --- Stats grid --------------------------------------------------- */}
      <section className="stats-grid" aria-label="Your workspace statistics">
        {stats.map((stat) => (
          <button
            key={stat.label}
            type="button"
            className="stat-card"
            onClick={() => navigate(stat.to)}
          >
            <span className={`stat-icon ${stat.color}`}>
              <stat.icon size={17} strokeWidth={1.7} />
            </span>
            <span className="stat-value">{String(stat.value).padStart(2, '0')}</span>
            <strong>{stat.label}</strong>
            <span className="stat-note">{stat.note}</span>
          </button>
        ))}
      </section>

      {/* --- Documents + learning card ------------------------------------ */}
      <section className="workspace-lower">
        <section className="documents-section" aria-label="Recent documents">
          <div className="section-title">
            <div>
              <h2>My documents</h2>
              <p>Your latest uploads, ready to open.</p>
            </div>
            <Link className="sample-label" to="/documents" style={{ textDecoration: 'none' }}>
              VIEW ALL
            </Link>
          </div>

          <div className="document-search">
            <SearchIcon size={15} />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search your documents…"
              aria-label="Search recent documents"
            />
          </div>

          <div className="document-list">
            {documents.length ? (
              documents.map((document) => {
                const kind = (document.file_type || 'file').toLowerCase()
                return (
                  <button
                    key={document.id || document._id}
                    type="button"
                    className="document-row"
                    onClick={() => navigate(`/documents/${document.id || document._id}`)}
                  >
                    <span className={`document-icon ${KIND_COLORS[kind] || 'sage'}`}>
                      <FileText size={21} strokeWidth={1.5} />
                      <small>{kind.toUpperCase().slice(0, 4)}</small>
                    </span>
                    <span className="document-info">
                      <strong>{document.title || document.original_filename || 'Untitled document'}</strong>
                      <span>
                        {document.subject || 'No subject'}
                        <span className="dot-separator">·</span>
                        {document.page_count || 0} pages
                      </span>
                    </span>
                    <ArrowUpRight size={17} />
                  </button>
                )
              })
            ) : (
              <p className="no-results">
                {query
                  ? `No documents match “${query}”. Try another topic.`
                  : 'Nothing uploaded yet. Add your first document to begin.'}
              </p>
            )}
          </div>
        </section>

        <aside className="learning-card">
          <span className="eyebrow">
            <Sprout size={14} /> A little every day
          </span>
          <div className="study-illustration" aria-hidden="true">
            <span className="mini-card back-card" />
            <span className="mini-card middle-card" />
            <span className="mini-card front-card">
              <Sprout size={30} strokeWidth={1.1} />
              <span>Let it sink in.</span>
              <small>LEARN · CONNECT · GROW</small>
            </span>
          </div>
          <h2>
            Don&apos;t just collect.<br />
            <em>Connect the dots.</em>
          </h2>
          <p>Turn what you&apos;ve read into what you know, one flashcard at a time.</p>
          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() => navigate('/flashcards')}
          >
            A little study session <ArrowRight size={14} />
          </button>
          <small>
            {flashcardCount
              ? `${flashcardCount} card${flashcardCount === 1 ? '' : 's'} ready to review`
              : 'Generate your first deck from any document'}
          </small>
        </aside>
      </section>

      <footer className="dashboard-footer">
        <span>
          <Sprout size={13} /> Your mind is a garden. Keep growing.
        </span>
        <span>KnowGraph · Local-first</span>
      </footer>
    </main>
  )
}
