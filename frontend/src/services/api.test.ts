import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorMessage, request, resetToken } from './api'

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function headersOf(init: RequestInit | undefined): Record<string, string> {
  return (init?.headers ?? {}) as Record<string, string>
}

beforeEach(() => {
  resetToken()
  window.localStorage.clear()
})

describe('request', () => {
  it('sends the session token on every call', async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => (url === '/api/session' ? json(200, { token: 'tok-1' }) : json(200, { ok: true })))
    vi.stubGlobal('fetch', fetchMock)
    await request('GET', '/api/status')
    await request('POST', '/api/control/disarm', { reason: 'user' })
    const getCall = fetchMock.mock.calls.find(([url]) => url === '/api/status')
    expect(headersOf(getCall?.[1])['X-Session-Token']).toBe('tok-1')
    const postCall = fetchMock.mock.calls.find(([url]) => url === '/api/control/disarm')
    expect(headersOf(postCall?.[1])).toMatchObject({ 'X-Session-Token': 'tok-1', 'Content-Type': 'application/json' })
    expect(postCall?.[1]?.body).toBe(JSON.stringify({ reason: 'user' }))
  })

  it('refreshes a stale token once and retries', async () => {
    let issued = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/session') {
          issued += 1
          return json(200, { token: `tok-${issued}` })
        }
        if (headersOf(init)['X-Session-Token'] === 'tok-1') return json(401, { error: { code: 'invalid_session_token', message: 'Missing or invalid X-Session-Token header' } })
        return json(200, { armed: false })
      }),
    )
    await expect(request('POST', '/api/control/reset')).resolves.toEqual({ armed: false })
    expect(issued).toBe(2)
  })

  it('gives up after one retry', async () => {
    const fetchMock = vi.fn(async (url: string) => (url === '/api/session' ? json(200, { token: 'tok' }) : json(401, { error: { code: 'invalid_session_token', message: 'Missing or invalid X-Session-Token header' } })))
    vi.stubGlobal('fetch', fetchMock)
    await expect(request('POST', '/api/control/reset')).rejects.toMatchObject({ code: 'invalid_session_token', status: 401 })
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/control/reset')).toHaveLength(2)
  })

  it('turns structured errors into ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/api/session' ? json(200, { token: 'tok' }) : json(409, { error: { code: 'not_ready', message: 'Cannot arm PC control', details: { reasons: ['No streaming sensor.'] } } }))))
    const error = await request('GET', '/api/control').catch((err: unknown) => err)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'not_ready', status: 409, message: 'Cannot arm PC control' })
    expect((error as ApiError).reasons).toEqual(['No streaming sensor.'])
  })

  it('reports an unreachable backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/session') return json(200, { token: 'tok' })
        throw new TypeError('Failed to fetch')
      }),
    )
    await expect(request('POST', '/api/control/arm', {})).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })

  it('reports an unreachable backend when even the session cannot be fetched', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await expect(request('GET', '/api/status')).rejects.toMatchObject({ code: 'network_error', status: 0, message: expect.stringContaining('backend\\run.py') })
  })
})

describe('online demo sessions', () => {
  async function freshApi() {
    vi.resetModules()
    return import('./api')
  }

  it('resumes the stored sandbox token instead of creating a new sandbox', async () => {
    window.localStorage.setItem('gesture-to-pc.session-token', 'sandbox-1')
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => (url === '/api/session' ? json(200, { token: 'sandbox-1', hosted: true, limits: null }) : json(200, {})))
    vi.stubGlobal('fetch', fetchMock)
    const api = await freshApi()
    await api.request('GET', '/api/status')
    const sessionCall = fetchMock.mock.calls.find(([url]) => url === '/api/session')
    expect(headersOf(sessionCall?.[1])['X-Session-Token']).toBe('sandbox-1')
    expect(api.currentSessionInfo()).toMatchObject({ token: 'sandbox-1', hosted: true })
  })

  it('surfaces the server message when the demo is full', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(503, { error: { code: 'demo_full', message: 'The online demo is full right now.' } })))
    const api = await freshApi()
    const error = await api.request('GET', '/api/status').catch((err: unknown) => err)
    expect(error).toMatchObject({ code: 'demo_full', status: 503, message: 'The online demo is full right now.' })
    expect(api.errorMessage(error)).toBe('The online demo is full right now.')
    expect(api.currentSessionError()).toMatchObject({ code: 'demo_full' })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/api/session' ? json(200, { token: 'sandbox-9', hosted: true, limits: null }) : json(200, {}))))
    await api.request('GET', '/api/status')
    expect(api.currentSessionError()).toBeNull()
  })

  it('announces when an expired sandbox is replaced by a new one', async () => {
    let issued = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/session') {
          issued += 1
          return json(200, { token: `sandbox-${issued}`, hosted: true, limits: null })
        }
        if (headersOf(init)['X-Session-Token'] === 'sandbox-1') return json(401, { error: { code: 'invalid_session_token', message: 'This demo sandbox has expired' } })
        return json(200, { ok: true })
      }),
    )
    const api = await freshApi()
    const replaced = vi.fn()
    api.onSessionReplaced(replaced)
    await api.request('POST', '/api/control/reset')
    expect(replaced).toHaveBeenCalledTimes(1)
    expect(replaced.mock.calls[0][0]).toMatchObject({ token: 'sandbox-2' })
    expect(window.localStorage.getItem('gesture-to-pc.session-token')).toBe('sandbox-2')
  })

  it('does not announce a new token from a restarted local backend', async () => {
    let issued = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/session') {
          issued += 1
          return json(200, { token: `launch-${issued}`, hosted: false, limits: null })
        }
        if (headersOf(init)['X-Session-Token'] === 'launch-1') return json(401, { error: { code: 'invalid_session_token', message: 'Missing or invalid X-Session-Token header' } })
        return json(200, { ok: true })
      }),
    )
    const api = await freshApi()
    const replaced = vi.fn()
    api.onSessionReplaced(replaced)
    await api.request('POST', '/api/control/reset')
    expect(replaced).not.toHaveBeenCalled()
  })
})

describe('errorMessage', () => {
  it('appends readiness reasons', () => {
    const error = new ApiError('not_ready', 'Cannot arm PC control', 409, { reasons: ['No streaming sensor.', 'Recognition is not running.'] })
    expect(errorMessage(error)).toBe('Cannot arm PC control: No streaming sensor. Recognition is not running.')
  })

  it('summarises validation errors without the body prefix', () => {
    const error = new ApiError('validation_error', 'Request validation failed', 422, [{ loc: ['body', 'live_seconds'], msg: 'Input should be less than or equal to 60' }])
    expect(errorMessage(error)).toBe('Request validation failed (live_seconds: Input should be less than or equal to 60)')
  })

  it('handles plain errors and values', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage('text')).toBe('text')
  })
})
