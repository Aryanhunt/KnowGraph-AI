/**
 * OcrReview — page-by-page OCR inspection and correction.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Badge from '../components/Badge'
import Button, { ButtonGroup } from '../components/Button'
import Card, { CardHeader } from '../components/Card'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import { Textarea } from '../components/Input'

const QUALITY_TONES = {
  good: 'success',
  acceptable: 'info',
  needs_review: 'warning',
  poor: 'danger',
  unreadable: 'danger',
}

const QUALITY_LABELS = {
  good: 'Good',
  acceptable: 'Acceptable',
  needs_review: 'Needs review',
  poor: 'Poor',
  unreadable: 'Unreadable',
}

function QualityBadge({ label }) {
  const key = (label || '').toLowerCase()
  return <Badge tone={QUALITY_TONES[key] || 'neutral'}>{QUALITY_LABELS[key] || 'Not assessed'}</Badge>
}

export default function OcrReview() {
  const { documentId } = useParams()
  const navigate = useNavigate()
  const { fromError, success } = useToast()

  const [bundle, setBundle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [rerunning, setRerunning] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await documentsApi.ocrReview(documentId)
      setBundle(data)
      const pages = data?.pages || []
      if (pages.length) {
        const flagged = pages.find((p) =>
          ['poor', 'needs_review', 'unreadable'].includes((p.quality_label || '').toLowerCase()),
        )
        setCurrentPage(flagged ? flagged.page_number : pages[0].page_number)
      }
    } catch (error) {
      fromError(error, 'Could not load the OCR review')
    } finally {
      setLoading(false)
    }
  }, [documentId, fromError])

  useEffect(() => {
    load()
  }, [load])

  const pages = useMemo(() => bundle?.pages || [], [bundle])
  const summary = bundle?.summary || {}
  const page = useMemo(
    () => pages.find((p) => p.page_number === currentPage) || null,
    [pages, currentPage],
  )

  useEffect(() => {
    setDraft(page ? page.effective_text || '' : '')
    setDirty(false)
  }, [page])

  async function refresh() {
    const { data } = await documentsApi.ocrReview(documentId)
    setBundle(data)
  }

  function gotoPage(next) {
    if (!pages.length) return
    const numbers = pages.map((p) => p.page_number).sort((a, b) => a - b)
    const idx = numbers.indexOf(currentPage)
    const target = numbers[(idx + next + numbers.length) % numbers.length]
    setCurrentPage(target)
  }

  async function handleSave(markReviewed = false) {
    if (!page) return
    setSaving(true)
    try {
      await documentsApi.ocrSaveCorrection(documentId, page.page_number, {
        corrected_text: draft,
        mark_reviewed: markReviewed,
      })
      success(markReviewed ? 'Correction saved and marked reviewed' : 'Correction saved')
      await refresh()
      setDirty(false)
    } catch (error) {
      fromError(error, 'Could not save the correction')
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    if (!page) return
    setSaving(true)
    try {
      await documentsApi.ocrResetCorrection(documentId, page.page_number)
      success('Correction cleared — original OCR text restored')
      await refresh()
    } catch (error) {
      fromError(error, 'Could not reset the correction')
    } finally {
      setSaving(false)
    }
  }

  async function handleMarkReviewed() {
    if (!page) return
    setSaving(true)
    try {
      await documentsApi.ocrMarkReviewed(documentId, page.page_number)
      success('Page marked as reviewed')
      await refresh()
    } catch (error) {
      fromError(error, 'Could not mark the page as reviewed')
    } finally {
      setSaving(false)
    }
  }

  async function handleRerun() {
    if (!page) return
    setRerunning(true)
    try {
      await documentsApi.ocrRerunPage(documentId, page.page_number)
      success('OCR re-ran for this page')
      await refresh()
    } catch (error) {
      fromError(error, 'Could not re-run OCR for this page')
    } finally {
      setRerunning(false)
    }
  }

  async function handleReindex() {
    setReindexing(true)
    try {
      const { data } = await documentsApi.ocrReindex(documentId, true)
      success(`Re-indexed ${data.chunk_count || 0} chunk(s) with corrected text`)
      await refresh()
    } catch (error) {
      fromError(error, 'Reindexing failed — your corrections are preserved')
    } finally {
      setReindexing(false)
    }
  }

  if (loading) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Loading OCR review…" />
      </div>
    )
  }

  return (
    <div className="kg-page kg-stack">
      <div className="kg-row-between">
        <div>
          <Link to={`/documents/${documentId}`} className="kg-link">
            ← Back to document
          </Link>
          <h1 className="kg-h1">OCR review — {bundle?.document?.title || 'Document'}</h1>
          <p className="kg-text-muted kg-text-sm">
            {summary.total || 0} page(s) · {summary.flagged || 0} flagged for review ·{' '}
            {summary.corrected || 0} corrected · {summary.reviewed || 0} reviewed
            {summary.needs_reindex ? ` · ${summary.needs_reindex} pending reindex` : ''}
          </p>
        </div>
        <ButtonGroup>
          <Button variant="secondary" size="sm" onClick={() => navigate(`/documents/${documentId}`)}>
            Document
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={reindexing}
            disabled={!summary.needs_reindex}
            onClick={handleReindex}
          >
            Reindex corrections
          </Button>
        </ButtonGroup>
      </div>

      {!pages.length ? (
        <EmptyState
          icon="🧾"
          title="No pages to review"
          description="Pages appear once extraction finishes."
        />
      ) : (
        <>
          <div className="kg-row-wrap">
            {pages.map((p) => {
              const key = (p.quality_label || '').toLowerCase()
              const flagged = ['poor', 'needs_review', 'unreadable'].includes(key)
              return (
                <Button
                  key={p.page_number}
                  variant={p.page_number === currentPage ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setCurrentPage(p.page_number)}
                >
                  {p.page_number}
                  {flagged ? ' ⚠' : ''}
                  {p.corrected_text ? ' ✎' : ''}
                </Button>
              )
            })}
          </div>

          {page ? (
            <Card>
              <CardHeader
                title={`Page ${page.page_number}${page.section_title ? ` — ${page.section_title}` : ''}`}
                actions={
                  <div className="kg-row-wrap">
                    <QualityBadge label={page.quality_label} />
                    {page.ocr_used ? (
                      <Badge
                        tone="info"
                        title={page.ocr_confidence != null ? `OCR confidence: ${page.ocr_confidence}%` : undefined}
                      >
                        OCR{page.ocr_confidence != null ? ` ${page.ocr_confidence}%` : ''}
                      </Badge>
                    ) : (
                      <Badge tone="success">digital text</Badge>
                    )}
                    {page.corrected_text ? <Badge tone="primary">corrected</Badge> : null}
                    {page.needs_reindex ? <Badge tone="warning">needs reindex</Badge> : null}
                    <Button size="sm" variant="secondary" onClick={() => gotoPage(-1)}>
                      Prev
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => gotoPage(1)}>
                      Next
                    </Button>
                  </div>
                }
              />
              <PageBody
                page={page}
                draft={draft}
                setDraft={setDraft}
                setDirty={setDirty}
                saving={saving}
                rerunning={rerunning}
                handleSave={handleSave}
                handleReset={handleReset}
                handleRerun={handleRerun}
                handleMarkReviewed={handleMarkReviewed}
              />
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}

function PageBody({
  page,
  draft,
  setDraft,
  setDirty,
  saving,
  rerunning,
  handleSave,
  handleReset,
  handleRerun,
  handleMarkReviewed,
}) {
  return (
    <div className="kg-grid-2">
      <div className="kg-stack-sm">
        <div className="kg-text-sm kg-text-muted">Original page image</div>
        <Alert
          tone="info"
          title={page.image_path ? 'Image stored on the server' : 'No stored image'}
          hint={
            page.image_path
              ? `Stored at ${page.image_path}. Images are preserved with the upload and never modified.`
              : 'This page came from digital text, so no page image was rendered.'
          }
        />
        {page.quality_warnings?.length ? (
          <Alert tone="warning" title="Quality warnings">
            <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
              {page.quality_warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Alert>
        ) : null}
        <div className="kg-card kg-card--flat kg-stack-sm" style={{ padding: 'var(--kg-space-3)' }}>
          <div className="kg-row-between kg-text-sm">
            <span className="kg-text-muted">Engine</span>
            <span className="kg-mono">{page.ocr_engine || '—'}</span>
          </div>
          <div className="kg-row-between kg-text-sm">
            <span className="kg-text-muted">Confidence</span>
            <span>{page.ocr_confidence != null ? `${page.ocr_confidence}%` : '—'}</span>
          </div>
          {page.quality_metrics?.word_count != null ? (
            <div className="kg-row-between kg-text-sm">
              <span className="kg-text-muted">Words</span>
              <span>{page.quality_metrics.word_count}</span>
            </div>
          ) : null}
          {page.quality_metrics?.suspicious_char_ratio != null ? (
            <div className="kg-row-between kg-text-sm">
              <span className="kg-text-muted">Unusual chars</span>
              <span>{(page.quality_metrics.suspicious_char_ratio * 100).toFixed(1)}%</span>
            </div>
          ) : null}
          {Object.keys(page.ocr_preprocessing || {}).length ? (
            <div className="kg-text-sm">
              <span className="kg-text-muted">Preprocessing: </span>
              <span className="kg-mono">{Object.keys(page.ocr_preprocessing).join(', ')}</span>
            </div>
          ) : null}
        </div>
      </div>
      <div className="kg-stack-sm">
        <div className="kg-text-sm kg-text-muted">Original OCR output (read-only)</div>
        <pre
          className="kg-card kg-card--flat"
          style={{ padding: 'var(--kg-space-3)', whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto' }}
        >
          {page.original_text || '(no text extracted)'}
        </pre>
        <Textarea
          label="Corrected text (used for search and RAG after reindexing)"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            setDirty(true)
          }}
          rows={12}
          help="Saving a correction marks the page for reindexing."
        />
        <ButtonGroup>
          <Button variant="primary" size="sm" loading={saving} onClick={() => handleSave(false)}>
            Save correction
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => handleSave(true)}>
            Save + review
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={handleReset}>
            Reset
          </Button>
          <Button variant="secondary" size="sm" loading={rerunning} onClick={handleRerun} disabled={!page.image_path}>
            Re-run OCR
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={handleMarkReviewed}>
            Mark reviewed
          </Button>
        </ButtonGroup>
      </div>
    </div>
  )
}


