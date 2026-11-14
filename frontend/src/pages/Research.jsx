/**
 * Research page — pick a paper and read it in structured mode (brief §14).
 *
 * Research papers are listed first; the comparison tool lives here too, since
 * comparing papers is the most common use of it.
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { compareApi, documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import ResearchPanel from './ResearchPanel'
import { EmptyState, LoadingBlock } from '../components/Feedback'

export default function ResearchPage() {
  const navigate = useNavigate()
  const { fromError } = useToast()

  const [documents, setDocuments] = useState(null)
  const [problem, setProblem] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [compareWith, setCompareWith] = useState([])
  const [comparison, setComparison] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setProblem(null)
    try {
      const { data } = await documentsApi.list({ page: 1, page_size: 100, status: 'completed' })
      const rows = data || []
      setDocuments(rows)
      if (rows.length) setSelectedId((current) => current || rows[0].id)
      return rows
    } catch (error) {
      setProblem({ message: error?.message, hint: error?.hint })
      fromError(error, 'Could not load documents')
      return []
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  if (problem) {
    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>Research mode</h1>
            <p className="kg-subtitle">Could not load your documents.</p>
          </div>
        </div>
        <Alert
          tone="danger"
          title={problem.message || 'Could not load documents'}
          hint={problem.hint || 'Check that the backend is running, then retry.'}
          actions={<Button onClick={load}>Retry</Button>}
        />
      </div>
    )
  }

  async function runComparison() {
    if (!compareWith.length) return
    setBusy(true)
    setComparison(null)
    try {
      const { data } = await compareApi.compare([selectedId, ...compareWith])
      setComparison(data)
    } catch (error) {
      fromError(error, 'Comparison failed')
    } finally {
      setBusy(false)
    }
  }

  if (!documents) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Loading documents…" />
      </div>
    )
  }

  const papersFirst = [...documents].sort((a, b) => {
    const aPaper = a.is_research_paper ? 0 : 1
    const bPaper = b.is_research_paper ? 0 : 1
    return aPaper - bPaper
  })
  const others = papersFirst.filter((row) => String(row.id) !== String(selectedId))

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Research mode</h1>
          <p className="kg-subtitle">
            Structured reading with sources, and “Not found in document” where nothing is stated.
          </p>
        </div>
      </div>

      {!documents.length ? (
        <EmptyState
          icon="🔬"
          title="No processed documents yet"
          description="Upload a research paper, wait for processing, then open this page."
          action={<Button onClick={() => navigate('/documents?action=upload')}>Upload a paper</Button>}
        />
      ) : (
        <div className="kg-grid kg-grid-wide">
          <div className="kg-stack">
            {selectedId ? <ResearchPanel documentId={selectedId} /> : null}
          </div>

          <div className="kg-stack">
            <Card>
              <CardHeader title="Papers" subtitle="Research papers are listed first." />
              <div className="kg-stack-sm">
                {papersFirst.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => setSelectedId(row.id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 'var(--kg-space-2) 0',
                      textAlign: 'left',
                      cursor: 'pointer',
                      width: '100%',
                      fontWeight: String(row.id) === String(selectedId) ? 600 : 400,
                    }}
                  >
                    <span className="kg-text-sm kg-truncate">{row.title}</span>
                    <div className="kg-row-wrap" style={{ marginTop: 2 }}>
                      {row.is_research_paper ? (
                        <Badge tone="info">paper</Badge>
                      ) : (
                        <Badge tone="neutral">document</Badge>
                      )}
                      <Badge tone="neutral">{row.page_count}p</Badge>
                    </div>
                  </button>
                ))}
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Compare with another paper"
                subtitle="Common topics, unique topics and variations (brief §13)."
              />
              <div className="kg-stack-sm">
                {others.map((row) => (
                  <label key={row.id} className="kg-checkbox">
                    <input
                      type="checkbox"
                      checked={compareWith.includes(String(row.id))}
                      onChange={() =>
                        setCompareWith((current) => {
                          const id = String(row.id)
                          return current.includes(id)
                            ? current.filter((item) => item !== id)
                            : [...current, id]
                        })
                      }
                    />
                    <span className="kg-text-sm kg-truncate">{row.title}</span>
                  </label>
                ))}
                <Button size="sm" loading={busy} disabled={!compareWith.length} onClick={runComparison}>
                  Compare
                </Button>
              </div>
            </Card>

            {comparison ? (
              <Card>
                <CardHeader
                  title="Comparison"
                  subtitle={comparison.method}
                  actions={
                    <Button size="sm" variant="ghost" onClick={() => setComparison(null)}>
                      Clear
                    </Button>
                  }
                />
                <div className="kg-stack-sm">
                  {comparison.summary ? <p className="kg-text-sm kg-prose">{comparison.summary}</p> : null}

                  <div className="kg-text-sm" style={{ fontWeight: 600 }}>
                    Common topics
                  </div>
                  <div className="kg-row-wrap">
                    {(comparison.common_topics || []).length ? (
                      comparison.common_topics.map((row) => (
                        <Badge key={row.topic} tone="success">
                          {row.topic}
                        </Badge>
                      ))
                    ) : (
                      <span className="kg-text-sm kg-text-muted">None detected.</span>
                    )}
                  </div>

                  <div className="kg-text-sm" style={{ fontWeight: 600 }}>
                    Unique topics
                  </div>
                  {(comparison.unique_topics || []).length ? (
                    comparison.unique_topics.map((row) => {
                      const label =
                        (comparison.documents || []).find((doc) => doc.id === row.document_id)?.label ||
                        row.document_id
                      return (
                        <div key={row.document_id} className="kg-stack-sm">
                          <span className="kg-text-xs kg-text-muted">{label}</span>
                          <div className="kg-row-wrap">
                            {(row.topics || []).map((topic) => (
                              <Badge key={topic} tone="primary">
                                {topic}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )
                    })
                  ) : (
                    <span className="kg-text-sm kg-text-muted">None detected.</span>
                  )}

                  {(comparison.variations || []).length ? (
                    <>
                      <div className="kg-text-sm" style={{ fontWeight: 600 }}>
                        Variations
                      </div>
                      {comparison.variations.map((row, index) => (
                        <div key={index} className="kg-stack-sm">
                          <Badge tone="warning">{row.topic}</Badge>
                          <span className="kg-text-sm">{row.note}</span>
                          <span className="kg-text-xs kg-text-muted">
                            {(row.documents || []).join(', ')}
                          </span>
                        </div>
                      ))}
                    </>
                  ) : null}

                  {(comparison.notes || []).map((note, index) => (
                    <p key={index} className="kg-text-xs kg-text-muted">
                      {note}
                    </p>
                  ))}
                </div>
              </Card>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
