/**
 * Polling hook used for live document-processing progress (brief §4).
 *
 * Keeps calling `fetcher` every `intervalMs` while `shouldContinue(result)` is
 * true (e.g. "any document not in a terminal state"). The timer is torn down the
 * moment the work is finished or the component unmounts.
 */

import { useEffect, useRef } from 'react'

export default function usePolling(
  fetcher,
  {
    intervalMs = 2500,
    shouldContinue = () => false,
    onTick = null,
    enabled = true,
    restartKey = 0,
  } = {},
) {
  const fetcherRef = useRef(fetcher)
  const continueRef = useRef(shouldContinue)
  const onTickRef = useRef(onTick)

  useEffect(() => {
    fetcherRef.current = fetcher
    continueRef.current = shouldContinue
    onTickRef.current = onTick
  }, [fetcher, shouldContinue, onTick])

  useEffect(() => {
    if (!enabled) return undefined

    let stopped = false
    let timeout = null

    async function tick() {
      if (stopped) return
      let result
      try {
        result = await fetcherRef.current()
      } catch {
        result = null
      }
      onTickRef.current?.(result)
      if (stopped) return
      if (result && continueRef.current(result)) {
        timeout = setTimeout(tick, intervalMs)
      }
    }

    tick()
    return () => {
      stopped = true
      clearTimeout(timeout)
    }
  }, [enabled, intervalMs, restartKey])
}