import { useMemo, useRef } from 'react'
import type uPlot from 'uplot'
import { useTheme } from '@/hooks/useTheme'
import { CHANNEL_LABELS, cssVar, isAccel, seriesColorVar } from '@/lib/units'
import type { Channel, SignalPreview } from '@/types/api'
import { UPlotChart } from './UPlotChart'
import { axisTheme, segmentOverlayPlugin, wheelZoomPlugin } from './uplotHelpers'

export interface OverlaySegment {
  start_s: number
  end_s: number
  label: string
  color?: string
}

export function StaticSignalChart({
  preview,
  channels,
  height = 240,
  segments = [],
  selectMode = false,
  onSelectRange,
  showMarkers = true,
}: {
  preview: SignalPreview
  channels: Channel[]
  height?: number
  segments?: OverlaySegment[]
  selectMode?: boolean
  onSelectRange?: (start: number, end: number) => void
  showMarkers?: boolean
}) {
  const { resolvedTheme } = useTheme()
  const segmentsRef = useRef(segments)
  segmentsRef.current = segments
  const markers = useMemo(() => (showMarkers ? (preview.markers ?? []).filter((m) => m.t_s !== null).map((m) => m.t_s as number) : []), [preview, showMarkers])
  const markersRef = useRef(markers)
  markersRef.current = markers
  const selectRef = useRef(onSelectRange)
  selectRef.current = onSelectRange
  const accel = channels.length ? isAccel(channels[0]) : true

  const options = useMemo<Omit<uPlot.Options, 'width' | 'height'>>(() => {
    const axis = axisTheme()
    return {
      cursor: { drag: { x: true, y: false, setScale: !selectMode } },
      scales: { x: { time: false } },
      axes: [
        { ...axis, label: 'Recording time (s)' },
        { ...axis, label: accel ? preview.units?.accel ?? 'g' : preview.units?.gyro ?? 'deg/s', size: 56 },
      ],
      series: [
        { label: 't (s)', value: (_u, v) => (v === null || v === undefined ? '—' : v.toFixed(3)) },
        ...channels.map((channel) => ({
          label: CHANNEL_LABELS[channel],
          stroke: cssVar(seriesColorVar(channel), '#3b82f6'),
          width: 1.4,
          points: { show: false },
        })),
      ],
      hooks: {
        setSelect: [
          (u: uPlot) => {
            if (!selectMode || u.select.width < 3) return
            const start = u.posToVal(u.select.left, 'x')
            const end = u.posToVal(u.select.left + u.select.width, 'x')
            selectRef.current?.(Math.max(0, start), end)
          },
        ],
      },
      plugins: [
        segmentOverlayPlugin(() => segmentsRef.current, () => markersRef.current),
        wheelZoomPlugin(() => undefined),
      ],
    }
  }, [channels.join(','), selectMode, resolvedTheme, accel, preview.units?.accel, preview.units?.gyro])

  const data = useMemo<uPlot.AlignedData>(() => [preview.t_s, ...channels.map((c) => preview.channels[c] ?? [])], [preview, channels.join(',')])
  return <UPlotChart options={options} data={data} height={height} />
}
