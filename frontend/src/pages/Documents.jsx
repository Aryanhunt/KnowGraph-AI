/**
 * Documents — upload, filter, monitor and manage the library (brief §4, §5).
 *
 * Live processing progress is polled while any document is unfinished (brief §4);
 * failures surface the backend's reason with a Reprocess action next to them.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { documentsApi, systemApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Select from '../components/Select'
import { Input } from '../components/Input'
import DocumentCard from '../components/DocumentCard'
import UploadDropzone from '../components/UploadDropzone'
import Modal from '../components/Modal'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import usePolling from '../hooks/usePolling'

const STATUSES = [
  { value: '', label: 'All statuses' },
  { value: 'queued', label: 'Queued' },
  { value: 'extracting_text', label: 'Extracting text' },
  { value: 'running_ocr', label: 'Running OCR' },
  { value: 'creating_chunks', label: 'Creating chunks' },
  { value: 'generating_embeddings', label: 'Generating embeddings' },
  { value: 'building_knowledge_graph', label: 'Building knowledge graph' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const TYPES = [
  { value: '', label: 'All types' },
  { value: 'pdf', label: 'PDF' },
  { value: 'png', label: 'Images' },
  { value: 'docx', label: 'DOCX' },
  { value: 'txt', label: 'Text / Markdown' },
]

function isUnfinished(item) {
  return item.processing_status !== 'completed' && item.processing_status !== 'failed'
}

export default function DocumentsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { fromError, success } = useToast()

  const [documents, setDocuments] = useState([])
  const [meta, setMeta] = useState({ total: 0, page: 1, page_size: 12 })
  const [loading, setLoading] = useState(true)
  const [subjects, setSubjects] = useState([])
  const [supportedTypes, setSupportedTypes] = useState([])
  const [showUpload, setShowUpload] = useState(searchParams.get('action') === 'upload')
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [selected, setSelected] = useState(new Set())

  const [filters, setFilters] = useState({
    search: '',
    status: '',
    subject: '',
    document_type: '',
    page: 1,
    page_size: 12,
  })

  const load = useCallback(
    async (nextFilters) => {
      const active = nextFilters || filters
      setLoading(true)
      try {
        const query = { ...active }
        Object.keys(query).forEach((key) => {
          if (query[key] === '' || query[key] == null) delete query[key]
        })
        const { data, meta: responseMeta } = await documentsApi.list(query)
        setDocuments(data || [])
        setMeta(responseMeta || { total: (data || []).length, page: 1, page_size: 12 })
      } catch (error) {
        fromError(error, 'Could not load documents')
      } finally {
        setLoading(false)
      }
    },
    [filters, fromError],
  )

  // Keep processing progress live.
  // Restart live polling whenever a new upload starts: once every document was
  // finished, the poller stops — without a restart a fresh upload would never
  // get progress updates until the page was refreshed.
  const [pollKey, setPollKey] = useState(0)
  usePolling(
    async () => {
      const query = { ...filters, page: filters.page, page_size: filters.page_size }
      const { data } = await documentsApi.list(query)
      return data || []
    },
    {
      intervalMs: 3000,
      shouldContinue: (items) => (items || []).some(isUnfinished),
      onTick: (items) => {
        if (items) {
          setDocuments(items)
          if (!items.some(isUnfinished)) load()
        }
      },
      enabled: true,
      restartKey: pollKey,
    },
  )

  useEffect(() => {
    documentsApi
      .subjects()
      .then(({ data }) => setSubjects(data || []))
      .catch(() => {})
    systemApi
      .supportedTypes()
      .then(({ data }) => setSupportedTypes(data || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => load(), filters.search ? 400 : 0)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search, filters.status, filters.subject, filters.document_type, filters.page])

  const subjectOptions = useMemo(
    () => [{ value: '', label: 'All subjects' }, ...subjects.map((row) => ({
      value: row.subject,
      label: `${row.subject} (${row.document_count})`,
    }))],
    [subjects],
  )

  function patchFilters(patch) {
    setFilters((current) => ({ ...current, ...patch, page: patch.page ?? 1 }))
  }

  // ------------------------------------------------------------------
  // Row actions
  // ------------------------------------------------------------------
  async function handleDelete(item) {
    setConfirmDelete(null)
    try {
      const { data } = await documentsApi.remove(item.id)
      success(`"${item.title}" deleted.`)
      setDocuments((current) => current.filter((row) => row.id !== item.id))
      setMeta((current) => ({ ...current, total: Math.max(0, current.total - 1) }))
      void data
    } catch (error) {
      fromError(error, 'Could not delete the document')
    }
  }

  async function handleReprocess(item) {
    try {
      const { data } = await documentsApi.reprocess(item.id)
      success(`"${item.title}" queued for reprocessing.`)
      setDocuments((current) =>
        current.map((row) => (row.id === item.id ? { ...row, ...data } : row)),
      )
    } catch (error) {
      fromError(error, 'Could not reprocess the document')
    }
  }

  function toggleSelect(id) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const pages = Math.max(1, Math.ceil((meta.total || 0) / (meta.page_size || 12)))

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Documents</h1>
          <p className="kg-subtitle">
            Upload PDFs, scans, images, Word files and notes — extraction, OCR and
            indexing happen automatically.
          </p>
        </div>
        <ButtonGroup>
          {selected.size ? (
            <Button
              variant="secondary"
              onClick={() =>
                navigate('/chat', { state: { mode: 'selected', document_ids: [...selected] } })
              }
            >
              Chat with {selected.size} selected
            </Button>
          ) : null}
          <Button onClick={() => setShowUpload((open) => !open)}>
            {showUpload ? 'Hide upload' : 'Upload documents'}
          </Button>
        </ButtonGroup>
      </div>

      {showUpload ? (
        <Card large>
          <UploadDropzone supportedTypes={supportedTypes} onUploaded={() => { setPollKey((k) => k + 1); load() }} />
        </Card>
      ) : null}

      <Card flat>
        <div className="kg-grid kg-grid-2">
          <Input
            label="Search titles"
            name="doc-search"
            value={filters.search}
            onChange={(event) => patchFilters({ search: event.target.value })}
            placeholder="e.g. DBMS notes"
          />
          <div className="kg-grid kg-grid-2">
            <Select
              label="Status"
              value={filters.status}
              options={STATUSES}
              onChange={(event) => patchFilters({ status: event.target.value })}
            />
            <Select
              label="Subject"
              value={filters.subject}
              options={subjectOptions}
              onChange={(event) => patchFilters({ subject: event.target.value })}
            />
          </div>
          <div className="kg-grid kg-grid-2">
            <Select
              label="Type"
              value={filters.document_type}
              options={TYPES}
              onChange={(event) => patchFilters({ document_type: event.target.value })}
            />
            <div className="kg-field">
              <span className="kg-label">&nbsp;</span>
              <Button
                variant="secondary"
                onClick={() =>
                  setFilters({ search: '', status: '', subject: '', document_type: '', page: 1, page_size: 12 })
                }
              >
                Clear filters
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {loading && !documents.length ? (
        <LoadingBlock message="Loading documents…" />
      ) : documents.length ? (
        <div className="kg-stack">
          {documents.map((document) => (
            <DocumentCard
              key={document.id}
              document={document}
              selectable
              selected={selected.has(document.id)}
              onToggleSelect={toggleSelect}
              onOpen={(item) => navigate(`/documents/${item.id}`)}
              onReprocess={handleReprocess}
              onDelete={(item) => setConfirmDelete(item)}
            />
          ))}

          {pages > 1 ? (
            <div className="kg-row-between">
              <span className="kg-text-sm kg-text-muted">
                Page {meta.page} of {pages} · {meta.total} document(s)
              </span>
              <ButtonGroup>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={meta.page <= 1}
                  onClick={() => patchFilters({ page: meta.page - 1 })}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={meta.page >= pages}
                  onClick={() => patchFilters({ page: meta.page + 1 })}
                >
                  Next
                </Button>
              </ButtonGroup>
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyState
          icon="📚"
          title="No documents match"
          description="Upload a file, or clear the filters to see everything."
        />
      )}

      <Modal
        open={Boolean(confirmDelete)}
        title="Delete document?"
        onClose={() => setConfirmDelete(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(null)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={() => handleDelete(confirmDelete)}>
              Delete everything
            </Button>
          </>
        }
      >
        <div className="kg-stack-sm">
          <p className="kg-text-sm">
            “<strong>{confirmDelete?.title}</strong>” is removed together with its pages,
            chunks, vectors, graph links and study material. This cannot be undone.
          </p>
          <Alert tone="info" title="The original file is deleted from local storage too." />
        </div>
      </Modal>
    </div>
  )
}
