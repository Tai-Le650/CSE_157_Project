import { useEffect, useRef, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { cssVar } from '@/lib/units'
import { cn } from '@/lib/utils'

type PlotlyModule = typeof import('plotly.js-cartesian-dist-min').default
let loader: Promise<PlotlyModule> | null = null

function loadPlotly(): Promise<PlotlyModule> {
  if (!loader) loader = import('plotly.js-cartesian-dist-min').then((m) => m.default)
  return loader
}

export function PlotlyChart({ data, layout, height = 280, className }: { data: Record<string, unknown>[]; layout?: Record<string, unknown>; height?: number; className?: string }) {
  const element = useRef<HTMLDivElement>(null)
  const { resolvedTheme } = useTheme()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const node = element.current
    if (!node) return
    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !element.current) return
        const fg = cssVar('--muted-foreground', '#667085')
        const grid = cssVar('--plot-grid', '#e5e7eb')
        const base = {
          height,
          margin: { l: 56, r: 16, t: 12, b: 44 },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          font: { family: '"Segoe UI", system-ui, sans-serif', size: 11, color: fg },
          xaxis: { gridcolor: grid, zerolinecolor: grid, ...((layout?.xaxis as object) ?? {}) },
          yaxis: { gridcolor: grid, zerolinecolor: grid, ...((layout?.yaxis as object) ?? {}) },
          showlegend: false,
        }
        void Plotly.react(element.current, data, { ...base, ...layout, xaxis: base.xaxis, yaxis: base.yaxis }, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] })
      })
      .catch((err: unknown) => setError(String(err)))
    return () => {
      cancelled = true
    }
  }, [data, layout, height, resolvedTheme])

  useEffect(() => {
    const node = element.current
    return () => {
      if (node && loader) void loader.then((Plotly) => Plotly.purge(node))
    }
  }, [])

  if (error) return <div className="text-sm text-destructive">Chart failed to load: {error}</div>
  return <div ref={element} className={cn('w-full min-w-0', className)} style={{ height }} />
}
