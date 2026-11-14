/**
 * Flashcards page — generate, review and manage flashcards (brief §10).
 *
 * Review outcomes (easy/medium/hard) feed knowledge-gap detection. The next-due
 * rule is the backend's and is shown plainly rather than dressed up as "AI".
 */

import { useCallback, useEffect, useState } from 'react'
import { documentsApi, studyApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import { Input, Textarea } from '../components/Input'
import { EmptyState, LoadingBlock } from '../components/Feedback'

const TONES = { easy: 'success', medium: 'warning', hard: 'danger', new: 'neutral' }

export default function FlashcardsPage() {
  const { fromError, success } = useToast()
  const [documents, setDocuments] = useState([])
  const [cards, setCards] = useState([])
  const [meta, setMeta] = useState({ total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [topicFilter, setTopicFilter] = useState('')
  const [revealed, setRevealed] = useState({})

  const [showGenerate, setShowGenerate] = useState(false)
  const [selectedDocs, setSelectedDocs] = useState([])
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(8)
  const [generating, setGenerating] = useState(false)

  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState({ question: '', answer: '', topic: '' })

  const load = useCallback(
    async (page = 1) => {
      setLoading(true)
      try {
        const { data, meta: responseMeta } = await studyApi.flashcards({
          page,
          page_size: 20,
          topic: topicFilter || undefined,
        })
        setCards(data || [])
        setMeta(responseMeta || { total: (data || []).length, page, page_size: 20 })
      } catch (error) {
        fromError(error, 'Could not load flashcards')
      } finally {
        setLoading(false)
      }
    },
    [topicFilter, fromError],
  )

  useEffect(() => {
    load(1)
  }, [topicFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    documentsApi
      .list({ page: 1, page_size: 100, status: 'completed' })
      .then(({ data }) => setDocuments(data || []))
      .catch(() => {})
  }, [])

  async function generate() {
    if (!selectedDocs.length) return
    setGenerating(true)
    try {
      const { data } = await studyApi.generateFlashcards({ document_ids: selectedDocs, topic, count })
      success(`${data.created} flashcard(s) generated (${data.method}).`)
      setShowGenerate(false)
      setSelectedDocs([])
      load(1)
    } catch (error) {
      fromError(error, 'Generation failed')
    } finally {
      setGenerating(false)
    }
  }

  async function saveEdit() {
    try {
      const { data } = await studyApi.updateFlashcard(editing.id, editForm)
      setCards((current) => current.map((row) => (row.id === data.id ? data : row)))
      setEditing(null)
      success('Flashcard updated.')
    } catch (error) {
      fromError(error, 'Could not update the card')
    }
  }

  async function review(card, outcome) {
    try {
      const { data } = await studyApi.reviewFlashcard(card.id, outcome)
      setCards((current) => current.map((row) => (row.id === data.id ? data : row)))
    } catch (error) {
      fromError(error, 'Could not record the review')
    }
  }

  async function remove(card) {
    try {
      await studyApi.deleteFlashcard(card.id)
      setCards((current) => current.filter((row) => row.id !== card.id))
      setMeta((current) => ({ ...current, total: Math.max(0, current.total - 1) }))
      success('Flashcard deleted.')
    } catch (error) {
      fromError(error, 'Could not delete the card')
    }
  }

  const pagesCount = Math.max(1, Math.ceil((meta.total || 0) / (meta.page_size || 20)))

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Flashcards</h1>
          <p className="kg-subtitle">
            {meta.total} card(s) — mark easy / medium / hard and analytics tracks weak topics.
          </p>
        </div>
        <ButtonGroup>
          <Button variant="secondary" onClick={() => setTopicFilter('')} disabled={!topicFilter}>
            Clear topic filter
          </Button>
          <Button onClick={() => setShowGenerate(true)}>Generate flashcards</Button>
        </ButtonGroup>
      </div>

      {loading && !cards.length ? (
        <LoadingBlock message="Loading flashcards…" />
      ) : cards.length ? (
        <div className="kg-stack">
          {cards.map((card) => {
            const isOpen = Boolean(revealed[card.id])
            return (
              <Card key={card.id}>
                <CardHeader
                  title={card.topic || 'Uncategorised'}
                  subtitle={card.source?.title || card.source?.document_title || undefined}
                  actions={
                    <div className="kg-row-wrap">
                      <Badge tone={TONES[card.review_status] || 'neutral'}>
                        {card.review_status}
                        {card.review_count ? ` · ${card.review_count}×` : ''}
                      </Badge>
                      <Badge tone="neutral">{card.difficulty}</Badge>
                      <Badge tone={card.generation_method === 'llm' ? 'success' : 'neutral'}>
                        {card.generation_method}
                      </Badge>
                    </div>
                  }
                />

                <p className="kg-text-sm" style={{ fontWeight: 600, margin: 0 }}>
                  {card.question}
                </p>

                {isOpen ? (
                  <p className="kg-prose kg-text-sm" style={{ marginTop: 'var(--kg-space-2)' }}>
                    {card.answer}
                  </p>
                ) : null}

                <div className="kg-card__footer">
                  <div className="kg-row-wrap">
                    {card.source?.page_number ? (
                      <Badge tone="neutral">
                        {card.source.title || 'document'} — page {card.source.page_number}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="kg-row-wrap">
                    <Button size="sm" variant="secondary" onClick={() => setRevealed({ ...revealed, [card.id]: !isOpen })}>
                      {isOpen ? 'Hide answer' : 'Reveal answer'}
                    </Button>
                    <Button size="sm" variant="success" onClick={() => review(card, 'easy')}>
                      Easy
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => review(card, 'medium')}>
                      Medium
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => review(card, 'hard')}>
                      Hard
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(card)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(card)}>
                      Delete
                    </Button>
                  </div>
                </div>
              </Card>
            )
          })}

          {pagesCount > 1 ? (
            <div className="kg-row-between">
              <span className="kg-text-sm kg-text-muted">
                Page {meta.page} of {pagesCount}
              </span>
              <ButtonGroup>
                <Button size="sm" variant="secondary" disabled={meta.page <= 1} onClick={() => load(meta.page - 1)}>
                  Previous
                </Button>
                <Button size="sm" variant="secondary" disabled={meta.page >= pagesCount} onClick={() => load(meta.page + 1)}>
                  Next
                </Button>
              </ButtonGroup>
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyState
          icon="🗂️"
          title="No flashcards yet"
          description="Generate them from any processed document — cards come from your own text."
          action={<Button onClick={() => setShowGenerate(true)}>Generate flashcards</Button>}
        />
      )}

      <Modal
        open={showGenerate}
        title="Generate flashcards"
        onClose={() => setShowGenerate(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowGenerate(false)}>
              Cancel
            </Button>
            <Button loading={generating} disabled={!selectedDocs.length} onClick={generate}>
              Generate {count} cards
            </Button>
          </>
        }
      >
        <div className="kg-stack">
          <div className="kg-stack-sm">
            <span className="kg-label">Documents</span>
            {documents.map((row) => (
              <label key={row.id} className="kg-checkbox">
                <input
                  type="checkbox"
                  checked={selectedDocs.includes(String(row.id))}
                  onChange={() =>
                    setSelectedDocs((current) => {
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
          <Input
            label="Topic (optional)"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="e.g. Normalization"
          />
          <Input
            label="How many cards"
            type="number"
            min="1"
            max="30"
            value={count}
            onChange={(event) => setCount(Number(event.target.value) || 8)}
          />
        </div>
      </Modal>

      <Modal
        open={Boolean(editing)}
        title="Edit flashcard"
        onClose={() => setEditing(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button onClick={saveEdit}>Save</Button>
          </>
        }
      >
        <div className="kg-stack">
          <Input
            label="Question"
            value={editForm.question}
            onChange={(event) => setEditForm({ ...editForm, question: event.target.value })}
          />
          <Textarea
            label="Answer"
            value={editForm.answer}
            onChange={(event) => setEditForm({ ...editForm, answer: event.target.value })}
          />
          <Input
            label="Topic"
            value={editForm.topic}
            onChange={(event) => setEditForm({ ...editForm, topic: event.target.value })}
          />
        </div>
      </Modal>
    </div>
  )
}
