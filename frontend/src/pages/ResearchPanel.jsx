/**
 * Research paper panel — the structured reading view (brief §14).
 *
 * Extracts title/authors/abstract/keywords/objective/methodology/dataset/results/
 * limitations/conclusion. Anything the documents do not contain is reported as
 * "Not found in document" — never guessed — and the action buttons run only over
 * the paper's own text.
 */

import { useCallback, useEffect, useState } from 'react'
import { researchApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Badge from '../components/Badge'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'

const FIELD_ORDER = [
  'title',
  'authors',
  'abstract',
  'keywords',
  'objective',
  'methodology',
  'dataset',
  'results',
  'limitations',
  'conclusion',
]

const FIELD_LABELS = {
  title: 'Title',
  authors: 'Authors',
  abstract: 'Abstract',
  keywords: 'Keywords',
  objective: 'Objective',
  methodology: 'Methodology',
  dataset: 'Dataset',
  results: 'Results',
  limitations: 'Limitations',
  conclusion: 'Conclusion',
}

const ACTIONS = [
  { id: 'summarize', label: 'Summarize' },
  { id: 'methodology', label: 'Explain Methodology' },
  { id: 'limitations', label: 'Find Limitations' },
  { id: 'study_notes', label: 'Generate Study Notes' },
]

export default function ResearchPanel({ documentId, document }) {
  const { fromError } = useToast()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [useLlm, setUseLlm] = useState(true)
  const [actionResult, setActionResult] = useState(null)
  const [actionLoading, setActionLoading] = useState(null)

  const load = useCallback(async () => {
    try {
      const { data: payload } = await researchApi.extract(documentId, useLlm)
      setData(payload)
    } catch (error) {
      fromError(error, 'Could not extract the paper structure')
    } finally {
      setLoading(false)
    }
  }, [documentId, useLlm, fromError])

  useEffect(() => {
    load()
  }, [load])

  async function runAction(action) {
    setActionLoading(action)
    setActionResult(null)
    try {
      const { data: payload } = await researchApi.run(documentId, action)
      setActionResult(payload)
    } catch (error) {
      fromError(error, 'The action failed')
    } finally {
      setActionLoading(null)
    }
  }

  if (loading) {
    return <LoadingBlock message="Extracting the paper structure…" />
  }

  const fields = data?.fields || {}
  const found = data?.found_count ?? 0

  return (
    <div className="kg-stack">
      <Card>
        <div className="kg-row-between" style={{ marginBottom: 'var(--kg-space-3)' }}>
          <div>
            <strong>Structured extraction</strong>
            <div className="kg-text-xs kg-text-muted">
              {found}/{data?.total_fields ?? 0} fields found · {data?.method}
            </div>
          </div>
          <ButtonGroup>
            <Button size="sm" variant={useLlm ? 'primary' : 'secondary'} onClick={() => setUseLlm(true)}>
              With model
            </Button>
            <Button size="sm" variant={!useLlm ? 'primary' : 'secondary'} onClick={() => setUseLlm(false)}>
              Heuristic only
            </Button>
          </ButtonGroup>
        </div>

        <div className="kg-stack-sm">
          {FIELD_ORDER.map((field) => {
            const entry = fields[field] || {}
            return (
              <div key={field} className="kg-row" style={{ alignItems: 'flex-start' }}>
                <span className="kg-text-sm" style={{ minWidth: 110, fontWeight: 600 }}>
                  {FIELD_LABELS[field]}
                </span>
                <div className="kg-grow">
                  {entry.found ? (
                    <p className="kg-prose kg-text-sm" style={{ margin: 0 }}>
                      {entry.value}
                      {entry.source?.page_number ? (
                        <Badge tone="neutral" title="Page where this field was found">
                          {' '}
                          p.{entry.source.page_number}
                        </Badge>
                      ) : null}
                    </p>
                  ) : (
                    <span className="kg-text-sm kg-text-muted">Not found in document</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {found === 0 ? (
          <Alert
            tone="warning"
            title="None of the research fields were recognised."
            hint="This may not be a research paper, or OCR quality may be too low."
          />
        ) : null}
      </Card>

      <Card>
        <div className="kg-stack">
          <div className="kg-row-wrap">
            {ACTIONS.map((action) => (
              <Button
                key={action.id}
                size="sm"
                variant={actionLoading === action.id ? 'primary' : 'secondary'}
                loading={actionLoading === action.id}
                disabled={Boolean(actionLoading)}
                onClick={() => runAction(action.id)}
              >
                {action.label}
              </Button>
            ))}
          </div>

          {actionResult ? (
            <div className="kg-stack-sm">
              <div className="kg-text-xs kg-text-muted">
                {actionResult.answer ? `model: ${actionResult.model}` : ''} · grounded in the paper text
              </div>
              <p className="kg-prose" style={{ margin: 0 }}>
                {actionResult.answer}
              </p>
            </div>
          ) : (
            <p className="kg-text-sm kg-text-muted" style={{ margin: 0 }}>
              Answers use only this paper's text; anything unstated is reported as such.
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
