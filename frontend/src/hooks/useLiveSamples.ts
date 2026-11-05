import { useEffect, useRef } from 'react'
import { request } from '@/services/api'
import { wsClient } from '@/services/ws'
import type { Channel, SamplesBatch } from '@/types/api'

const AXES = ['ax', 'ay', 'az', 'gx', 'gy', 'gz'] as const

export class SampleRing {
  readonly capacity: number
  t: Float64Array
  data: Record<(typeof AXES)[number], Float64Array>
  head = 0
  size = 0
  epoch: number | null = null
  simulated = false
  received = 0
  lastBatchAt = 0

  constructor(capacity = 20000) {
    this.capacity = capacity
    this.t = new Float64Array(capacity)
    this.data = Object.fromEntries(AXES.map((axis) => [axis, new Float64Array(capacity)])) as Record<(typeof AXES)[number], Float64Array>
  }

  clear() {
    this.head = 0
    this.size = 0
  }

  newestTime(): number | null {
    return this.size ? this.t[(this.head - 1 + this.capacity) % this.capacity] : null
  }

  push(batch: SamplesBatch) {
    if (this.epoch !== null && this.epoch !== batch.epoch) {
      this.clear()
    }
    this.epoch = batch.epoch
    this.simulated = batch.simulated
    const n = batch.t_us.length
    const newest = this.newestTime()
    for (let i = 0; i < n; i++) {
      if (newest !== null && batch.t_us[i] / 1e6 <= newest) continue
      const at = this.head
      this.t[at] = batch.t_us[i] / 1e6
      for (const axis of AXES) this.data[axis][at] = batch[axis][i]
      this.head = (at + 1) % this.capacity
      if (this.size < this.capacity) this.size += 1
    }
    this.received += n
    this.lastBatchAt = performance.now()
  }

  window(seconds: number, channels: Channel[]): { t: number[]; series: Record<string, number[]> } {
    const out: { t: number[]; series: Record<string, number[]> } = { t: [], series: {} }
    for (const channel of channels) out.series[channel] = []
    if (this.size === 0) return out
    const newest = this.t[(this.head - 1 + this.capacity) % this.capacity]
    const cutoff = newest - seconds
    const start = (this.head - this.size + this.capacity) % this.capacity
    for (let k = 0; k < this.size; k++) {
      const i = (start + k) % this.capacity
      const time = this.t[i]
      if (time < cutoff) continue
      out.t.push(time)
      for (const channel of channels) {
        let value: number
        if (channel === 'amag') value = Math.hypot(this.data.ax[i], this.data.ay[i], this.data.az[i])
        else if (channel === 'gmag') value = Math.hypot(this.data.gx[i], this.data.gy[i], this.data.gz[i])
        else value = this.data[channel][i]
        out.series[channel].push(value)
      }
    }
    return out
  }
}

export function useLiveSamples(sensorId: string | null | undefined, capacity = 20000) {
  const ring = useRef(new SampleRing(capacity))
  useEffect(() => {
    const target = new SampleRing(capacity)
    ring.current = target
    if (!sensorId) return
    let live = false
    const queued: SamplesBatch[] = []
    const unsubscribe = wsClient.subscribe(`samples:${sensorId}`, (message) => {
      if (message.type !== 'samples') return
      if (live) target.push(message.data as SamplesBatch)
      else queued.push(message.data as SamplesBatch)
    })
    request<{ epoch: number | null; simulated: boolean; t_us: number[]; values: number[][] }>('GET', `/api/sensors/${encodeURIComponent(sensorId)}/buffer?seconds=60&fmt=json`)
      .then((buffer) => {
        if (buffer.t_us.length && buffer.epoch !== null) {
          const column = (i: number) => buffer.values.map((row) => row[i])
          target.push({ sensor_id: sensorId, simulated: buffer.simulated, epoch: buffer.epoch, t_us: buffer.t_us, ax: column(0), ay: column(1), az: column(2), gx: column(3), gy: column(4), gz: column(5) })
        }
      })
      .catch(() => undefined)
      .finally(() => {
        live = true
        for (const batch of queued) target.push(batch)
        queued.length = 0
      })
    return unsubscribe
  }, [sensorId, capacity])
  return ring
}
