import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/services/api'

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], intervalMs?: number) {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const alive = useRef(true)

  const reload = useCallback(async () => {
    try {
      const result = await fnRef.current()
      if (alive.current) {
        setData(result)
        setError(null)
      }
      return result
    } catch (err) {
      if (alive.current) setError(err)
      return undefined
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    setLoading(true)
    void reload()
    let timer: ReturnType<typeof setInterval> | undefined
    if (intervalMs) timer = setInterval(() => void reload(), intervalMs)
    return () => {
      alive.current = false
      if (timer) clearInterval(timer)
    }
  }, deps)

  return { data, error, loading, reload, setData }
}

export function useAction() {
  const [pending, setPending] = useState<string | null>(null)
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, success?: string | ((result: T) => string)): Promise<T | undefined> => {
    setPending(key)
    try {
      const result = await fn()
      if (success) toast.success(typeof success === 'function' ? success(result) : success)
      return result
    } catch (err) {
      toast.error(errorMessage(err))
      return undefined
    } finally {
      setPending(null)
    }
  }, [])
  return { run, pending }
}
