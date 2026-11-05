import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { EmergencyStopButton, useEmergencyStop } from './EmergencyStop'

const mocks = vi.hoisted(() => ({
  socketStop: vi.fn(() => true),
  restStop: vi.fn(async (_source?: string) => ({})),
  toastError: vi.fn(),
}))

vi.mock('@/services/ws', () => ({ wsClient: { emergencyStop: mocks.socketStop, subscribe: () => () => undefined } }))

vi.mock('@/services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api')>()
  return { ...actual, api: { ...actual.api, control: { ...actual.api.control, emergencyStop: mocks.restStop } } }
})

vi.mock('sonner', () => ({ toast: { error: mocks.toastError, success: vi.fn() } }))

beforeEach(() => {
  mocks.socketStop.mockReset().mockReturnValue(true)
  mocks.restStop.mockReset().mockResolvedValue({})
  mocks.toastError.mockReset()
})

describe('Emergency Stop', () => {
  it('uses the socket fast path and the REST call together', async () => {
    const { result } = renderHook(() => useEmergencyStop())
    await act(() => result.current())
    expect(mocks.socketStop).toHaveBeenCalledTimes(1)
    expect(mocks.restStop).toHaveBeenCalledWith('ui_button')
    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining('PC control disarmed'))
  })

  it('stays quiet when REST fails but the socket delivered the stop', async () => {
    mocks.restStop.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useEmergencyStop())
    await act(() => result.current())
    expect(mocks.toastError).not.toHaveBeenCalled()
  })

  it('warns when neither path reached the backend', async () => {
    mocks.socketStop.mockReturnValue(false)
    mocks.restStop.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useEmergencyStop())
    await act(() => result.current())
    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining('could not reach the backend'))
  })

  it('triggers from the button and from Shift+Esc', async () => {
    render(
      <TooltipProvider>
        <EmergencyStopButton />
      </TooltipProvider>,
    )
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Emergency Stop' }))
    })
    await act(async () => {
      fireEvent.keyDown(window, { key: 'Escape', shiftKey: true })
    })
    await act(async () => {
      fireEvent.keyDown(window, { key: 'Escape' })
    })
    expect(mocks.socketStop).toHaveBeenCalledTimes(2)
    expect(mocks.restStop).toHaveBeenCalledTimes(2)
  })
})
