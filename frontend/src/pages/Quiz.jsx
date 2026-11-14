/**
 * Quiz page — generate, take and grade quizzes (brief §10).
 *
 * Grading happens in the backend with explicit rules (never the LLM): MCQ and
 * true/false are exact matches, short answers are word-order tolerant. The result
 * view shows the correct answer, the explanation and the source page for every
 * question.
 */

import { useCallback, useEffect, useState } from 'react'
import { documentsApi, studyApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import ProgressBar from '../components/ProgressBar'
import { Input } from '../components/Input'
import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'
import './Quiz.css'

const TYPE_LABELS = { mcq: 'Multiple choice', true_false: 'True / False', short_answer: 'Short answer' }

export default function QuizPage() {
  const { fromError, success } = useToast()
  const [documents, setDocuments] = useState([])
  const [quizzes, setQuizzes] = useState([])
  const [meta, setMeta] = useState({ total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState(null)          // quiz being taken / reviewed
  const [attempt, setAttempt] = useState(null)        // last graded attempt
  const [attempts, setAttempts] = useState([])
  const [answers, setAnswers] = useState({})

  const [showGenerate, setShowGenerate] = useState(false)
  const [selectedDocs, setSelectedDocs] = useState([])
  const [topic, setTopic] = useState('')
  const [counts, setCounts] = useState({ mcq: 3, true_false: 2, short_answer: 1 })
  const [generating, setGenerating] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async (page = 1) => {
    setLoading(true)
    try {
      const { data, meta: responseMeta } = await studyApi.quizzes({ page, page_size: 20 })
      setQuizzes(data || [])
      setMeta(responseMeta || { total: (data || []).length, page, page_size: 20 })
    } catch (error) {
      fromError(error, 'Could not load quizzes')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load(1)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      const { data } = await studyApi.generateQuiz({
        document_ids: selectedDocs,
        topic,
        counts: Object.fromEntries(Object.entries(counts).filter(([, value]) => value > 0)),
      })
      success(`Quiz created with ${data.question_count ?? 0} question(s) (${data.generation_method}).`)
      setShowGenerate(false)
      setSelectedDocs([])
      load(1)
      openQuiz(data.id ?? data.quiz_id)
    } catch (error) {
      fromError(error, 'Generation failed')
    } finally {
      setGenerating(false)
    }
  }

  async function openQuiz(id) {
    setAttempt(null)
    setAnswers({})
    setAttempts([])
    try {
      const { data } = await studyApi.quiz(id, false)
      setActive(data)
      const { data: history } = await studyApi.quizAttempts(id).catch(() => ({ data: [] }))
      setAttempts(history || [])
    } catch (error) {
      fromError(error, 'Could not open the quiz')
    }
  }

  async function submit() {
    if (!active) return
    setSubmitting(true)
    try {
      const { data } = await studyApi.submitQuiz(active.id, answers)
      setAttempt(data)
      const { data: history } = await studyApi.quizAttempts(active.id).catch(() => ({ data: [] }))
      setAttempts(history || [])
      const { data: fresh } = await studyApi.quiz(active.id, true)
      setActive(fresh)
      success(`Scored ${data.score}% (${data.correct}/${data.total}).`)
    } catch (error) {
      fromError(error, 'Could not submit the quiz')
    } finally {
      setSubmitting(false)
    }
  }

  async function removeQuiz(quiz) {
    try {
      await studyApi.deleteQuiz(quiz.id)
      setQuizzes((current) => current.filter((row) => row.id !== quiz.id))
      if (active?.id === quiz.id) setActive(null)
      success('Quiz deleted.')
    } catch (error) {
      fromError(error, 'Could not delete the quiz')
    }
  }

  if (active) {
    const questions = active.questions || []
    const graded = attempt?.results || []
    const answeredCount = Object.keys(answers).length

    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>{active.title}</h1>
            <p className="kg-subtitle">
              {questions.length} question(s){active.topic ? ` · ${active.topic}` : ''} ·{' '}
              {active.generation_method === 'llm' ? 'local model' : 'deterministic'}
            </p>
          </div>
          <Button variant="secondary" onClick={() => setActive(null)}>
            Back to quizzes
          </Button>
        </div>

        {attempt ? (
          <Card flat>
            <div className="kg-grid">
              <div>
                <div className="kg-text-xs kg-text-muted">Score</div>
                <div style={{ fontSize: 'var(--kg-font-size-2xl)', fontWeight: 600 }}>
                  {attempt.score}%{' '}
                  <span className="kg-text-sm kg-text-muted">
                    ({attempt.correct}/{attempt.total})
                  </span>
                </div>
              </div>
              <ProgressBar
                value={attempt.score}
                tone={attempt.score >= 80 ? 'success' : attempt.score >= 50 ? 'warning' : 'danger'}
                label={false}
              />
            </div>
            {attempt.topic_scores ? (
              <div className="kg-row-wrap" style={{ marginTop: 'var(--kg-space-3)' }}>
                {Object.entries(attempt.topic_scores).map(([topicName, stats]) => (
                  <Badge key={topicName} tone={stats.correct === stats.attempts ? 'success' : 'warning'}>
                    {topicName}: {stats.correct}/{stats.attempts}
                  </Badge>
                ))}
              </div>
            ) : null}
          </Card>
        ) : null}

        <div className="kg-stack">
          {questions.map((question, index) => {
            const gradedRow = graded.find((row) => row.question_id === question.question_id)
            const isCorrect = gradedRow?.correct
            return (
              <Card key={question.question_id} flat={gradedRow === undefined}>
                <div className="kg-stack-sm">
                  <div className="kg-row-wrap">
                    <Badge tone="primary">Q{index + 1}</Badge>
                    <Badge tone="neutral">{TYPE_LABELS[question.type] || question.type}</Badge>
                    {question.topic ? <Badge tone="neutral">{question.topic}</Badge> : null}
                    <Badge tone="neutral">{question.difficulty}</Badge>
                    {gradedRow !== undefined ? (
                      <Badge tone={isCorrect ? 'success' : 'danger'}>
                        {isCorrect ? 'correct' : 'incorrect'}
                      </Badge>
                    ) : null}
                  </div>

                  <p className="kg-text-sm" style={{ fontWeight: 600, margin: 0 }}>
                    {question.question}
                  </p>

                  {question.type === 'short_answer' ? (
                    <Input
                      value={answers[question.question_id] || ''}
                      onChange={(event) =>
                        setAnswers({ ...answers, [question.question_id]: event.target.value })
                      }
                      placeholder="Your answer"
                      disabled={Boolean(attempt)}
                    />
                  ) : (
                    <div className="kg-stack-sm">
                      {(question.options || []).map((option) => {
                        const chosen = answers[question.question_id] === option
                        const showRight = attempt && option === question.correct_answer
                        const showWrong = attempt && chosen && !showRight
                        return (
                          <label key={option} className="kg-checkbox">
                            <input
                              type="radio"
                              name={question.question_id}
                              checked={chosen}
                              disabled={Boolean(attempt)}
                              onChange={() => setAnswers({ ...answers, [question.question_id]: option })}
                            />
                            <span
                              className={`kg-text-sm${showRight ? ' kg-answer-right' : showWrong ? ' kg-answer-wrong' : ''}`}
                            >
                              {option}
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}

                  {gradedRow ? (
                    <div className="kg-stack-sm">
                      {gradedRow.explanation ? (
                        <Alert tone={isCorrect ? 'success' : 'info'} title="Why" hint={gradedRow.explanation} />
                      ) : null}
                      {gradedRow.source?.page_number ? (
                        <Badge tone="neutral">
                          {gradedRow.source.title || 'source'} — page {gradedRow.source.page_number}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </Card>
            )
          })}
        </div>

        {!attempt ? (
          <div className="kg-row-between">
            <span className="kg-text-sm kg-text-muted">
              {answeredCount}/{questions.length} answered
            </span>
            <Button loading={submitting} disabled={submitting || !answeredCount} onClick={submit}>
              Submit quiz
            </Button>
          </div>
        ) : null}

        {attempts.length ? (
          <Card flat>
            <CardHeader title="Previous attempts" />
            <div className="kg-stack-sm">
              {attempts.slice(0, 8).map((row) => (
                <div key={row.id ?? row._id} className="kg-row-between">
                  <span className="kg-text-sm">
                    {row.score}% ({row.correct}/{row.total})
                  </span>
                  <span className="kg-text-xs kg-text-muted">
                    {row.submitted_at ? new Date(row.submitted_at).toLocaleString() : ''}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        ) : null}
      </div>
    )
  }

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Quiz</h1>
          <p className="kg-subtitle">
            {meta.total} quiz(zes) — grading is plain application logic, never the model.
          </p>
        </div>
        <Button onClick={() => setShowGenerate(true)}>Generate quiz</Button>
      </div>

      {loading && !quizzes.length ? (
        <LoadingBlock message="Loading quizzes…" />
      ) : quizzes.length ? (
        <div className="kg-stack">
          {quizzes.map((quiz) => (
            <Card key={quiz.id}>
              <CardHeader
                title={quiz.title}
                subtitle={`${(quiz.questions || []).length} question(s) · ${quiz.generation_method}`}
                actions={
                  <div className="kg-row-wrap">
                    <Button size="sm" onClick={() => openQuiz(quiz.id)}>
                      Take quiz
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => removeQuiz(quiz)}>
                      Delete
                    </Button>
                  </div>
                }
              />
              <div className="kg-row-wrap">
                {quiz.topic ? <Badge tone="primary">{quiz.topic}</Badge> : null}
                {(quiz.documents || []).slice(0, 3).map((id) => (
                  <Badge key={id} tone="neutral">
                    document
                  </Badge>
                ))}
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          icon="📝"
          title="No quizzes yet"
          description="Generate MCQs, true/false and short-answer questions from your own documents."
          action={<Button onClick={() => setShowGenerate(true)}>Generate quiz</Button>}
        />
      )}

      <Modal
        open={showGenerate}
        title="Generate quiz"
        onClose={() => setShowGenerate(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowGenerate(false)}>
              Cancel
            </Button>
            <Button loading={generating} disabled={!selectedDocs.length} onClick={generate}>
              Generate
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
          <Input label="Topic (optional)" value={topic} onChange={(event) => setTopic(event.target.value)} />
          <div className="kg-grid">
            <Input
              label="MCQs"
              type="number"
              min="0"
              max="10"
              value={counts.mcq}
              onChange={(event) => setCounts({ ...counts, mcq: Number(event.target.value) || 0 })}
            />
            <Input
              label="True / False"
              type="number"
              min="0"
              max="10"
              value={counts.true_false}
              onChange={(event) => setCounts({ ...counts, true_false: Number(event.target.value) || 0 })}
            />
            <Input
              label="Short answer"
              type="number"
              min="0"
              max="10"
              value={counts.short_answer}
              onChange={(event) => setCounts({ ...counts, short_answer: Number(event.target.value) || 0 })}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
