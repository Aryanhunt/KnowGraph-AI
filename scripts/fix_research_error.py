"""Research page: fail loudly when documents cannot be loaded.

Previously a failed load left the page on "Loading documents…" forever (or the
error only appeared as a toast). Now the failure is stored and rendered as an
Alert with a Retry button, so a dead backend can never look like an empty page.
"""

import pathlib

path = pathlib.Path(
    "/Users/aryanchaubey/Desktop/KnowGraph-AI/frontend/src/pages/Research.jsx"
)
text = path.read_text()

OLD = """  const load = useCallback(async () => {
    const { data } = await documentsApi.list({ page: 1, page_size: 100, status: 'completed' })
    const rows = data || []
    setDocuments(rows)
    if (rows.length) setSelectedId((current) => current || rows[0].id)
    return rows
  }, [])

  useEffect(() => {
    load().catch((error) => fromError(error, 'Could not load documents'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])"""

NEW = """  const load = useCallback(async () => {
    setLoading(true)
    setProblem(null)
    try {
      const { data } = await documentsApi.list({ page: 1, page_size: 100, status: 'completed' })
      const rows = data || []
      setDocuments(rows)
      if (rows.length) setSelectedId((current) => current || rows[0].id)
      return rows
    } catch (error) {
      setProblem({ message: error?.message, hint: error?.hint })
      fromError(error, 'Could not load documents')
      return []
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  if (problem) {
    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>Research mode</h1>
            <p className="kg-subtitle">Could not load your documents.</p>
          </div>
        </div>
        <Alert
          tone="danger"
          title={problem.message || 'Could not load documents'}
          hint={problem.hint || 'Check that the backend is running, then retry.'}
          actions={<Button onClick={load}>Retry</Button>}
        />
      </div>
    )
  }"""

if OLD not in text:
    raise SystemExit("research load block not found")
text = text.replace(OLD, NEW, 1)

# New state + Alert import.
OLD_STATE = "  const [documents, setDocuments] = useState(null)"
if OLD_STATE in text and "const [problem, setProblem]" not in text:
    text = text.replace(
        OLD_STATE,
        "  const [documents, setDocuments] = useState(null)\n"
        "  const [problem, setProblem] = useState(null)\n"
        "  const [loading, setLoading] = useState(false)",
        1,
    )
    print("  added problem/loading state")

if "import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'" in text:
    text = text.replace(
        "import { Alert, EmptyState, LoadingBlock } from '../components/Feedback'",
        "import { Alert, EmptyState } from '../components/Feedback'",
        1,
    )
    print("  switched Feedback import (Alert kept, spinner no longer needed)")

path.write_text(text)
print("research error handling patched")
