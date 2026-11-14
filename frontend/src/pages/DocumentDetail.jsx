/**
 * DocumentDetail — inspect one document: summary, pages (with OCR evidence) and
 * actions (brief §5, §7, §14).
 *
 * Citations land here with `?page=N`, which activates the cited page. Research
 * mode lives behind a tab so the page stays focused for ordinary notes.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Tabs from '../components/Tabs'
import { Input } from '../components/Input'
import StatusPill from '../components/StatusPill'
import Modal from '../components/Modal'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import usePolling from '../hooks/usePolling'
import ResearchPanel from './ResearchPanel'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'pages', label: 'Pages' },
  { id: 'research', label: 'Research mode' },
]

export default function DocumentDetail() {
  const { documentId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { fromError, success } = useToast()

  const [document, setDocument] = useState(null)
  const [pages, setPages] = useState([])
  const [tab, setTab] = useState('overview')
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [form, setForm] = useState({ title: '', subject: '', tags: '' })
  const pageRefs = useRef({})
  const targetPage = Number(searchParams.get('page') || 0)

  const load = useCallback(async () => {
    const { data } = await documentsApi.get(documentId)
    setDocument(data)
    setForm({
      title: data.title || '',
      subject: data.subject || '',
      tags: (data.tags || []).join(', '),
    })
    return data
  }, [documentId])

  const loadPages = useCallback(async () => {
    const { data } = await documentsApi.pages(documentId)
    setPages(data || [])
    return data
  }, [documentId])

  useEffect(() => {
    load().catch((error) => fromError(error, 'Could not load the document'))
    loadPages().catch(() => {})
  }, [load, loadPages, fromError])

  usePolling(
    async () => {
      const { data } = await documentsApi.get(documentId)
      return data
    },
    {
      intervalMs: 3000,
      shouldContinue: (item) =>
        item && item.processing_status !== 'completed' && item.processing_status !== 'failed',
      onTick: (item) => {
        if (!item) return
        setDocument(item)
        if (item.processing_status === 'completed' || item.processing_status === 'failed') {
          loadPages().catch(() => {})
        }
      },
    },
  )

  useEffect(() => {
    if (targetPage > 0) {
      setTab('pages')
      const timer = setTimeout(() => {
        pageRefs.current[targetPage]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 350)
      return () => clearTimeout(timer)
    }
    return undefined
  }, [targetPage, pages.length])

  async function handleSave() {
    try {
      const { data } = await documentsApi.update(documentId, {
        title: form.title,
        subject: form.subject,
        tags: form.tags.split(',').map((item) => item.trim()).filter(Boolean),
      })
      setDocument(data)
      setEditing(false)
      success('Document updated.')
    } catch (error) {
      fromError(error, 'Could not save changes')
    }
  }

  async function handleReprocess() {
    try {
      const { data } = await documentsApi.reprocess(documentId)
      setDocument(data)
      success('Reprocessing started.')
    } catch (error) {
      fromError(error, 'Could not reprocess')
    }
  }

  async function handleDelete() {
    try {
      await documentsApi.remove(documentId)
      success('Document deleted.')
      navigate('/documents')
    } catch (error) {
      fromError(error, 'Could not delete the document')
    }
  }

  if (!document) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Loading document…" />
      </div>
    )
  }

  const failed = document.processing_status === 'failed'

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <Link to="/documents" className="kg-text-sm">
            ← Documents
          </Link>
          <h1>{document.title || document.original_filename}</h1>
          <p className="kg-subtitle">
            {document.original_filename} · {document.file_size_label} · {document.page_count}{' '}
            page(s) · {document.chunk_count} chunks
          </p>
        </div>
        <StatusPill
          status={document.processing_status}
          stageLabel={document.stage_label}
          progress={document.progress}
          error={document.processing_error}
        />
      </div>

      {failed && document.processing_error ? (
        <Alert
          tone="danger"
          title="Processing failed"
          hint={document.processing_error}
          actions={
            <Button size="sm" variant="secondary" onClick={handleReprocess}>
              Reprocess
            </Button>
          }
        />
      ) : null}

      <div className="kg-btn-group">
        <Button size="sm" variant="secondary" onClick={() => setEditing((value) => !value)}>
          {editing ? 'Cancel editing' : 'Edit metadata'}
        </Button>
        <Button size="sm" variant="secondary" onClick={handleReprocess}>
          Reprocess
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            navigate('/chat', { state: { mode: 'document', document_ids: [document.id] } })
          }
        >
          Chat with this document
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
      </div>

      {editing ? (
        <Card>
          <div className="kg-grid kg-grid-2">
            <Input
              label="Title"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
            />
            <Input
              label="Subject"
              value={form.subject}
              onChange={(event) => setForm({ ...form, subject: event.target.value })}
            />
          </div>
          <Input
            label="Tags (comma separated)"
            value={form.tags}
            onChange={(event) => setForm({ ...form, tags: event.target.value })}
          />
          <Button onClick={handleSave}>Save changes</Button>
        </Card>
      ) : null}

      <Tabs
        tabs={TABS.map((item) => ({
          ...item,
          count: item.id === 'pages' ? pages.length : undefined,
        }))}
        active={tab}
        onChange={setTab}
      />

      {tab === 'overview' ? (
        <div className="kg-stack">
          <Card>
            <CardHeader
              title="Summary"
              subtitle={document.summary_method ? `produced by: ${document.summary_method}` : undefined}
            />
            <p className="kg-prose" style={{ margin: 0 }}>
              {document.summary || 'No summary yet — it appears once processing finishes.'}
            </p>
          </Card>

          <div className="kg-grid kg-grid-2">
            <Card flat>
              <CardHeader title="Topics" />
              <div className="kg-row-wrap">
                {(document.topics || []).length ? (
                  document.topics.map((topic) => <Badge key={topic}>{topic}</Badge>)
                ) : (
                  <span className="kg-text-sm kg-text-muted">No topics extracted yet.</span>
                )}
              </div>
            </Card>
            <Card flat>
              <CardHeader title="Details" />
              <div className="kg-stack-sm kg-text-sm">
                <div className="kg-row-between">
                  <span className="kg-text-muted">Language</span>
                  <span>{document.language || 'not detected'}</span>
                </div>
                <div className="kg-row-between">
                  <span className="kg-text-muted">OCR used</span>
                  <span>
                    {document.ocr_used ? `yes — ${document.ocr_page_count || '?'} page(s)` : 'no'}
                  </span>
                </div>
                <div className="kg-row-between">
                  <span className="kg-text-muted">Embedding model</span>
                  <span className="kg-mono">{document.embedding_model || '—'}</span>
                </div>
                <div className="kg-row-between">
                  <span className="kg-text-muted">Subject</span>
                  <span>{document.subject || '—'}</span>
                </div>
              </div>
            </Card>
          </div>
        </div>
      ) : null}

      {tab === 'pages' ? (
        <div className="kg-stack">
          {pages.length ? (
            pages.map((page) => (
              <Card key={page.page_number} flat={page.page_number !== targetPage}>
                <div
                  ref={(element) => {
                    pageRefs.current[page.page_number] = element
                  }}
                >
                  <CardHeader
                    title={`${page.section_title ? `${page.section_title} — ` : ''}Page ${page.page_number}`}
                    actions={
                      <div className="kg-row-wrap">
                        {page.ocr_used ? (
                          <Badge
                            tone="warning"
                            title={
                              page.ocr_confidence != null
                                ? `OCR confidence: ${page.ocr_confidence}%`
                                : undefined
                            }
                          >
                            OCR{page.ocr_confidence != null ? ` ${page.ocr_confidence}%` : ''}
                          </Badge>
                        ) : (
                          <Badge tone="success">digital text</Badge>
                        )}
                        <Badge tone="neutral">{page.char_count || 0} chars</Badge>
                        {page.quality_label &&
                        ['poor', 'needs_review', 'unreadable'].includes(
                          (page.quality_label || '').toLowerCase(),
                        ) ? (
                          <Link
                            to={`/documents/${documentId}/ocr`}
                            style={{ textDecoration: 'none' }}
                          >
                            <Badge tone="warning">review OCR</Badge>
                          </Link>
                        ) : null}
                        {page.correction_status ? (
                          <Badge tone="primary">{page.correction_status}</Badge>
                        ) : null}
                      </div>
                    }
                  />
                  <p className="kg-prose" style={{ margin: 0 }}>
                    {page.text || '(no readable text on this page)'}
                  </p>
                </div>
              </Card>
            ))
          ) : (
            <EmptyState
              icon="📄"
              title="Pages are not available yet"
              description="They appear once extraction finishes."
            />
          )}
        </div>
      ) : null}

      {tab === 'research' ? (
        <ResearchPanel documentId={document.id} document={document} />
      ) : null}

      <Modal
        open={confirmDelete}
        title="Delete document?"
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={handleDelete}>
              Delete everything
            </Button>
          </>
        }
      >
        <p className="kg-text-sm">
          “<strong>{document.title}</strong>” will be removed together with its pages, chunks,
          vectors, graph links and study material.
        </p>
      </Modal>
    </div>
  )
}
