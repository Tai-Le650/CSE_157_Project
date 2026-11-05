import { cn } from '@/lib/utils'
import { pct } from '@/lib/format'
import type { LabelDistribution } from '@/types/api'

export function ProbabilityBars({ probabilities, highlight, threshold }: { probabilities: Record<string, number>; highlight?: string | null; threshold?: number }) {
  const entries = Object.entries(probabilities).sort((a, b) => b[1] - a[1])
  return (
    <div className="space-y-2">
      {entries.map(([label, value]) => (
        <div key={label} className="grid grid-cols-[minmax(7rem,10rem)_1fr_3.5rem] items-center gap-3 text-sm">
          <span className={cn('truncate font-mono text-xs', label === highlight && 'font-semibold text-foreground')}>{label}</span>
          <div className="relative h-2.5 overflow-hidden rounded-full bg-muted">
            <div className={cn('h-full rounded-full transition-[width] duration-200', label === highlight ? 'bg-primary' : 'bg-primary/40')} style={{ width: `${Math.max(1, value * 100)}%` }} />
            {threshold !== undefined ? <div className="absolute top-0 h-full w-px bg-foreground/50" style={{ left: `${threshold * 100}%` }} title={`Threshold ${threshold}`} /> : null}
          </div>
          <span className="tabular text-right text-xs text-muted-foreground">{pct(value, 0)}</span>
        </div>
      ))}
    </div>
  )
}

export function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  const max = Math.max(1, ...matrix.flat())
  return (
    <div className="overflow-x-auto">
      <table className="tabular border-separate border-spacing-1 text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left font-medium text-muted-foreground">true ↓ / predicted →</th>
            {labels.map((label) => (
              <th key={label} className="px-2 py-1 text-center font-mono font-medium">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <th className="px-2 py-1 text-left font-mono font-medium">{labels[i]}</th>
              {row.map((value, j) => (
                <td
                  key={j}
                  className={cn('min-w-12 rounded-md px-2 py-1.5 text-center font-semibold', i === j ? 'text-foreground' : value ? 'text-destructive' : 'text-muted-foreground')}
                  style={{ background: `color-mix(in oklch, ${i === j ? 'var(--primary)' : 'var(--destructive)'} ${Math.round((value / max) * (i === j ? 45 : 35))}%, transparent)` }}
                >
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function DistributionBars({ distribution }: { distribution: Record<string, LabelDistribution> }) {
  const entries = Object.entries(distribution)
  const max = Math.max(1, ...entries.map(([, d]) => d.members))
  if (!entries.length) return <p className="text-sm text-muted-foreground">No members yet.</p>
  return (
    <div className="space-y-2">
      {entries.map(([label, d]) => (
        <div key={label} className="grid grid-cols-[minmax(7rem,10rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate font-mono text-xs">{label}</span>
          <div className="flex h-3 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary/80" style={{ width: `${(d.trials / max) * 100}%` }} title={`${d.trials} trial(s)`} />
            <div className="h-full bg-chart-2/80" style={{ width: `${(d.segments / max) * 100}%` }} title={`${d.segments} segment(s)`} />
          </div>
          <span className="tabular text-xs text-muted-foreground">
            {d.members} · {d.sessions || 0} session{d.sessions === 1 ? '' : 's'}
          </span>
        </div>
      ))}
      <div className="flex gap-4 pt-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary/80" /> trials</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-chart-2/80" /> segments</span>
      </div>
    </div>
  )
}
