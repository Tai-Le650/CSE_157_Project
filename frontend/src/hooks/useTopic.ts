import { useEffect, useRef, useState } from 'react'
import { wsClient } from '@/services/ws'
import type { WsEnvelope } from '@/types/api'

export function useTopic<T = unknown>(topic: string | null | undefined, handler: (message: WsEnvelope<T>) => void) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    if (!topic) return
    return wsClient.subscribe(topic, (message) => ref.current(message as WsEnvelope<T>))
  }, [topic])
}

export function useTopicState<T>(topic: string | null | undefined, initial: T, type?: string, throttleMs = 0): T {
  const [value, setValue] = useState<T>(initial)
  const last = useRef(0)
  const pending = useRef<T | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])
  useTopic<T>(topic, (message) => {
    if (type && message.type !== type) return
    if (!throttleMs) {
      setValue(message.data)
      return
    }
    const now = performance.now()
    if (now - last.current >= throttleMs) {
      last.current = now
      setValue(message.data)
      return
    }
    pending.current = message.data
    if (!timer.current) {
      timer.current = setTimeout(() => {
        timer.current = null
        last.current = performance.now()
        if (pending.current !== null) setValue(pending.current)
      }, throttleMs)
    }
  })
  return value
}
