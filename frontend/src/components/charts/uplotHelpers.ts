import type uPlot from 'uplot'
import { cssVar } from '@/lib/units'

export function axisTheme(): Partial<uPlot.Axis> {
  const stroke = cssVar('--plot-axis', '#667085')
  const grid = cssVar('--plot-grid', '#e5e7eb')
  return {
    stroke,
    grid: { stroke: grid, width: 1 },
    ticks: { stroke: grid, width: 1 },
    font: '11px "Segoe UI", system-ui, sans-serif',
    labelFont: '12px "Segoe UI", system-ui, sans-serif',
  }
}

export function wheelZoomPlugin(onUserView: () => void): uPlot.Plugin {
  return {
    hooks: {
      ready: (u: uPlot) => {
        const over = u.over
        over.addEventListener(
          'wheel',
          (event: WheelEvent) => {
            if (!event.shiftKey && !event.ctrlKey && !event.metaKey) return
            event.preventDefault()
            const xMin = u.scales.x.min
            const xMax = u.scales.x.max
            if (xMin === undefined || xMax === undefined || xMin === null || xMax === null) return
            const range = xMax - xMin
            if (event.shiftKey) {
              const shift = range * 0.1 * Math.sign(event.deltaY || event.deltaX)
              u.setScale('x', { min: xMin + shift, max: xMax + shift })
            } else {
              const rect = over.getBoundingClientRect()
              const position = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
              const anchor = xMin + range * position
              const factor = event.deltaY < 0 ? 0.8 : 1.25
              const next = Math.max(range * factor, 0.05)
              u.setScale('x', { min: anchor - next * position, max: anchor + next * (1 - position) })
            }
            onUserView()
          },
          { passive: false },
        )
      },
    },
  }
}

export function segmentOverlayPlugin(getSegments: () => { start_s: number; end_s: number; label: string; color?: string }[], getMarkers: () => number[] = () => []): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const ctx = u.ctx
        const top = u.bbox.top
        const height = u.bbox.height
        ctx.save()
        for (const segment of getSegments()) {
          const x0 = u.valToPos(segment.start_s, 'x', true)
          const x1 = u.valToPos(segment.end_s, 'x', true)
          ctx.fillStyle = segment.color ?? 'rgba(59, 130, 246, 0.12)'
          ctx.fillRect(x0, top, Math.max(1, x1 - x0), height)
          ctx.fillStyle = cssVar('--foreground', '#111')
          ctx.globalAlpha = 0.75
          ctx.font = `${Math.round(11 * devicePixelRatio)}px "Segoe UI", sans-serif`
          ctx.fillText(segment.label, x0 + 4 * devicePixelRatio, top + 14 * devicePixelRatio)
          ctx.globalAlpha = 1
        }
        ctx.strokeStyle = cssVar('--destructive', '#dc2626')
        ctx.lineWidth = 1 * devicePixelRatio
        ctx.setLineDash([4 * devicePixelRatio, 3 * devicePixelRatio])
        for (const marker of getMarkers()) {
          const x = u.valToPos(marker, 'x', true)
          ctx.beginPath()
          ctx.moveTo(x, top)
          ctx.lineTo(x, top + height)
          ctx.stroke()
        }
        ctx.restore()
      },
    },
  }
}
