import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Poll an async function on an interval.
 *
 *   const { data, error, loading, stale, lastUpdated, refresh } =
 *     usePolling((signal) => api.stats({ signal }), 5000)
 *
 * - keeps the previous `data` visible while re-fetching (no flicker)
 * - pauses while the tab is hidden, refetches immediately on return
 * - extra `deps` re-run the fetch right away when they change
 */
export function usePolling(fn, intervalMs, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  const savedFn = useRef(fn)
  savedFn.current = fn
  const mounted = useRef(true)
  const inflight = useRef(null)

  const run = useCallback(async () => {
    inflight.current?.abort()
    const controller = new AbortController()
    inflight.current = controller
    try {
      const result = await savedFn.current(controller.signal)
      if (!mounted.current) return
      setData(result)
      setError(null)
      setLastUpdated(Date.now())
      setLoading(false)
    } catch (err) {
      // An aborted request (deps changed, unmount, or a newer poll started)
      // must leave loading/data untouched so the consumer keeps showing the
      // last good state instead of a null.
      if (mounted.current && err.name !== 'AbortError') {
        setError(err)
        setLoading(false)
      }
    }
  }, [])

  const refresh = useCallback(() => {
    setLoading(true)
    run()
  }, [run])

  useEffect(() => {
    mounted.current = true
    setLoading(true)
    run()
    let timer = setInterval(run, intervalMs)

    const onVisibility = () => {
      clearInterval(timer)
      if (!document.hidden) {
        run()
        timer = setInterval(run, intervalMs)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      mounted.current = false
      clearInterval(timer)
      inflight.current?.abort()
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, run, ...deps])

  const stale = Boolean(error) && Boolean(data)
  return { data, error, loading, stale, lastUpdated, refresh }
}
