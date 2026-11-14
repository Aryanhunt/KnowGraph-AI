/**
 * Chat page — the five RAG modes plus saved conversations (brief §7, §8).
 *
 * Accepts navigation state from other pages (e.g. DocumentDetail sends
 * `mode: 'document'`). The mode selector always shows which retrieval scope is
 * active, and each assistant message carries its own provenance badge.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { chatApi, documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button from '../components/Button'
import Select from '../components/Select'
import { Textarea } from '../components/Input'
import Badge from '../components/Badge'
import ChatMessage from '../components/ChatMessage'
import Modal from '../components/Modal'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import './Chat.css'

export default function ChatPage() {
  const location = useLocation()
  const { fromError } = useToast()

  const [modes] = useState(null)
  const [documents, setDocuments] = useState([])
  const [subjects, setSubjects] = useState([])
  const [mode, setMode] = useState(location.state?.mode || 'knowledge')
  const [documentIds, setDocumentIds] = useState(location.state?.document_ids || [])
  const [subject, setSubject] = useState('')
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [sessions, setSessions] = useState([])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const endRef = useRef(null)

  // Absorb navigation state from other pages (document detail, documents list).
  useEffect(() => {
    if (location.state?.mode) setMode(location.state.mode)
    if (location.state?.document_ids) setDocumentIds(location.state.document_ids)
  }, [location.state])

  useEffect(() => {
    documentsApi
      .list({ page: 1, page_size: 100, status: 'completed' })
      .then(({ data }) => setDocuments(data || []))
      .catch(() => {})
    documentsApi.subjects().then(({ data }) => setSubjects(data || [])).catch(() => {})
    chatApi
      .sessions()
      .then(({ data }) => setSessions(data || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, asking])

  async function ask(nextQuestion) {
    const text = (nextQuestion ?? question).trim()
    if (!text || asking) return
    if (mode === 'document' && !documentIds.length) {
      fromError({ message: 'Pick a document first.', hint: 'Chat With Document needs one document in scope.' })
      return
    }
    if (mode === 'selected' && !documentIds.length) {
      fromError({ message: 'Select at least one document.', hint: 'Use the checkboxes in the scope panel.' })
      return
    }
    if (mode === 'subject' && !subject) {
      fromError({ message: 'Pick a subject first.', hint: 'Chat With Subject searches that subject only.' })
      return
    }

    setAsking(true)
    setQuestion('')
    const userMessage = { role: 'user', content: text }
    setMessages((current) => [...current, userMessage])

    try {
      const { data } = await chatApi.ask({
        question: text,
        mode,
        document_ids: mode === 'document' || mode === 'selected' ? documentIds : undefined,
        subject: mode === 'subject' ? subject : undefined,
        session_id: sessionId,
      })
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: data.answer,
          sources: data.sources,
          mode: data.mode,
          model: data.model,
          based_on_documents: data.based_on_documents,
          retrieval: data.retrieval,
        },
      ])
      if (data.session_id) setSessionId(data.session_id)
      chatApi.sessions().then(({ data: rows }) => setSessions(rows || [])).catch(() => {})
    } catch (error) {
      fromError(error, 'Could not get an answer')
    } finally {
      setAsking(false)
    }
  }

  async function openSession(id) {
    try {
      const { data } = await chatApi.session(id)
      setMessages((data.messages || []).map((row) => ({ ...row })))
      setSessionId(data.id)
      setMode(data.mode || 'knowledge')
      setShowSessions(false)
    } catch (error) {
      fromError(error, 'Could not open the conversation')
    }
  }

  async function removeSession(id) {
    try {
      await chatApi.removeSession(id)
      setSessions((current) => current.filter((row) => row.id !== id))
      if (sessionId === id) {
        setSessionId(null)
        setMessages([])
      }
    } catch (error) {
      fromError(error, 'Could not delete the conversation')
    }
  }

  function startNew() {
    setSessionId(null)
    setMessages([])
    setQuestion('')
  }

  const scopeSummary = useCallback(() => {
    if (mode === 'knowledge') return 'scope: all processed documents'
    if (mode === 'general') return 'scope: none — General AI'
    if (mode === 'document') {
      const found = documents.find((row) => String(row.id) === String(documentIds[0]))
      return `scope: ${found?.title || 'one document'}`
    }
    if (mode === 'selected') return `scope: ${documentIds.length} selected document(s)`
    if (mode === 'subject') return `scope: subject “${subject || '—'}”`
    return ''
  }, [mode, documents, documentIds, subject])

  const titleMap = Object.fromEntries(documents.map((row) => [String(row.id), row.title]))
  void titleMap

  return (
    <div className="kg-page kg-chat-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>AI Chat</h1>
          <p className="kg-subtitle">Five modes — one rule: RAG answers cite your documents.</p>
        </div>
        <div className="kg-btn-group">
          <Button variant="secondary" size="sm" onClick={() => setShowSessions(true)}>
            Conversations ({sessions.length})
          </Button>
          <Button variant="secondary" size="sm" onClick={startNew}>
            New chat
          </Button>
        </div>
      </div>

      <div className="kg-chat__layout">
        <Card flat>
          <div className="kg-stack">
            <Select
              label="Mode"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
              options={[
                { value: 'knowledge', label: 'Ask My Knowledge (all documents)' },
                { value: 'document', label: 'Chat With Document' },
                { value: 'subject', label: 'Chat With Subject' },
                { value: 'selected', label: 'Selected Documents' },
                { value: 'general', label: 'General AI (no documents)' },
              ]}
            />

            <Badge tone={mode === 'general' ? 'warning' : 'info'}>{scopeSummary()}</Badge>

            {mode === 'document' ? (
              <Select
                label="Document"
                value={documentIds[0] || ''}
                options={documents.map((row) => ({ value: String(row.id), label: row.title }))}
                onChange={(event) => setDocumentIds(event.target.value ? [event.target.value] : [])}
              />
            ) : null}

            {mode === 'subject' ? (
              <Select
                label="Subject"
                value={subject}
                options={subjects.map((row) => ({ value: row.subject, label: `${row.subject} (${row.document_count})` }))}
                onChange={(event) => setSubject(event.target.value)}
              />
            ) : null}

            {mode === 'general' ? (
              <Alert
                tone="warning"
                title="General AI does not use your documents."
                hint="Answers come from the local model alone."
              />
            ) : null}
          </div>
        </Card>

        <div className="kg-chat__thread kg-stack">
          {!messages.length ? (
            <EmptyState
              icon="💬"
              title={mode === 'general' ? 'Ask anything' : 'Ask your knowledge'}
              description={
                mode === 'general'
                  ? 'The local model answers without retrieval.'
                  : 'Answers are grounded in your documents and cite document + page.'
              }
            />
          ) : (
            messages.map((message, index) => <ChatMessage key={index} message={message} />)
          )}

          {asking ? <ChatMessage message={{ role: 'assistant', content: '' }} pending /> : null}
          <div ref={endRef} />

          <form
            className="kg-chat__composer"
            onSubmit={(event) => {
              event.preventDefault()
              ask()
            }}
          >
            <Textarea
              name="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={mode === 'general' ? 'Ask anything…' : 'Ask about your documents…'}
              rows={3}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  ask()
                }
              }}
            />
            <Button type="submit" loading={asking} disabled={asking || !question.trim()}>
              Ask
            </Button>
          </form>

          {mode === 'selected' ? (
            <Card flat>
              <CardHeader title={`Selected documents (${documentIds.length})`} />
              <div className="kg-stack-sm">
                {(documents || []).slice(0, 20).map((row) => (
                  <label key={row.id} className="kg-checkbox">
                    <input
                      type="checkbox"
                      checked={documentIds.includes(String(row.id))}
                      onChange={() =>
                        setDocumentIds((current) => {
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
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      <Modal
        open={showSessions}
        title="Conversations"
        onClose={() => setShowSessions(false)}
        width="min(760px, 100%)"
      >
        <div className="kg-stack-sm">
          {sessions.length ? (
            sessions.map((session) => (
              <div key={session.id} className="kg-row-between">
                <div className="kg-grow">
                  <div className="kg-text-sm kg-truncate">{session.title}</div>
                  <div className="kg-text-xs kg-text-muted">
                    {session.mode} · {session.message_count} message(s)
                  </div>
                </div>
                <div className="kg-row-wrap">
                  <Button size="sm" variant="secondary" onClick={() => openSession(session.id)}>
                    Open
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => removeSession(session.id)}>
                    Delete
                  </Button>
                </div>
              </div>
            ))
          ) : (
            <p className="kg-text-sm kg-text-muted">No saved conversations yet.</p>
          )}
        </div>
      </Modal>
    </div>
  )
}
