import type { WsEnvelope } from '@/types/api'
import { getToken, resetToken } from './api'

export type ConnectionState = 'connecting' | 'open' | 'closed'
type Listener = (message: WsEnvelope) => void

const HEARTBEAT_MS = 1000
const MAX_BACKOFF_MS = 10000

export class WsClient {
  private socket: WebSocket | null = null
  private listeners = new Map<string, Set<Listener>>()
  private topicRefs = new Map<string, number>()
  private stateListeners = new Set<(state: ConnectionState) => void>()
  private heartbeat: ReturnType<typeof setInterval> | null = null
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private attempts = 0
  private stopped = false
  clientId: string | null = null
  state: ConnectionState = 'closed'

  start() {
    this.stopped = false
    if (!this.socket) void this.connect()
  }

  stop() {
    this.stopped = true
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.socket?.close()
    this.socket = null
  }

  private setState(state: ConnectionState) {
    this.state = state
    for (const listener of this.stateListeners) listener(state)
  }

  onState(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => this.stateListeners.delete(listener)
  }

  private async connect() {
    this.setState('connecting')
    let token: string
    try {
      token = await getToken()
    } catch {
      this.scheduleReconnect()
      return
    }
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws?token=${encodeURIComponent(token)}`)
    this.socket = socket
    socket.onopen = () => {
      this.attempts = 0
      this.setState('open')
      const topics = [...this.topicRefs.keys()]
      if (topics.length) this.send({ type: 'subscribe', topics })
      if (this.heartbeat) clearInterval(this.heartbeat)
      this.heartbeat = setInterval(() => this.send({ type: 'heartbeat' }), HEARTBEAT_MS)
      this.send({ type: 'heartbeat' })
    }
    socket.onmessage = (event) => {
      let message: WsEnvelope
      try {
        message = JSON.parse(event.data as string) as WsEnvelope
      } catch {
        return
      }
      if (message.type === 'hello') {
        this.clientId = (message.data as { client_id: string }).client_id
      }
      this.dispatch(message)
    }
    socket.onclose = (event) => {
      if (this.heartbeat) clearInterval(this.heartbeat)
      this.heartbeat = null
      this.clientId = null
      this.socket = null
      this.setState('closed')
      if (event.code === 1008) resetToken()
      if (!this.stopped) this.scheduleReconnect()
    }
    socket.onerror = () => {
      socket.close()
    }
  }

  private scheduleReconnect() {
    if (this.stopped) return
    this.attempts += 1
    const delay = Math.min(MAX_BACKOFF_MS, 400 * 2 ** Math.min(this.attempts, 5))
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.retryTimer = setTimeout(() => void this.connect(), delay)
  }

  private dispatch(message: WsEnvelope) {
    const exact = this.listeners.get(message.topic)
    if (exact) for (const listener of exact) listener(message)
    const prefix = message.topic.split(':')[0]
    if (prefix !== message.topic) {
      const wildcard = this.listeners.get(`${prefix}:*`)
      if (wildcard) for (const listener of wildcard) listener(message)
    }
    const all = this.listeners.get('*')
    if (all) for (const listener of all) listener(message)
  }

  send(payload: Record<string, unknown>) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  subscribe(topic: string, listener: Listener): () => void {
    let set = this.listeners.get(topic)
    if (!set) {
      set = new Set()
      this.listeners.set(topic, set)
    }
    set.add(listener)
    if (topic !== '*') {
      const refs = (this.topicRefs.get(topic) ?? 0) + 1
      this.topicRefs.set(topic, refs)
      if (refs === 1) this.send({ type: 'subscribe', topics: [topic] })
    }
    return () => {
      set?.delete(listener)
      if (topic === '*') return
      const remaining = (this.topicRefs.get(topic) ?? 1) - 1
      if (remaining <= 0) {
        this.topicRefs.delete(topic)
        this.send({ type: 'unsubscribe', topics: [topic] })
      } else {
        this.topicRefs.set(topic, remaining)
      }
    }
  }

  emergencyStop(): boolean {
    return this.send({ type: 'estop' })
  }
}

export const wsClient = new WsClient()
