"""Analytics page: fail loudly instead of rendering an empty (black) page.

When the API is unreachable the page previously fell through to a bare tab shell,
which is indistinguishable from "no data" — exactly the "blacked out" symptom.
Now:
* the load failure is stored in state and rendered as an Alert with a Retry button,
* a loading state is shown while retrying,
* the reason (network error / 403 AirPlay / expired session) comes from the API
  layer's `hint`, so the user is told what to do.
"""

import pathlib

path = pathlib.Path("/Users/aryanchaubey/Desktop/KnowGraph-AI/frontend/src/pages/Analytics.jsx")
text = path.read_text()

OLD_STATE = """  const [topics, setTopics] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([analyticsApi.progress(), analyticsApi.knowledgeGaps(), analyticsApi.topics()])
      .then(([progressResponse, gapsResponse, topicsResponse]) => {
        setProgress(progressResponse.data)
        setGaps(gapsResponse.data)
        setTopics(topicsResponse.data)
      })
      .catch((error) => fromError(error, 'Could not load analytics'))
      .finally(() => setLoading(false))
  }, [fromError])
"""

NEW_STATE = """  const [topics, setTopics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [problem, setProblem] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setProblem(null)
    try {
      const [progressResponse, gapsResponse, topicsResponse] = await Promise.all([
        analyticsApi.progress(),
        analyticsApi.knowledgeGaps(),
        analyticsApi.topics(),
      ])
      setProgress(progressResponse.data)
      setGaps(gapsResponse.data)
      setTopics(topicsResponse.data)
    } catch (error) {
      // Keep the reason on screen: an empty dashboard must never look like
      // "no data" when the truth is "the API could not be reached".
      setProblem({ message: error?.message, hint: error?.hint })
      fromError(error, 'Could not load analytics')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    load()
  }, [load])

  if (problem) {
    return (
      <div className="kg-page">
        <div className="kg-page-header">
          <div className="kg-page-title">
            <h1>Analytics</h1>
            <p className="kg-subtitle">Could not load your progress data.</p>
          </div>
        </div>
        <Alert
          tone="danger"
          title={problem.message || 'Could not load analytics'}
          hint={problem.hint || 'Check that the backend is running, then retry.'}
          actions={<Button onClick={load}>Retry</Button>}
        />
      </div>
    )
  }
"""

if OLD_STATE not in text:
    raise SystemExit("analytics state block not found")
text = text.replace(OLD_STATE, NEW_STATE, 1)

# useCallback must be imported.
OLD_IMPORT = "import { useEffect, useState } from 'react'"
if OLD_IMPORT in text:
    text = text.replace(OLD_IMPORT, "import { useCallback, useEffect, useState } from 'react'", 1)
    print("  added useCallback import")

# Button is needed for the retry action.
OLD_BTN_IMPORT = "import ProgressBar from '../components/ProgressBar'"
if "import Button from '../components/Button'" not in text:
    text = text.replace(
        OLD_BTN_IMPORT,
        "import Button from '../components/Button'\n" + OLD_BTN_IMPORT,
        1,
    )
    print("  added Button import")

path.write_text(text)
print("analytics error handling patched")
