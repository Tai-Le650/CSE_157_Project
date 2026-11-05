import { FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { SensorStatus, ValidationState } from '@/types/api'

const SENSOR_STYLE: Record<SensorStatus, { label: string; dot: string; tone: string }> = {
  streaming: { label: 'Streaming', dot: 'bg-success', tone: 'border-success/30 bg-success/10 text-success' },
  waiting_for_data: { label: 'Waiting for data', dot: 'bg-warning', tone: 'border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning' },
  connecting: { label: 'Connecting', dot: 'bg-info', tone: 'border-info/30 bg-info/10 text-info' },
  stalled: { label: 'Stalled', dot: 'bg-warning', tone: 'border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning' },
  disconnected: { label: 'Disconnected', dot: 'bg-muted-foreground', tone: 'border-border bg-muted text-muted-foreground' },
  error: { label: 'Error', dot: 'bg-destructive', tone: 'border-destructive/30 bg-destructive/10 text-destructive' },
}

export function StatusDot({ status, className }: { status: SensorStatus; className?: string }) {
  const style = SENSOR_STYLE[status] ?? SENSOR_STYLE.disconnected
  return (
    <span className={cn('relative inline-flex size-2.5', className)} aria-hidden>
      {status === 'streaming' ? <span className={cn('absolute inline-flex size-full animate-ping rounded-full opacity-40', style.dot)} /> : null}
      <span className={cn('relative inline-flex size-2.5 rounded-full', style.dot)} />
    </span>
  )
}

export function SensorStatusBadge({ status }: { status: SensorStatus }) {
  const style = SENSOR_STYLE[status] ?? SENSOR_STYLE.disconnected
  return (
    <Badge variant="outline" className={cn('gap-1.5 font-medium', style.tone)}>
      <StatusDot status={status} />
      {style.label}
    </Badge>
  )
}

const VALIDATION_STYLE: Record<ValidationState, { label: string; tone: string }> = {
  valid: { label: 'Valid', tone: 'border-success/30 bg-success/10 text-success' },
  flagged: { label: 'Needs repair', tone: 'border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning' },
  invalid: { label: 'Invalid', tone: 'border-destructive/30 bg-destructive/10 text-destructive' },
}

export function ValidationBadge({ state }: { state: ValidationState }) {
  const style = VALIDATION_STYLE[state] ?? VALIDATION_STYLE.invalid
  return (
    <Badge variant="outline" className={cn('font-medium', style.tone)}>
      {style.label}
    </Badge>
  )
}

export function DemoBadge({ className }: { className?: string }) {
  return (
    <Badge variant="outline" className={cn('gap-1 border-violet-400/40 bg-violet-500/10 font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300', className)}>
      <FlaskConical className="size-3" />
      Demo
    </Badge>
  )
}

export function ToneBadge({ tone, children, className }: { tone: 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'primary'; children: React.ReactNode; className?: string }) {
  const tones = {
    success: 'border-success/30 bg-success/10 text-success',
    warning: 'border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning',
    danger: 'border-destructive/30 bg-destructive/10 text-destructive',
    info: 'border-info/30 bg-info/10 text-info',
    muted: 'border-border bg-muted text-muted-foreground',
    primary: 'border-primary/30 bg-primary/10 text-primary',
  }
  return (
    <Badge variant="outline" className={cn('font-medium', tones[tone], className)}>
      {children}
    </Badge>
  )
}
