import { expect, test, type Page } from '@playwright/test'

async function waitForConnection(page: Page) {
  await expect(page.getByRole('note', { name: 'Online demo' })).toBeVisible()
  await expect(page.getByText(/Connecting to the online demo|Connecting to the Gesture-to-PC backend/)).toHaveCount(0)
}

function storedToken(page: Page): Promise<string | null> {
  return page.evaluate(() => window.localStorage.getItem('gesture-to-pc.session-token'))
}

test('online demo: private sandbox per visitor, Demo Mode locked on, simulated sensor streams', async ({ page, browser }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))

  await test.step('the banner explains the online demo and links to the local app', async () => {
    await page.goto('/')
    await waitForConnection(page)
    await expect(page.getByRole('link', { name: /run it on your own PC/ })).toHaveAttribute('href', 'https://example.org/gesture-to-pc')
  })

  await test.step('Settings cannot turn Demo Mode off or change the data folder', async () => {
    await page.goto('/settings')
    await waitForConnection(page)
    await expect(page.getByText(/always on in the online demo/)).toBeVisible()
    await expect(page.getByRole('switch', { name: /^Demo Mode/ })).toHaveCount(0)
    await expect(page.getByText('Storage', { exact: true })).toHaveCount(0)
  })

  await test.step('a simulated sensor connects and streams live data', async () => {
    await page.getByRole('navigation').getByRole('link', { name: 'Sensor Connections', exact: true }).click()
    await page.getByRole('button', { name: 'Connect simulated sensor' }).click()
    await expect(page.getByText('DEMO-1').first()).toBeVisible({ timeout: 20_000 })
    await page.getByRole('navigation').getByRole('link', { name: 'Live Sensor Data', exact: true }).click()
    await expect(page.locator('.uplot canvas').first()).toBeVisible()
  })

  await test.step('a second visitor gets a separate, empty sandbox', async () => {
    const other = await browser.newContext()
    try {
      const otherPage = await other.newPage()
      await otherPage.goto('/sensors')
      await waitForConnection(otherPage)
      await expect(otherPage.getByRole('link', { name: 'No sensors connected' })).toBeVisible()
      await expect(otherPage.getByText('DEMO-1')).toHaveCount(0)
      const [mine, theirs] = await Promise.all([storedToken(page), storedToken(otherPage)])
      expect(mine).toBeTruthy()
      expect(theirs).toBeTruthy()
      expect(mine).not.toBe(theirs)
    } finally {
      await other.close()
    }
  })

  expect(errors).toEqual([])
})
