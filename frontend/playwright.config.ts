import os from 'node:os'
import path from 'node:path'
import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.GESTURE_TO_PC_E2E_PORT ?? 8765)
const HOSTED_PORT = Number(process.env.GESTURE_TO_PC_E2E_HOSTED_PORT ?? 8766)
const root = path.resolve(import.meta.dirname, '..')
process.env.GESTURE_TO_PC_E2E_WORKSPACE ??= path.join(os.tmpdir(), 'gesture-to-pc-e2e', `run-${Date.now()}`)
const workspace = process.env.GESTURE_TO_PC_E2E_WORKSPACE
const python = process.platform === 'win32' ? path.join('.venv', 'Scripts', 'python.exe') : path.join('.venv', 'bin', 'python')
const runPy = path.join('backend', 'run.py')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    channel: 'msedge',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'local', testIgnore: /hosted\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${PORT}` } },
    { name: 'hosted', testMatch: /hosted\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${HOSTED_PORT}` } },
  ],
  webServer: [
    {
      command: `${python} ${runPy} --port ${PORT}`,
      cwd: root,
      url: `http://127.0.0.1:${PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        GESTURE_TO_PC_DATA_DIR: path.join(workspace, 'data'),
        GESTURE_TO_PC_MODELS_DIR: path.join(workspace, 'models'),
      },
    },
    {
      command: `${python} ${runPy} --hosted --port ${HOSTED_PORT}`,
      cwd: root,
      url: `http://127.0.0.1:${HOSTED_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        GESTURE_TO_PC_BIND_HOST: '127.0.0.1',
        GESTURE_TO_PC_SANDBOX_DIR: path.join(workspace, 'sandboxes'),
        GESTURE_TO_PC_PROJECT_URL: 'https://example.org/gesture-to-pc',
      },
    },
  ],
})
