import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetToken } from './api'
import { WsClient } from './ws'

vi.mock('./api', () => ({
  getToken: vi.fn(async () => 'tok'),
  resetToken: vi.fn(),
}))

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 0
  sent: Record<string, unknown>[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>)
  }

  close(code = 1000) {
    this.readyState = 3
    this.onclose?.({ code })
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  receive(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

function subscribeMessages(socket: FakeSocket, type: 'subscribe' | 'unsubscribe', topic: string) {
  return socket.sent.filter((m) => m.type === type && (m.topics as string[]).includes(topic))
}

let client: WsClient

async function openClient(): Promise<FakeSocket> {
  client.start()
  await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(1))
  const socket = FakeSocket.instances[0]
  socket.open()
  return socket
}

beforeEach(() => {
  FakeSocket.instances = []
  vi.stubGlobal('WebSocket', FakeSocket)
  client = new WsClient()
})

afterEach(() => {
  client.stop()
})

describe('WsClient', () => {
  it('connects with the session token', async () => {
    const socket = await openClient()
    expect(socket.url).toMatch(/\/ws\?token=tok$/)
    expect(client.state).toBe('open')
  })

  it('subscribes once per topic and unsubscribes after the last listener leaves', async () => {
    const socket = await openClient()
    const offA = client.subscribe('samples:S1', () => undefined)
    const offB = client.subscribe('samples:S1', () => undefined)
    expect(subscribeMessages(socket, 'subscribe', 'samples:S1')).toHaveLength(1)
    offA()
    expect(subscribeMessages(socket, 'unsubscribe', 'samples:S1')).toHaveLength(0)
    offB()
    expect(subscribeMessages(socket, 'unsubscribe', 'samples:S1')).toHaveLength(1)
  })

  it('subscribes to topics registered before the socket opened', async () => {
    client.subscribe('predictions', () => undefined)
    const socket = await openClient()
    expect(socket.sent).toContainEqual({ type: 'subscribe', topics: ['predictions'] })
  })

  it('routes messages to exact, wildcard and catch-all listeners', async () => {
    const socket = await openClient()
    const exact = vi.fn()
    const wildcard = vi.fn()
    const all = vi.fn()
    const other = vi.fn()
    client.subscribe('samples:S1', exact)
    client.subscribe('samples:*', wildcard)
    client.subscribe('*', all)
    client.subscribe('samples:S2', other)
    socket.receive({ v: 1, type: 'samples', topic: 'samples:S1', seq: 1, ts: 0, data: {} })
    expect(exact).toHaveBeenCalledTimes(1)
    expect(wildcard).toHaveBeenCalledTimes(1)
    expect(all).toHaveBeenCalledTimes(1)
    expect(other).not.toHaveBeenCalled()
  })

  it('reconnects with backoff and restores subscriptions', async () => {
    vi.useFakeTimers()
    const first = await openClient()
    client.subscribe('detections', () => undefined)
    first.close(1006)
    expect(client.state).toBe('closed')
    await vi.advanceTimersByTimeAsync(799)
    expect(FakeSocket.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeSocket.instances).toHaveLength(2)
    const second = FakeSocket.instances[1]
    second.open()
    expect(second.sent).toContainEqual({ type: 'subscribe', topics: ['detections'] })
  })

  it('drops the cached token when the server rejects the socket', async () => {
    const socket = await openClient()
    socket.close(1008)
    expect(resetToken).toHaveBeenCalled()
  })

  it('sends the emergency stop only over an open socket', async () => {
    expect(client.emergencyStop()).toBe(false)
    const socket = await openClient()
    expect(client.emergencyStop()).toBe(true)
    expect(socket.sent).toContainEqual({ type: 'estop' })
  })
})
