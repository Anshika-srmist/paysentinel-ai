import { useCallback, useEffect, useState } from 'react'

const KEY = 'paysentinel-theme'

function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Light / dark theme with a persisted override. The initial value is set
 * synchronously by an inline script in index.html (no flash); this hook
 * keeps it in sync and lets the toggle flip it.
 */
export function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.getAttribute('data-theme') || systemTheme(),
  )

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // follow the OS setting until the user makes an explicit choice
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = (e) => {
      try {
        if (!localStorage.getItem(KEY)) setTheme(e.matches ? 'dark' : 'light')
      } catch { /* ignore */ }
    }
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark'
      try { localStorage.setItem(KEY, next) } catch { /* ignore */ }
      return next
    })
  }, [])

  return { theme, toggle }
}
