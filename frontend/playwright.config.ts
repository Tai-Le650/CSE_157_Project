import os from 'node:os'
import path from 'node:path'
import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.GESTURE_TO_PC_E2E_PORT ?? 8765)
const root = path.resolve(import.meta.dirname, '..')
process.env.GESTURE_TO_PC_E2E_WORKSPACE ??= path.join(os.tmpdir(), 'gesture-to-pc-e2e', `run-${Date.now()}`)
const workspace = process.env.GESTURE_TO_PC_E2E_WORKSPACE
const python = process.platform === 'win32' ? path.join('.venv', 'Scripts', 'python.exe') : path.join('.venv', 'bin', 'python')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: 'msedge',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `${python} ${path.join('backend', 'run.py')} --port ${PORT}`,
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
})
