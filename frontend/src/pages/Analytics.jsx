/**
 * Analytics page — knowledge progress and gap detection (brief §11).
 *
 * Theme-native redesign on the kg-* design system (not a Dashboard clone):
 * tokens only (dark-mode safe), kg-card/kg-grid/kg-badge, staggered fade-ins,
 * animated accuracy meters, hover lifts. Same three data views and API fields:
 * per-subject progress, the knowledge-gap list (with legend), all topics.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, ChartNoAxesCombined, Layers, ClipboardCheck,
  BookOpen, Flame, CircleCheck, TriangleAlert, PauseCircle, Search,
} from 'lucide-react'
import { analyticsApi } from '../services'
import { useToast } from '../context/ToastContext'
import { TOPIC_STATUS_TONES } from '../theme'
import Badge from '../components/Badge'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import './Analytics.css'

const TABS = [
  { id: 'progress', label: 'Progress', icon: ChartNoAxesCombined },
  { id: 'gaps', label: 'Knowledge gaps', icon: TriangleAlert },
  { id: 'topics', label: 'All topics', icon: Layers },
]

function toneFor(status) {
  return TOPIC_STATUS_TONES[status] || 'neutral'
}

const STATUS_ICONS = {
  Strong: CircleCheck,
  'Needs Revision': TriangleAlert,
  'Frequently Missed': Flame,
  'Recently Studied': BookOpen,
  'Not Yet Studied': PauseCircle,
}

const STATUS_META = {
  Strong: { tone: 'success' },
  'Needs Revision': { tone: 'warning' },
  'Frequently Missed': { tone: 'danger' },
  'Recently Studied': { tone: 'info' },
  'Not Yet Studied': { tone: 'neutral' },
}

export default function AnalyticsPage() {
  const { fromError } = useToast()
  const [tab, setTab] = useState('progress')
  const [progress, setProgress] = useState(null)
  const [gaps, setGaps] = useState(null)
  const [topics, setTopics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [problem, setProblem] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setProblem(null)
    try {
      const [progressResponse, gapsResponse, topicsResponse] = await Promise.all([
        analyticsApi.progress(),
        analyticsApi.knowledgeGaps(),
        analyticsApi.topics(),
      ])
      setProgress(progressResponse.data)
      setGaps(gapsResponse.data)
      setTopics(topicsResponse.data)
    } catch (error) {
      setProblem({ message: error?.message, hint: error?.hint })
      fromError(error, 'Could not load analytics')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load()
  }, [load])

  const summary = progress?.summary || {}
  const legend = gaps?.legend || {}

  const heroStats = useMemo(() => ([
    { icon: Layers, value: summary.topics_with_activity ?? 0, label: 'Active topics' },
    { icon: CircleCheck, value: summary.strong_topics ?? 0, label: 'Strong' },
    { icon: TriangleAlert, value: summary.weak_topics ?? 0, label: 'Need attention' },
  ]), [summary])

  if (problem) {
    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>Analytics</h1>
            <p className="kg-subtitle">Could not load your progress data.</p>
          </div>
        </div>
        <Alert
          tone="danger"
          title={problem.message || 'Could not load analytics'}
          hint={problem.hint || 'Check that the backend is running, then retry.'}
        />
        <button type="button" className="btn btn-outline" onClick={load}>Retry</button>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Loading analytics…" />
      </div>
    )
  }

  return (
    <div className="kg-page kg-analytics">
      {/* ---- Hero / heading ---- */}
      <div className="kg-hero kg-analytics-hero kg-fade-in">
        <div className="kg-hero__eyebrow">
          <ChartNoAxesCombined size={15} />
          <span>KNOWLEDGE ANALYTICS</span>
        </div>
        <h1 className="kg-hero__title">
          Know what&apos;s strong.<br />
          <em>Fix what isn&apos;t.</em>
        </h1>
        <p className="kg-hero__copy">
          Labels come from recorded quiz answers, flashcard reviews and search
          history — with published thresholds, never a mystery score.
        </p>
        <div className="kg-hero__actions">
          <Link className="btn btn-primary" to="/quiz">
            Take a quiz <ArrowRight size={14} />
          </Link>
          <Link className="btn btn-outline" to="/flashcards">
            Review flashcards
          </Link>
        </div>
      </div>

      {/* ---- Hero stat chips ---- */}
      <div className="kg-analytics-hero-stats kg-fade-in" style={{ animationDelay: '60ms' }}>
        {heroStats.map((stat) => (
          <div key={stat.label} className="kg-card kg-analytics-stat">
            <span className="kg-analytics-stat-icon"><stat.icon size={18} strokeWidth={1.7} /></span>
            <div>
              <strong>{stat.value}</strong>
              <small>{stat.label}</small>
            </div>
          </div>
        ))}
      </div>

      {/* ---- Tabs ---- */}
      <div className="kg-tabs kg-fade-in" role="tablist" style={{ animationDelay: '120ms' }}>
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            className={`kg-tab${tab === entry.id ? ' kg-tab--active' : ''}`}
            onClick={() => setTab(entry.id)}
          >
            <entry.icon size={14} style={{ marginRight: 6, verticalAlign: '-2px' }} />
            {entry.label}
          </button>
        ))}
      </div>

      {/* ================= PROGRESS ================= */}
      {tab === 'progress' ? (
        <section className="kg-analytics-view kg-fade-in" style={{ animationDelay: '160ms' }}>
          <div className="kg-grid kg-grid-2">
            {(progress?.subjects || []).length ? progress.subjects.map((subject, index) => {
              const rows = subject.topics || []
              const attempts = rows.reduce((sum, row) => sum + (row.attempts || 0), 0)
              const correct = rows.reduce((sum, row) => sum + (row.correct || 0), 0)
              const accuracy = attempts > 0 ? Math.round((correct / attempts) * 100) : null
              const dominant = rows.find((row) => row.status && row.status !== 'Not Yet Studied') || rows[0]
              const status = dominant?.status || 'Not Yet Studied'
              const Icon = STATUS_ICONS[status] || PauseCircle
              return (
                <div key={subject.subject} className="kg-card kg-card--interactive kg-analytics-card kg-fade-in" style={{ animationDelay: `${180 + index * 50}ms` }}>
                  <div className="kg-analytics-card-head">
                    <span className={`kg-analytics-status-icon kg-badge--${STATUS_META[status]?.tone || 'neutral'}`}>
                      <Icon size={16} strokeWidth={1.8} />
                    </span>
                    <h3 className="kg-analytics-card-title">{subject.subject}</h3>
                    <Badge tone={toneFor(status)}>{status}</Badge>
                  </div>
                  <div className="kg-analytics-meter" aria-hidden="true">
                    <span style={{ width: `${accuracy ?? 0}%`, transition: 'width 600ms ease' }} />
                  </div>
                  <div className="kg-row-wrap kg-analytics-card-meta">
                    <span>{correct}/{attempts} correct</span>
                    <span className="kg-dot" style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--kg-border-strong)' }} />
                    <span>{rows.length} topic(s)</span>
                    {accuracy != null ? <span>{accuracy}% accuracy</span> : <span className="kg-text-muted">No answers yet</span>}
                  </div>
                </div>
              )
            }) : (
              <div className="kg-card kg-card--flat kg-analytics-empty kg-fade-in" style={{ animationDelay: '180ms' }}>
                <EmptyState
                  icon="📊"
                  title="No progress yet"
                  description="Study activity will appear here once you review or answer."
                />
              </div>
            )}
          </div>
        </section>
      ) : null}

      {/* ================= GAPS ================= */}
      {tab === 'gaps' ? (
        <section className="kg-analytics-view kg-fade-in" style={{ animationDelay: '160ms' }}>
          <div className="kg-grid kg-grid-wide">
            {/* Weak topics — main column */}
            <div className="kg-stack">
              <div className="kg-page-title">
                <h2 className="kg-analytics-section-title">Weak topics</h2>
                <p className="kg-subtitle">Ordered so the most urgent comes first.</p>
              </div>
              {(gaps?.weak_topics || []).length ? (
                <div className="kg-stack">
                  {gaps.weak_topics.map((topic, index) => {
                    const Icon = STATUS_ICONS[topic.status] || TriangleAlert
                    return (
                      <div key={topic.topic} className="kg-card kg-card--interactive kg-analytics-card kg-fade-in" style={{ animationDelay: `${180 + index * 40}ms` }}>
                        <div className="kg-analytics-card-head">
                          <span className={`kg-analytics-status-icon kg-badge--${STATUS_META[topic.status]?.tone || 'danger'}`}>
                            <Icon size={16} strokeWidth={1.8} />
                          </span>
                          <h3 className="kg-analytics-card-title">{topic.topic}</h3>
                          <Badge tone={toneFor(topic.status)}>{topic.status}</Badge>
                        </div>
                        {topic.explanation ? <p className="kg-analytics-card-reason">{topic.explanation}</p> : null}
                        <div className="kg-row-wrap kg-analytics-card-meta">
                          <span>{topic.correct}/{topic.attempts} correct</span>
                          {topic.days_since_review != null ? (
                            <>
                              <span className="kg-dot" style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--kg-border-strong)' }} />
                              <span>{topic.days_since_review}d since review</span>
                            </>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '180ms' }}>
                  <EmptyState
                    icon="🌱"
                    title="Nothing weak right now"
                    description="Answer more questions and weak spots will surface here."
                  />
                </div>
              )}
            </div>

            {/* Side column — secondary panels */}
            <div className="kg-stack">
              <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '200ms' }}>
                <div className="kg-card__header">
                  <div>
                    <div className="kg-card__title">Not studied yet</div>
                    <p className="kg-card__subtitle">Material with no answers on record.</p>
                  </div>
                </div>
                {(gaps?.not_studied || []).length ? (
                  <div className="kg-stack-sm">
                    {gaps.not_studied.map((topic, i) => (
                      <div key={topic.topic} className="kg-row-between kg-analytics-mini kg-fade-in" style={{ animationDelay: `${220 + i * 25}ms` }}>
                        <span className="kg-truncate">{topic.topic}</span>
                        <Badge tone={toneFor(topic.status)}>{topic.status}</Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="kg-text-sm kg-text-muted">Every topic has some study activity.</p>
                )}
              </div>

              <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '240ms' }}>
                <div className="kg-card__header">
                  <div>
                    <div className="kg-card__title">Not revised recently</div>
                    <p className="kg-card__subtitle">Stale topics (21+ days).</p>
                  </div>
                </div>
                {(gaps?.not_revised_recently || []).length ? (
                  <div className="kg-stack-sm">
                    {gaps.not_revised_recently.map((topic, i) => (
                      <div key={topic.topic} className="kg-row-between kg-analytics-mini kg-fade-in" style={{ animationDelay: `${260 + i * 25}ms` }}>
                        <span className="kg-truncate">{topic.topic}</span>
                        <Badge tone="neutral">{topic.days_since_review}d ago</Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="kg-text-sm kg-text-muted">Everything is fresh.</p>
                )}
              </div>

              <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '280ms' }}>
                <div className="kg-card__header">
                  <div>
                    <div className="kg-card__title">Legend</div>
                    <p className="kg-card__subtitle">Published thresholds, no magic.</p>
                  </div>
                </div>
                <div className="kg-stack-sm">
                  {Object.entries(legend).map(([label, rule], i) => (
                    <div key={label} className="kg-row-between kg-analytics-mini kg-fade-in" style={{ animationDelay: `${300 + i * 25}ms` }}>
                      <Badge tone={toneFor(label)}>{label}</Badge>
                      <span className="kg-text-xs kg-text-muted kg-grow kg-analytics-rule">{rule}</span>
                    </div>
                  ))}
                </div>
              </div>

              {(gaps?.frequently_searched || []).length ? (
                <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '320ms' }}>
                  <div className="kg-card__header">
                    <div>
                      <div className="kg-card__title">Frequently searched</div>
                      <p className="kg-card__subtitle">What you keep looking up may be what to revise.</p>
                    </div>
                    <Search size={16} className="kg-text-muted" />
                  </div>
                  <div className="kg-stack-sm">
                    {gaps.frequently_searched.map((row, i) => (
                      <div key={row.query} className="kg-row-between kg-analytics-mini kg-fade-in" style={{ animationDelay: `${340 + i * 25}ms` }}>
                        <span className="kg-truncate">“{row.query}”</span>
                        <Badge tone="neutral">{row.count}×</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {/* ================= ALL TOPICS ================= */}
      {tab === 'topics' ? (
        <section className="kg-analytics-view kg-fade-in" style={{ animationDelay: '160ms' }}>
          <div className="kg-page-title" style={{ marginBottom: 'var(--kg-space-3)' }}>
            <h2 className="kg-analytics-section-title">{(topics || []).length} topic(s)</h2>
            <p className="kg-subtitle">Every tracked topic, with its label.</p>
          </div>
          {(topics || []).length ? (
            <div className="kg-card kg-card--padded kg-analytics-topics-card kg-fade-in" style={{ animationDelay: '180ms' }}>
              {topics.map((topic, i) => (
                <div key={topic.topic} className="kg-row-between kg-analytics-topic-row kg-fade-in" style={{ animationDelay: `${200 + i * 20}ms` }}>
                  <span className="kg-truncate kg-grow">{topic.topic}</span>
                  <span className="kg-row-wrap">
                    <Badge tone="neutral">{topic.correct}/{topic.attempts}</Badge>
                    <Badge tone={toneFor(topic.status)}>{topic.status}</Badge>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="kg-card kg-card--flat kg-fade-in" style={{ animationDelay: '180ms' }}>
              <EmptyState
                icon="📝"
                title="No study activity yet"
                description="Take a quiz or review flashcards and this list fills up."
              />
            </div>
          )}
        </section>
      ) : null}

      {/* ---- Footer ---- */}
      <footer className="kg-analytics-footer kg-fade-in" style={{ animationDelay: '200ms' }}>
        <span className="kg-text-xs kg-text-muted">Your mind is a garden. Keep growing.</span>
        <span className="kg-text-xs kg-text-muted">KnowGraph · Local-first</span>
      </footer>
    </div>
  )
}
