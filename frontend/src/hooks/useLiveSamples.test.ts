import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { SamplesBatch } from '@/types/api'
import { SampleRing, useLiveSamples } from './useLiveSamples'

const mocks = vi.hoisted(() => ({
  listener: null as null | ((message: unknown) => void),
  resolveBuffer: null as null | ((value: unknown) => void),
  unsubscribe: vi.fn(),
  topics: [] as string[],
}))

vi.mock('@/services/ws', () => ({
  wsClient: {
    subscribe: (topic: string, listener: (message: unknown) => void) => {
      mocks.topics.push(topic)
      mocks.listener = listener
      return mocks.unsubscribe
    },
  },
}))

vi.mock('@/services/api', () => ({
  request: () =>
    new Promise((resolve) => {
      mocks.resolveBuffer = resolve
    }),
}))

function batch(epoch: number, tUs: number[], fill: Partial<Record<'ax' | 'ay' | 'az' | 'gx' | 'gy' | 'gz', number>> = {}): SamplesBatch {
  const column = (axis: 'ax' | 'ay' | 'az' | 'gx' | 'gy' | 'gz') => tUs.map(() => fill[axis] ?? 0)
  return { sensor_id: 'S1', simulated: false, epoch, t_us: tUs, ax: column('ax'), ay: column('ay'), az: column('az'), gx: column('gx'), gy: column('gy'), gz: column('gz') }
}

describe('SampleRing', () => {
  it('keeps samples in time order and skips ones it already holds', () => {
    const ring = new SampleRing(10)
    ring.push(batch(0, [0, 10_000, 20_000]))
    ring.push(batch(0, [10_000, 20_000, 30_000]))
    expect(ring.window(10, ['ax']).t).toEqual([0, 0.01, 0.02, 0.03])
    expect(ring.received).toBe(6)
  })

  it('starts over when the device clock epoch changes', () => {
    const ring = new SampleRing(10)
    ring.push(batch(0, [5_000_000, 5_010_000]))
    ring.push(batch(1, [0, 10_000]))
    expect(ring.epoch).toBe(1)
    expect(ring.window(10, ['ax']).t).toEqual([0, 0.01])
  })

  it('overwrites the oldest samples when full', () => {
    const ring = new SampleRing(4)
    ring.push(batch(0, [0, 1, 2, 3, 4, 5].map((s) => s * 1_000_000)))
    expect(ring.size).toBe(4)
    expect(ring.window(100, ['ax']).t).toEqual([2, 3, 4, 5])
  })

  it('windows by time and derives magnitudes', () => {
    const ring = new SampleRing(100)
    ring.push(batch(0, [0, 1, 2, 3].map((s) => s * 1_000_000), { ax: 3, ay: 4, gx: 1, gy: 2, gz: 2 }))
    const view = ring.window(1.5, ['amag', 'gmag', 'ax'])
    expect(view.t).toEqual([2, 3])
    expect(view.series.amag).toEqual([5, 5])
    expect(view.series.gmag).toEqual([3, 3])
    expect(view.series.ax).toEqual([3, 3])
  })
})

describe('useLiveSamples', () => {
  it('backfills the buffer first, then applies live batches that arrived meanwhile', async () => {
    const { result, unmount } = renderHook(() => useLiveSamples('S1', 100))
    expect(mocks.topics).toContain('samples:S1')
    act(() => {
      mocks.listener?.({ type: 'samples', topic: 'samples:S1', data: batch(7, [1_000_000, 1_010_000]) })
    })
    expect(result.current.current.size).toBe(0)
    await act(async () => {
      mocks.resolveBuffer?.({ epoch: 7, simulated: false, t_us: [990_000, 1_000_000], values: [[0, 0, 1, 0, 0, 0], [0, 0, 1, 0, 0, 0]] })
    })
    await waitFor(() => expect(result.current.current.window(10, ['ax']).t).toEqual([0.99, 1, 1.01]))
    unmount()
    expect(mocks.unsubscribe).toHaveBeenCalledTimes(1)
  })
})
