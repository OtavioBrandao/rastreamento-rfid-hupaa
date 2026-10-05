import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

export const LIVE_INTERVAL_MS = 2000
const LiveContext = createContext({ version: 0, pending: 0, refresh: () => {}, begin: () => () => {} })

export function LiveProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0)
  const [pending, setPending] = useState(0)
  const refreshing = useRef(false)
  const refresh = useCallback(() => {
    if (refreshing.current) return
    refreshing.current = true
    setVersion((value) => value + 1)
  }, [])
  useEffect(() => { if (pending === 0) refreshing.current = false }, [pending, version])
  const begin = useCallback(() => {
    setPending((value) => value + 1)
    let done = false
    return () => { if (!done) { done = true; setPending((value) => value - 1) } }
  }, [])
  return <LiveContext.Provider value={{ version, pending, refresh, begin }}>{children}</LiveContext.Provider>
}

export const useLiveRefresh = () => useContext(LiveContext)

// Cada recurso mantém sua última resposta durante atualização/falha transitória.
// Uma mudança de chave (filtro, página ou equipamento) oculta a resposta anterior.
export function useLiveQuery<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>) {
  const { version, begin } = useLiveRefresh()
  const loader = useRef(load)
  loader.current = load
  const [state, setState] = useState<{ key: string | null; data: T | null; error: Error | null }>({ key, data: null, error: null })
  useEffect(() => {
    if (key === null) return
    let stopped = false
    let busy = false
    let controller: AbortController | undefined
    let finish: (() => void) | undefined
    async function update() {
      if (busy) return
      busy = true
      controller = new AbortController()
      finish = begin()
      try {
        const data = await loader.current(controller.signal)
        if (!stopped) setState({ key, data, error: null })
      } catch (error) {
        if (!stopped) setState((old) => ({ key, data: old.key === key ? old.data : null, error: error instanceof Error ? error : new Error(String(error)) }))
      } finally { finish?.(); busy = false }
    }
    void update()
    const interval = window.setInterval(() => { void update() }, LIVE_INTERVAL_MS)
    return () => { stopped = true; controller?.abort(); finish?.(); window.clearInterval(interval) }
  }, [key, version, begin])
  const current = state.key === key ? state : { data: null, error: null }
  return { ...current, loading: key !== null && !current.data && !current.error }
}
