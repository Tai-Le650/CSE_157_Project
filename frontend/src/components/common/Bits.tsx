import { useId, type ReactNode } from 'react'
import { AlertTriangle, Info, Inbox } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export function Section({ title, description, actions, children, className, contentClassName }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; contentClassName?: string }) {
  return (
    <Card className={cn('gap-4 rounded-xl border-border/80 shadow-sm', className)}>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="min-w-0 space-y-1">
          <CardTitle className="text-base font-semibold">{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </CardHeader>
      <CardContent className={contentClassName}>{children}</CardContent>
    </Card>
  )
}

export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn('rounded-lg border border-border/70 bg-muted/30 px-3 py-2.5', className)}>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="tabular mt-0.5 truncate text-lg font-semibold">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

export function KeyValue({ items, columns = 2 }: { items: [ReactNode, ReactNode][]; columns?: 1 | 2 | 3 }) {
  const grid = columns === 1 ? 'grid-cols-1' : columns === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2'
  return (
    <dl className={cn('grid grid-cols-1 gap-x-6 gap-y-2 text-sm', grid)}>
      {items.map(([key, value], i) => (
        <div key={i} className="flex min-w-0 items-baseline justify-between gap-3 border-b border-dashed border-border/60 pb-1.5">
          <dt className="shrink-0 text-muted-foreground">{key}</dt>
          <dd className="tabular min-w-0 truncate text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Empty({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <div className="mb-3 text-muted-foreground">{icon ?? <Inbox className="size-6" />}</div>
      <div className="font-medium">{title}</div>
      {description ? <div className="mt-1 max-w-md text-sm text-muted-foreground">{description}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export function Notice({ tone = 'info', title, children, className }: { tone?: 'info' | 'warning' | 'danger'; title?: ReactNode; children?: ReactNode; className?: string }) {
  const styles = {
    info: 'border-info/30 bg-info/5 text-foreground [&>svg]:text-info',
    warning: 'border-warning/50 bg-warning/10 text-foreground [&>svg]:text-warning-foreground dark:[&>svg]:text-warning',
    danger: 'border-destructive/40 bg-destructive/5 text-foreground [&>svg]:text-destructive',
  }
  return (
    <Alert className={cn(styles[tone], className)}>
      {tone === 'info' ? <Info /> : <AlertTriangle />}
      {title ? <AlertTitle>{title}</AlertTitle> : null}
      {children ? <AlertDescription className="text-muted-foreground">{children}</AlertDescription> : null}
    </Alert>
  )
}

export function Field({ label, hint, htmlFor, children, className }: { label: ReactNode; hint?: ReactNode; htmlFor?: string; children: ReactNode; className?: string }) {
  const id = useId()
  return (
    <div role="group" aria-labelledby={`${id}-label`} aria-describedby={hint ? `${id}-hint` : undefined} className={cn('space-y-1.5', className)}>
      <Label id={`${id}-label`} htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </Label>
      {children}
      {hint ? <p id={`${id}-hint`} className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export function NumberInput({ value, onChange, min, max, step, id, disabled, className }: { value: number | null | undefined; onChange: (value: number) => void; min?: number; max?: number; step?: number; id?: string; disabled?: boolean; className?: string }) {
  return (
    <Input
      id={id}
      type="number"
      inputMode="decimal"
      className={cn('tabular', className)}
      value={value ?? ''}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onChange={(event) => {
        const next = event.target.valueAsNumber
        if (!Number.isNaN(next)) onChange(next)
      }}
    />
  )
}
