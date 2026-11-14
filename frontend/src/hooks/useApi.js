/**
 * Data hooks — one consistent pattern for every API call in the UI.
 *
 * `useAsync` wraps any promise-returning function into `{ execute, data, error,
 * loading }`. `useLoad` adds "run once on mount" (with a cancelled flag so an
 * unmounted component never updates state).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export function useAsync(asyncFn, { initialData = null } = {}) {
  const [data, setData] = useState(initialData)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const execute = useCallback(
    async (...args) => {
      setLoading(true)
      setError(null)
      try {
        const result = await asyncFn(...args)
        setData(result)
        return result
      } catch (error_) {
        setError(error_)
        throw error_
      } finally {
        setLoading(false)
      }
    },
    [asyncFn],
  )

  return { execute, data, setData, error, setError, loading }
}

/** Run a GET-style call on mount (and whenever `deps` change). */
export function useLoad(loader, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const cancelled = useRef(false)

  useEffect(() => {
    let cancelledNow = false
    cancelled.current = false
    setLoading(true)
    setError(null)
    Promise.resolve()
      .then(loader)
      .then((result) => {
        if (!cancelledNow) setData(result)
      })
      .catch((error_) => {
        if (!cancelledNow) setError(error_)
      })
      .finally(() => {
        if (!cancelledNow) setLoading(false)
      })
    return () => {
      cancelledNow = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await loader()
      if (!cancelled.current) setData(result)
      return result
    } catch (error_) {
      if (!cancelled.current) setError(error_)
      throw error_
    } finally {
      if (!cancelled.current) setLoading(false)
    }
  }, [loader])

  return { data, setData, error, loading, reload }
}

export default { useAsync, useLoad }