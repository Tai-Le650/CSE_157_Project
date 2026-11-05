import { expect, test, type Locator, type Page } from '@playwright/test'
import { DEMO_SENSOR, TRAINING_LABELS, call, performDemoGesture, recordTrials, saveAllStaged, setDemoMode, waitForRecorderIdle } from './helpers'

function field(page: Page, name: string): Locator {
  return page.getByRole('group', { name, exact: true })
}

async function choose(page: Page, fieldName: string, option: RegExp) {
  await field(page, fieldName).getByRole('combobox').click()
  await page.getByRole('option', { name: option }).click()
}

async function performUntil(page: Page, request: Parameters<typeof call>[0], label: string, rows: Locator, attempts = 3) {
  const before = await rows.count()
  for (let attempt = 0; attempt < attempts; attempt++) {
    await performDemoGesture(request, label)
    try {
      await expect.poll(() => rows.count(), { timeout: 6_000 }).toBeGreaterThan(before)
      return
    } catch (error) {
      if (attempt === attempts - 1) throw error
      await page.waitForTimeout(1_500)
    }
  }
}

test.beforeAll(async ({ request }) => {
  await setDemoMode(request, false)
})

test.afterAll(async ({ request }) => {
  await call(request, 'POST', '/api/recognition/stop').catch(() => undefined)
  await call(request, 'PATCH', '/api/settings', { values: { control: { pc_control_enabled: false } } }).catch(() => undefined)
  await setDemoMode(request, false).catch(() => undefined)
})

test('demo workflow: connect, live, record, dataset, train, recognize, map, arm, emergency stop', async ({ page, request }) => {
  test.setTimeout(300_000)

  await test.step('turn on Demo Mode and allow (simulated) PC control in Settings', async () => {
    await page.goto('/settings')
    await page.getByRole('switch', { name: /^Demo Mode/ }).click()
    await page.getByRole('button', { name: 'Enable Demo Mode', exact: true }).click()
    await expect(page.getByText(/sensors, signals and gestures are simulated/)).toBeVisible()
    await page.getByRole('switch', { name: /^Allow PC control/ }).click()
    await page.getByRole('button', { name: 'Allow PC control', exact: true }).click()
    await expect(page.getByRole('switch', { name: /^Allow PC control/ })).toBeChecked()
  })

  await test.step('connect a simulated sensor', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Sensor Connections', exact: true }).click()
    await page.getByRole('button', { name: 'Connect simulated sensor' }).click()
    await expect.poll(async () => (await call<{ status: string }>(request, 'GET', `/api/sensors/${DEMO_SENSOR}`)).status, { timeout: 20_000 }).toBe('streaming')
    await expect(page.getByText(DEMO_SENSOR).first()).toBeVisible()
  })

  await test.step('watch live data', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Live Sensor Data', exact: true }).click()
    await expect(page.locator('.uplot canvas').first()).toBeVisible()
    const parsed = async () => (await call<{ counters: { samples_parsed?: number } }>(request, 'GET', `/api/sensors/${DEMO_SENSOR}`)).counters.samples_parsed ?? 0
    const first = await parsed()
    await expect.poll(parsed, { timeout: 5_000 }).toBeGreaterThan(first)
  })

  await test.step('record and save two trials in the Gesture Recorder', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Gesture Recorder', exact: true }).click()
    await choose(page, 'Label', /swipe_right/)
    await field(page, 'Trial duration (s)').getByRole('spinbutton').fill('1.5')
    await field(page, 'Countdown (s)').getByRole('spinbutton').fill('0.2')
    await field(page, 'Trials').getByRole('spinbutton').fill('2')
    await field(page, 'Pause between (s)').getByRole('spinbutton').fill('0.1')
    await page.getByRole('button', { name: 'New session' }).click()
    await expect(page.getByText(/New session started/)).toBeVisible()
    await page.getByRole('button', { name: 'Start 2 trials' }).click()
    await expect(page.getByText('Staged trials (2)')).toBeVisible({ timeout: 30_000 })
    await waitForRecorderIdle(request)
    await page.getByRole('checkbox', { name: 'Select all' }).click()
    await page.getByRole('button', { name: 'Save selected' }).click()
    await expect(page.getByText('Saved 2 recording(s)')).toBeVisible()
  })

  await test.step('add trials for every class across two more sessions', async () => {
    for (const name of ['E2E session A', 'E2E session B']) {
      const session = await call<{ session_id: string }>(request, 'POST', '/api/recorder/session', { name })
      for (const label of TRAINING_LABELS) await recordTrials(request, label, session.session_id)
    }
    const result = await saveAllStaged(request)
    expect(result.errors).toEqual([])
    expect(result.saved).toHaveLength(24)
  })

  await test.step('build a dataset in the Dataset Manager', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Dataset Manager', exact: true }).click()
    await page.getByRole('tab', { name: /^Datasets/ }).click()
    await page.getByPlaceholder('New dataset name').fill('E2E gestures')
    await page.getByRole('button', { name: 'Create dataset' }).click()
    await page.getByRole('tab', { name: /^Recordings \(26\)/ }).click()
    await page.getByRole('checkbox', { name: 'Select all' }).click()
    await page.getByRole('combobox').filter({ hasText: 'Choose dataset' }).click()
    await page.getByRole('option', { name: /E2E gestures/ }).click()
    await page.getByRole('button', { name: 'Add to dataset' }).click()
    await expect(page.getByText('Added 26')).toBeVisible()
    await page.getByRole('tab', { name: /^Datasets/ }).click()
    await expect(page.getByText('Ready to train')).toBeVisible()
  })

  await test.step('train a model with grouped evaluation', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Model Training', exact: true }).click()
    await expect(field(page, 'Dataset').getByRole('combobox')).toContainText('E2E gestures')
    await field(page, 'Model name (optional)').getByRole('textbox').fill('E2E model')
    await page.getByRole('button', { name: 'Train model' }).click()
    await expect(page.getByText(/Last job done/)).toBeVisible({ timeout: 180_000 })
    await expect(page.getByText('Macro F1')).toBeVisible()
  })

  await test.step('recognize a simulated gesture', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Live Recognition', exact: true }).click()
    await choose(page, 'Model', /E2E model/)
    await choose(page, 'Sensor', new RegExp(DEMO_SENSOR))
    await page.getByRole('button', { name: 'Start recognition' }).click()
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
    await page.waitForTimeout(2_000)
    const rows = page.getByRole('row').filter({ hasText: 'swipe_right' })
    await performUntil(page, request, 'swipe_right', rows)
    await expect(rows.first()).toContainText('no mapping')
    await expect(rows.first()).toContainText('unmapped')
  })

  await test.step('map swipe_right in the Browser navigation profile', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Command Mapping', exact: true }).click()
    await expect(page.getByRole('radio', { name: /^Activate Browser navigation/ })).toBeChecked()
    await page.getByRole('button', { name: /^Browser navigation/ }).click()
    const row = page.getByRole('row').filter({ hasText: 'swipe_right' })
    await row.getByRole('switch', { name: 'Enabled' }).click()
    await row.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(page.getByText('Mapping saved')).toBeVisible()
  })

  await test.step('arm simulated PC control and run a simulated action', async () => {
    await page.getByRole('button', { name: 'Arm…' }).click()
    const dialog = page.getByRole('dialog', { name: 'Arm PC control?' })
    await expect(dialog.getByText('swipe_right')).toBeVisible()
    await dialog.getByRole('button', { name: 'Arm (simulated)' }).click()
    await expect(page.getByText('ARMED', { exact: true })).toBeVisible()
    await page.waitForTimeout(2_000)
    const simulatedRows = page.getByRole('row').filter({ hasText: 'swipe_right' }).filter({ hasText: 'simulated' })
    await performUntil(page, request, 'swipe_right', simulatedRows)
    const control = await call<{ armed: boolean; simulated_actions: boolean; history: { outcome: string }[] }>(request, 'GET', '/api/control')
    expect(control.armed).toBe(true)
    expect(control.simulated_actions).toBe(true)
    expect(control.history.some((h) => h.outcome === 'executed')).toBe(false)
  })

  await test.step('Emergency Stop disarms immediately and stays latched until reset', async () => {
    await page.getByRole('banner').getByRole('button', { name: 'Emergency Stop' }).click()
    await expect(page.getByRole('banner').getByText('E-stop latched')).toBeVisible()
    const stopped = await call<{ armed: boolean; estop_latched: boolean }>(request, 'GET', '/api/control')
    expect(stopped).toMatchObject({ armed: false, estop_latched: true })
    await expect(page.getByRole('button', { name: 'Arm…' })).toBeDisabled()
    await page.getByRole('banner').getByRole('button', { name: 'Reset' }).click()
    await expect(page.getByRole('banner').getByRole('button', { name: 'Emergency Stop' })).toBeVisible()
    const reset = await call<{ armed: boolean; estop_latched: boolean }>(request, 'GET', '/api/control')
    expect(reset).toMatchObject({ armed: false, estop_latched: false })
  })
})
