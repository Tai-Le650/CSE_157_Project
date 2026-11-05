import { expect, test } from '@playwright/test'
import { call, setDemoMode } from './helpers'

const PAGES = [
  ['/', 'Dashboard'],
  ['/sensors', 'Sensor Connections'],
  ['/live', 'Live Sensor Data'],
  ['/recorder', 'Gesture Recorder'],
  ['/datasets', 'Dataset Manager'],
  ['/training', 'Model Training'],
  ['/recognition', 'Live Recognition'],
  ['/mappings', 'Command Mapping'],
  ['/sound', 'Sound Activation'],
  ['/settings', 'Settings'],
] as const

test.beforeAll(async ({ request }) => {
  await setDemoMode(request, false)
})

test.describe('real mode', () => {
  for (const [route, title] of PAGES) {
    test(`${title} page loads without errors`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      await page.goto(route)
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible()
      await expect(page.getByText('Unexpected Application Error')).toHaveCount(0)
      expect(errors).toEqual([])
    })
  }

  test('the sidebar reaches every page without a reload', async ({ page }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation')
    for (const [, title] of PAGES) {
      await nav.getByRole('link', { name: title, exact: true }).click()
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible()
    }
  })

  test('unavailable features explain why instead of faking data', async ({ page }) => {
    await page.goto('/sound')
    await expect(page.getByText('Unavailable with the current firmware')).toBeVisible()
    await expect(page.getByText('No compatible microphone stream')).toBeVisible()
    await page.goto('/')
    await expect(page.getByText('Real hardware')).toBeVisible()
  })

  test('PC control is off by default and arming is refused with reasons', async ({ request }) => {
    const control = await call<{ pc_control_enabled: boolean; armed: boolean }>(request, 'GET', '/api/control')
    expect(control.pc_control_enabled).toBe(false)
    expect(control.armed).toBe(false)
    const session = (await (await request.get('/api/session')).json()) as { token: string }
    const response = await request.post('/api/control/arm', { headers: { 'X-Session-Token': session.token }, data: { control_session_id: 'not-a-session', confirm: true } })
    expect(response.status()).toBe(409)
    const body = (await response.json()) as { error: { details: { reasons: string[] } } }
    expect(body.error.details.reasons.join(' ')).toContain('PC control is disabled in Settings')
  })

  test('the API rejects foreign origins and missing session tokens', async ({ request }) => {
    const foreign = await request.post('/api/control/disarm', { headers: { Origin: 'http://evil.example' }, data: { reason: 'test' } })
    expect(foreign.status()).toBe(403)
    const missingToken = await request.post('/api/control/disarm', { data: { reason: 'test' } })
    expect(missingToken.status()).toBe(401)
  })
})
