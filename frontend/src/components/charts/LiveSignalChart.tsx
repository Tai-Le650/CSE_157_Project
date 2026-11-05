import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type uPlot from 'uplot'
import { Play, ScanSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DemoBadge } from '@/components/common/StatusBadge'
import { useLiveSamples } from '@/hooks/useLiveSamples'
import { useTheme } from '@/hooks/useTheme'
import { accelFactor, CHANNEL_LABELS, cssVar, gyroFactor, isAccel, seriesColorVar, unitLabel, type AccelUnit, type GyroUnit } from '@/lib/units'
import type { Channel } from '@/types/api'
import { UPlotChart } from './UPlotChart'
import { axisTheme, wheelZoomPlugin } from './uplotHelpers'

const FRAME_MS = 40

export function LiveSignalChart({
  sensorId,
  channels,
  windowS,
  paused = false,
  accelUnit = 'g',
  gyroUnit = 'deg/s',
  height = 220,
  title,
  showAxes = true,
}: {
  sensorId: string | null | undefined
  channels: Channel[]
  windowS: number
  paused?: boolean
  accelUnit?: AccelUnit
  gyroUnit?: GyroUnit
  height?: number
  title?: string
  showAxes?: boolean
}) {
  const ring = useLiveSamples(sensorId)
  const { resolvedTheme } = useTheme()
  const plot = useRef<uPlot | null>(null)
  const [following, setFollowing] = useState(true)
  const followRef = useRef(true)
  followRef.current = following
  const [hasData, setHasData] = useState(false)
  const [simulated, setSimulated] = useState(false)
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  const channelKey = channels.join(',')

  const markUserView = useCallback(() => setFollowing(false), [])

  const options = useMemo<Omit<uPlot.Options, 'width' | 'height'>>(() => {
    const axis = axisTheme()
    const unit = channels.length ? unitLabel(channels[0], accelUnit, gyroUnit) : ''
    return {
      legend: { show: showAxes },
      cursor: { drag: { x: true, y: false, setScale: true } },
      scales: { x: { time: false } },
      axes: showAxes
        ? [
            { ...axis, label: 'Device time (s)', values: (_u, ticks) => ticks.map((v) => v.toFixed(1)) },
            { ...axis, label: unit, size: 56 },
          ]
        : [{ show: false }, { show: false }],
      series: [
        { label: 't (s)', value: (_u, v) => (v === null || v === undefined ? '—' : v.toFixed(3)) },
        ...channels.map((channel) => ({
          label: CHANNEL_LABELS[channel],
          stroke: cssVar(seriesColorVar(channel), '#3b82f6'),
          width: channel === 'amag' || channel === 'gmag' ? 1.8 : 1.4,
          points: { show: false },
          value: (_u: uPlot, v: number | null) => (v === null || v === undefined ? '—' : v.toFixed(isAccel(channel) ? 3 : 1)),
        })),
      ],
      hooks: {
        setSelect: [
          (u: uPlot) => {
            if (u.select.width > 2) markUserView()
          },
        ],
        ready: [
          (u: uPlot) => {
            u.over.addEventListener('dblclick', () => setFollowing(true))
          },
        ],
      },
      plugins: showAxes ? [wheelZoomPlugin(markUserView)] : [],
    }
  }, [channelKey, accelUnit, gyroUnit, resolvedTheme, showAxes, markUserView])

  const initial = useMemo<uPlot.AlignedData>(() => [[], ...channels.map(() => [])], [channelKey])

  useEffect(() => {
    let frame = 0
    let last = 0
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick)
      if (now - last < FRAME_MS || pausedRef.current) return
      last = now
      const u = plot.current
      if (!u) return
      const { t, series } = ring.current.window(windowS, channels)
      if (!t.length) {
        setHasData(false)
        return
      }
      setHasData(true)
      setSimulated(ring.current.simulated)
      const data: uPlot.AlignedData = [t, ...channels.map((channel) => {
        const factor = isAccel(channel) ? accelFactor(accelUnit) : gyroFactor(gyroUnit)
        const values = series[channel]
        return factor === 1 ? values : values.map((v) => v * factor)
      })]
      u.setData(data, followRef.current)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [channelKey, windowS, accelUnit, gyroUnit, ring])

  return (
    <div className="relative">
      {title || !following || simulated ? (
        <div className="mb-2 flex min-h-6 items-center justify-between gap-2">
          <div className="text-sm font-medium">{title}</div>
          <div className="flex items-center gap-2">
            {simulated ? <DemoBadge /> : null}
            {!following ? (
              <Button size="xs" variant="outline" onClick={() => setFollowing(true)}>
                <Play /> Resume live view
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
      <UPlotChart options={options} data={initial} height={height} onReady={(u) => (plot.current = u)} />
      {!hasData ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          <span className="flex items-center gap-2 rounded-md bg-background/80 px-3 py-1.5">
            <ScanSearch className="size-4" />
            {sensorId ? 'Waiting for samples…' : 'Select a sensor'}
          </span>
        </div>
      ) : null}
    </div>
  )
}
