/**
 * Search page — global keyword/semantic/hybrid search (brief §15).
 *
 * Three entry points: typed queries, the `?q=` navbar shortcut, and saved search
 * history. Scores are shown exactly as returned, with a band from documented
 * thresholds.
 */

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { documentsApi, searchApi } from '../services'
import { useToast } from '../context/ToastContext'
import Card, { CardHeader } from '../components/Card'
import Button, { ButtonGroup } from '../components/Button'
import Select from '../components/Select'
import { Input } from '../components/Input'
import Badge from '../components/Badge'
import SourceCitation from '../components/SourceCitation'
import { EmptyState, LoadingBlock } from '../components/Feedback'

const MODES = [
  { value: 'hybrid', label: 'Hybrid (semantic + keyword)' },
  { value: 'semantic', label: 'Semantic' },
  { value: 'keyword', label: 'Keyword' },
]

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { fromError } = useToast()

  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [mode, setMode] = useState('hybrid')
  const [subject, setSubject] = useState('')
  const [subjects, setSubjects] = useState([])
  const [history, setHistory] = useState([])
  const [results, setResults] = useState(null)
  const [meta, setMeta] = useState(null)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    documentsApi.subjects().then(({ data }) => setSubjects(data || [])).catch(() => {})
    searchApi.history().then(({ data }) => setHistory(data || [])).catch(() => {})
  }, [])

  const run = useCallback(
    async (nextQuery) => {
      const text = (nextQuery ?? query).trim()
      if (!text) return
      setLoading(true)
      setSearched(true)
      try {
        const { data, meta: responseMeta } = await searchApi.run({
          query: text,
          mode,
          subject: subject || undefined,
          top_k: 10,
        })
        setResults(data || [])
        setMeta(responseMeta)
        setQuery(text)
        setSearchParams(text ? { q: text } : {})
        searchApi.history().then(({ data: rows }) => setHistory(rows || [])).catch(() => {})
      } catch (error) {
        fromError(error, 'Search failed')
        setResults([])
        setMeta(null)
      } finally {
        setLoading(false)
      }
    },
    [query, mode, subject, setSearchParams, fromError],
  )

  // The navbar's global search lands here with ?q=.
  useEffect(() => {
    const seed = searchParams.get('q')
    if (seed && !results && !loading) run(seed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="kg-page">
      <div className="kg-page-header">
        <div className="kg-page-title">
          <h1>Search</h1>
          <p className="kg-subtitle">Keyword, semantic or hybrid — your call.</p>
        </div>
      </div>

      <Card>
        <form
          className="kg-stack"
          onSubmit={(event) => {
            event.preventDefault()
            run()
          }}
        >
          <Input
            label="Search your knowledge"
            name="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. How does TCP control congestion?"
          />
          <div className="kg-grid kg-grid-2">
            <Select label="Mode" value={mode} options={MODES} onChange={(event) => setMode(event.target.value)} />
            <Select
              label="Subject"
              value={subject}
              options={[
                { value: '', label: 'All subjects' },
                ...subjects.map((row) => ({
                  value: row.subject,
                  label: `${row.subject} (${row.document_count})`,
                })),
              ]}
              onChange={(event) => setSubject(event.target.value)}
            />
          </div>
          <ButtonGroup>
            <Button type="submit" loading={loading} disabled={loading || !query.trim()}>
              Search
            </Button>
          </ButtonGroup>
          {meta?.score_meaning ? (
            <p className="kg-text-xs kg-text-muted" style={{ margin: 0 }}>
              {meta.score_meaning}.
              {meta.bands ? ` Bands: High ≥ ${meta.bands.high}, Medium ≥ ${meta.bands.medium}.` : ''}
            </p>
          ) : null}
        </form>
      </Card>

      {loading ? <LoadingBlock message="Searching…" /> : null}

      {!loading && searched && results && !results.length ? (
        <EmptyState
          icon="🔍"
          title="No matches"
          description="Try fewer words, a different mode, or upload material on this topic."
        />
      ) : null}

      {!loading && results?.length ? (
        <Card>
          <CardHeader title={`${results.length} result(s)`} subtitle={meta?.query ? `for “${meta.query}”` : undefined} />
          <div className="kg-stack">
            {results.map((result, position) => (
              <SourceCitation
                key={result.chunk_id || position}
                source={result}
                index={position + 1}
                relevance={result.relevance}
                showScore
              />
            ))}
          </div>
        </Card>
      ) : null}

      {history.length ? (
        <Card flat>
          <CardHeader title="Recent searches" />
          <div className="kg-row-wrap">
            {history.slice(0, 12).map((row, index) => (
              <button
                key={`${row.query}-${index}`}
                type="button"
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                onClick={() => run(row.query)}
              >
                <Badge tone="neutral">
                  {row.query} · {row.result_count}
                </Badge>
              </button>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
