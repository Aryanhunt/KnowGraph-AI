/**
 * Compare page — side-by-side document comparison (brief §13).
 *
 * The deterministic facts (common/unique topics, per-document sources) come from
 * the API; methodology/variation sections only appear when the local model
 * produced them, and each item names the documents it refers to.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { compareApi, documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'

export default function ComparePage() {
  const { fromError } = useToast()
  const [documents, setDocuments] = useState(null)
  const [selected, setSelected] = useState([])
  const [comparison, setComparison] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const { data } = await documentsApi.list({ page: 1, page_size: 100, status: 'completed' })
    setDocuments(data || [])
    return data
  }, [])

  useEffect(() => {
    load().catch((error) => fromError(error, 'Could not load documents'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run() {
    if (selected.length < 2) {
      fromError({ message: 'Select at least two documents.' })
      return
    }
    setBusy(true)
    setComparison(null)
    try {
      const { data } = await compareApi.compare(selected)
      setComparison(data)
    } catch (error) {
      fromError(error, 'Comparison failed')
    } finally {
      setBusy(false)
    }
  }

  function toggle(id) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    )
  }

  if (!documents) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Loading documents…" />
      </div>
    )
  }

  const labelFor = (id) =>
    comparison?.documents?.find((doc) => doc.id === id)?.label ||
    documents.find((doc) => doc.id === id)?.title ||
    id

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Compare documents</h1>
          <p className="kg-subtitle">
            Common topics, unique topics, methodology and variations — every claim keeps its source.
          </p>
        </div>
        <Button loading={busy} disabled={selected.length < 2} onClick={run}>
          Compare {selected.length ? `(${selected.length})` : ''}
        </Button>
      </div>

      {!documents.length ? (
        <EmptyState
          icon="⚖️"
          title="Nothing to compare yet"
          description="Upload and process at least two documents."
          action={<Link to="/documents?action=upload">Upload documents</Link>}
        />
      ) : (
        <>
          <Card flat>
            <CardHeader title={`${selected.length} selected`} subtitle="Pick two or more documents." />
            <div className="kg-stack-sm">
              {documents.map((row) => (
                <label key={row.id} className="kg-checkbox">
                  <input
                    type="checkbox"
                    checked={selected.includes(row.id)}
                    onChange={() => toggle(row.id)}
                  />
                  <span className="kg-text-sm kg-truncate">{row.title}</span>
                  <span className="kg-text-xs kg-text-muted">
                    {row.subject || 'no subject'} · {row.page_count}p
                  </span>
                </label>
              ))}
            </div>
          </Card>

          {comparison ? (
            <div className="kg-stack">
              {(comparison.notes || []).map((note, index) => (
                <Alert key={index} tone="info" title={note} />
              ))}

              {comparison.summary ? (
                <Card>
                  <CardHeader title="Summary" subtitle={comparison.method} />
                  <p className="kg-prose kg-text-sm" style={{ margin: 0 }}>
                    {comparison.summary}
                  </p>
                </Card>
              ) : null}

              <div className="kg-grid kg-grid-2">
                <Card>
                  <CardHeader title="Common topics" subtitle="In every selected document." />
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
                </Card>

                <Card>
                  <CardHeader title="Unique topics" subtitle="Only in one document." />
                  {(comparison.unique_topics || []).length ? (
                    <div className="kg-stack-sm">
                      {comparison.unique_topics.map((row) => (
                        <div key={row.document_id} className="kg-stack-sm">
                          <span className="kg-text-xs kg-text-muted">{labelFor(row.document_id)}</span>
                          <div className="kg-row-wrap">
                            {(row.topics || []).map((topic) => (
                              <Badge key={topic} tone="primary">
                                {topic}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <span className="kg-text-sm kg-text-muted">None detected.</span>
                  )}
                </Card>
              </div>

              {(comparison.methodology || []).length ? (
                <Card>
                  <CardHeader
                    title="Methodology"
                    subtitle="Produced by the local model — check the sources below."
                  />
                  <div className="kg-stack">
                    {comparison.methodology.map((row, index) => (
                      <div key={index} className="kg-stack-sm">
                        <Badge tone="info">{row.document}</Badge>
                        <p className="kg-prose kg-text-sm" style={{ margin: 0 }}>
                          {row.methodology}
                        </p>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : null}

              {(comparison.variations || []).length ? (
                <Card>
                  <CardHeader title="Variations" subtitle="Where the documents differ." />
                  <div className="kg-stack">
                    {comparison.variations.map((row, index) => (
                      <div key={index} className="kg-stack-sm">
                        <div className="kg-row-wrap">
                          <Badge tone="warning">{row.topic}</Badge>
                          <span className="kg-text-xs kg-text-muted">
                            {(row.documents || []).map(labelFor).join(', ')}
                          </span>
                        </div>
                        <span className="kg-text-sm">{row.note}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : null}

              <Card flat>
                <CardHeader title="Sources" />
                <div className="kg-stack-sm">
                  {(comparison.sources || []).map((row) => (
                    <div key={row.document_id} className="kg-row-between">
                      <Link
                        to={`/documents/${row.document_id}`}
                        className="kg-text-sm kg-truncate kg-grow"
                      >
                        {row.label ? `${row.label} — ` : ''}
                        {row.title}
                      </Link>
                      <Badge tone="neutral">{row.reference}</Badge>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
