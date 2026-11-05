import { expect, type APIRequestContext } from '@playwright/test'

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export const DEMO_SENSOR = 'DEMO-1'
export const TRAINING_LABELS = ['idle', 'swipe_left', 'swipe_right', 'wrist_rotation'] as const

async function sessionToken(request: APIRequestContext): Promise<string> {
  const response = await request.get('/api/session')
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { token: string }).token
}

export async function call<T = unknown>(request: APIRequestContext, method: Method, path: string, data?: unknown): Promise<T> {
  const headers: Record<string, string> = method === 'GET' ? {} : { 'X-Session-Token': await sessionToken(request) }
  const response = await request.fetch(path, { method, headers, data: method === 'GET' ? undefined : (data ?? {}) })
  if (!response.ok()) throw new Error(`${method} ${path} failed with ${response.status()}: ${await response.text()}`)
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export async function setDemoMode(request: APIRequestContext, enabled: boolean): Promise<void> {
  const settings = await call<{ demo_mode: boolean }>(request, 'GET', '/api/settings')
  if (settings.demo_mode !== enabled) await call(request, 'POST', '/api/settings/demo-mode', { enabled, confirm: true })
}

export async function waitForRecorderIdle(request: APIRequestContext): Promise<void> {
  await expect
    .poll(async () => (await call<{ state: { active: boolean } }>(request, 'GET', '/api/recorder')).state.active, { timeout: 90_000, intervals: [250] })
    .toBe(false)
}

export async function recordTrials(request: APIRequestContext, labelId: string, sessionId: string, trials = 3): Promise<void> {
  await call(request, 'POST', '/api/recorder/trials', { label_id: labelId, sensor_ids: [DEMO_SENSOR], duration_s: 1.5, countdown_s: 0.2, trials, pause_s: 0.1, session_id: sessionId })
  await waitForRecorderIdle(request)
}

export async function saveAllStaged(request: APIRequestContext): Promise<{ saved: string[]; errors: unknown[] }> {
  const recorder = await call<{ staging: { staging_id: string }[] }>(request, 'GET', '/api/recorder')
  return call(request, 'POST', '/api/recorder/staging/save', { staging_ids: recorder.staging.map((s) => s.staging_id) })
}

export async function performDemoGesture(request: APIRequestContext, label: string): Promise<void> {
  await call(request, 'POST', `/api/demo/sensors/${DEMO_SENSOR}/perform`, { label })
}
