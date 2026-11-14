/**
 * Settings page — local-stack status, active configuration and profile (brief §22).
 *
 * The health panel is the honest answer to "why isn't something working?": every
 * local dependency (MongoDB, Ollama, embeddings, OCR, vector store, job queue) is
 * listed with its availability and, when unavailable, the exact reason.
 */

import { useCallback, useEffect, useState } from 'react'
import { authApi, systemApi } from '../services'
import { useToast } from '../context/ToastContext'
import { useAuth } from '../context/AuthContext'
import Card, { CardHeader } from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Badge, { DotBadge } from '../components/Badge'
import Modal from '../components/Modal'
import { Input } from '../components/Input'
import { Alert, LoadingBlock } from '../components/Feedback'

function ServiceRow({ name, service, hint }) {
  const available = Boolean(service?.available)
  const detail = service?.reason || service?.error || hint
  return (
    <div className="kg-row-between">
      <div className="kg-grow">
        <div className="kg-text-sm" style={{ fontWeight: 600 }}>
          {name}
        </div>
        {detail ? <div className="kg-text-xs kg-text-muted">{detail}</div> : null}
      </div>
      <DotBadge tone={available ? 'success' : 'danger'}>
        {available ? 'available' : 'unavailable'}
      </DotBadge>
    </div>
  )
}

export default function SettingsPage() {
  const { fromError, success } = useToast()
  const { user } = useAuth()

  const [health, setHealth] = useState(null)
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [passwordForm, setPasswordForm] = useState({ current_password: '', new_password: '' })
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [{ data: healthData }, { data: configData }] = await Promise.all([
        systemApi.health(),
        systemApi.config(),
      ])
      setHealth(healthData)
      setConfig(configData)
    } catch (error) {
      fromError(error, 'Could not load system status')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load()
  }, [load])

  async function changePassword() {
    setSaving(true)
    try {
      await authApi.changePassword(passwordForm)
      setShowPassword(false)
      setPasswordForm({ current_password: '', new_password: '' })
      success('Password changed.')
    } catch (error) {
      fromError(error, 'Could not change the password')
    } finally {
      setSaving(false)
    }
  }

  if (loading && !health) {
    return (
      <div className="kg-page">
        <LoadingBlock message="Checking your local AI stack…" />
      </div>
    )
  }

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Settings</h1>
          <p className="kg-subtitle">Local-first by design: your documents never leave this machine.</p>
        </div>
        <Button variant="secondary" onClick={load}>
          Re-check services
        </Button>
      </div>

      {!health?.ok ? (
        <Alert
          tone="warning"
          title="Some local services are not available."
          hint="Everything still runs, but search/chat/OCR may fall back to simpler behaviour — the reasons are listed below."
        />
      ) : (
        <Alert
          tone="success"
          title="All local services are available."
          hint="Full pipeline, semantic search and local LLM answering are enabled."
        />
      )}

      <div className="kg-grid kg-grid-2">
        <Card>
          <CardHeader title="Local AI stack" subtitle="Status of every dependency." />
          <div className="kg-stack">
            <ServiceRow name="MongoDB (metadata)" service={health?.database} />
            <ServiceRow
              name={`Ollama LLM — ${health?.llm?.model || '—'}`}
              service={health?.llm}
              hint={health?.llm?.hint}
            />
            <ServiceRow
              name={`Embeddings — ${config?.embeddings?.model || '—'}`}
              service={health?.embeddings}
            />
            <ServiceRow
              name={`OCR — ${health?.ocr?.engine || config?.ocr?.engine || '—'}`}
              service={health?.ocr}
            />
            <ServiceRow
              name={`Vector store — ${health?.vector_store?.backend || '—'}`}
              service={health?.vector_store}
            />
            <div className="kg-row-between">
              <div>
                <div className="kg-text-sm" style={{ fontWeight: 600 }}>
                  Background processing
                </div>
                <div className="kg-text-xs kg-text-muted">
                  {health?.processing?.workers ?? '?'} worker(s) · {health?.processing?.active ?? 0}{' '}
                  active · {health?.processing?.failed ?? 0} failed
                </div>
              </div>
              <DotBadge tone="info">running</DotBadge>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Configuration" subtitle="Change these in backend/.env, then restart." />
          <div className="kg-stack-sm kg-text-sm">
            <div className="kg-row-between">
              <span className="kg-text-muted">LLM</span>
              <span className="kg-mono">
                {config?.llm?.provider}/{config?.llm?.model}
              </span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Embeddings</span>
              <span className="kg-mono">
                {config?.embeddings?.provider}/{config?.embeddings?.model}
              </span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">OCR engine</span>
              <span className="kg-mono">{config?.ocr?.engine}</span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">OCR threshold</span>
              <span>{config?.ocr?.min_chars_per_page} chars/page</span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Vector backend</span>
              <span className="kg-mono">{config?.vector_db?.backend}</span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Chunk size / overlap</span>
              <span>
                {config?.chunking?.chunk_size} / {config?.chunking?.chunk_overlap}
              </span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Retrieval top-k</span>
              <span>{config?.retrieval?.top_k}</span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Hybrid search</span>
              <Badge tone={config?.retrieval?.hybrid ? 'success' : 'neutral'}>
                {config?.retrieval?.hybrid ? 'enabled' : 'disabled'}
              </Badge>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted">Upload limit</span>
              <span>{config?.limits?.max_upload_mb} MB</span>
            </div>
          </div>
          <div className="kg-row-wrap" style={{ marginTop: 'var(--kg-space-3)' }}>
            {(config?.supported_types || []).map((type) => (
              <Badge key={type} tone="neutral">
                .{type}
              </Badge>
            ))}
          </div>
        </Card>
      </div>

      <div className="kg-grid">
        <Card>
          <CardHeader title="Account" subtitle={user?.email} />
          <div className="kg-stack-sm">
            <div className="kg-row-between">
              <span className="kg-text-muted kg-text-sm">Name</span>
              <span className="kg-text-sm">{user?.full_name}</span>
            </div>
            <div className="kg-row-between">
              <span className="kg-text-muted kg-text-sm">Email</span>
              <span className="kg-text-sm kg-truncate">{user?.email}</span>
            </div>
            <ButtonGroup>
              <Button variant="secondary" onClick={() => setShowPassword(true)}>
                Change password
              </Button>
            </ButtonGroup>
          </div>
        </Card>
      </div>

      <Card flat>
        <CardHeader title="Offline behaviour" subtitle="What works without the internet." />
        <div className="kg-stack-sm kg-text-sm">
          <div className="kg-row-between">
            <span>Upload, extraction, OCR, chunking</span>
            <Badge tone="success">offline</Badge>
          </div>
          <div className="kg-row-between">
            <span>Embeddings, vector search, hybrid search</span>
            <Badge tone="success">offline (local models)</Badge>
          </div>
          <div className="kg-row-between">
            <span>RAG answers, summaries, flashcards, quizzes</span>
            <Badge tone="success">offline (Ollama)</Badge>
          </div>
          <div className="kg-row-between">
            <span>Knowledge graph, analytics, learning path</span>
            <Badge tone="success">offline (no model needed)</Badge>
          </div>
          <p className="kg-text-xs kg-text-muted" style={{ margin: 0 }}>
            No online AI API is used anywhere in this project. The health panel above shows exactly which
            local component answered the last request.
          </p>
        </div>
      </Card>

      <Modal
        open={showPassword}
        title="Change password"
        onClose={() => setShowPassword(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowPassword(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={changePassword}>
              Save
            </Button>
          </>
        }
      >
        <div className="kg-stack">
          <Input
            label="Current password"
            type="password"
            value={passwordForm.current_password}
            onChange={(event) =>
              setPasswordForm({ ...passwordForm, current_password: event.target.value })
            }
          />
          <Input
            label="New password"
            type="password"
            value={passwordForm.new_password}
            onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })}
            help="At least 8 characters, and not a common password."
          />
        </div>
      </Modal>
    </div>
  )
}
