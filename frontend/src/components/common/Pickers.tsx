import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAppState } from '@/hooks/useAppState'
import { cn } from '@/lib/utils'
import type { Label, SensorState } from '@/types/api'
import { StatusDot } from './StatusBadge'

const NONE = '__none__'

export function SensorSelect({ value, onChange, onlyStreaming = false, allowNone = false, placeholder = 'Choose a sensor', className }: { value: string | null | undefined; onChange: (value: string | null) => void; onlyStreaming?: boolean; allowNone?: boolean; placeholder?: string; className?: string }) {
  const { sensors } = useAppState()
  const options = onlyStreaming ? sensors.filter((s) => s.status === 'streaming') : sensors
  return (
    <Select value={value ?? (allowNone ? NONE : undefined)} onValueChange={(v) => onChange(v === NONE ? null : v)}>
      <SelectTrigger className={cn('w-full', className)}>
        <SelectValue placeholder={options.length ? placeholder : 'No sensors connected'} />
      </SelectTrigger>
      <SelectContent>
        {allowNone ? <SelectItem value={NONE}>None</SelectItem> : null}
        {options.map((s) => (
          <SelectItem key={s.sensor_id} value={s.sensor_id}>
            <span className="flex items-center gap-2">
              <StatusDot status={s.status} />
              {s.sensor_id}
              <span className="text-xs text-muted-foreground">{s.hand !== 'unassigned' ? `· ${s.hand}` : ''}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function SensorChecklist({ value, onChange, sensors }: { value: string[]; onChange: (value: string[]) => void; sensors: SensorState[] }) {
  if (!sensors.length) return <p className="text-sm text-muted-foreground">No streaming sensors. Connect one on the Sensor Connections page.</p>
  return (
    <div className="flex flex-wrap gap-2">
      {sensors.map((s) => {
        const checked = value.includes(s.sensor_id)
        return (
          <label key={s.sensor_id} className={cn('flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors', checked ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted/50')}>
            <Checkbox checked={checked} onCheckedChange={(next) => onChange(next ? [...value, s.sensor_id] : value.filter((id) => id !== s.sensor_id))} />
            <StatusDot status={s.status} />
            <span className="font-medium">{s.sensor_id}</span>
            {s.hand !== 'unassigned' ? <span className="text-xs capitalize text-muted-foreground">{s.hand}</span> : null}
          </label>
        )
      })}
    </div>
  )
}

export function LabelSelect({ labels, value, onChange, includeDisabled = false, allowNone = false, noneLabel = 'No label', placeholder = 'Choose a label', className }: { labels: Label[]; value: string | null | undefined; onChange: (value: string | null) => void; includeDisabled?: boolean; allowNone?: boolean; noneLabel?: string; placeholder?: string; className?: string }) {
  const options = includeDisabled ? labels : labels.filter((l) => l.enabled)
  return (
    <Select value={value ?? (allowNone ? NONE : undefined)} onValueChange={(v) => onChange(v === NONE ? null : v)}>
      <SelectTrigger className={cn('w-full', className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {allowNone ? <SelectItem value={NONE}>{noneLabel}</SelectItem> : null}
        {options.map((l) => (
          <SelectItem key={l.label_id} value={l.label_id}>
            <span className="flex items-center gap-2">
              {l.display_name}
              <span className="font-mono text-xs text-muted-foreground">{l.label_id}</span>
              {!l.enabled ? <span className="text-xs text-muted-foreground">(disabled)</span> : null}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function SimpleSelect<T extends string>({ value, onChange, options, className, placeholder, disabled }: { value: T | null | undefined; onChange: (value: T) => void; options: { value: T; label: string }[]; className?: string; placeholder?: string; disabled?: boolean }) {
  return (
    <Select value={value ?? undefined} onValueChange={(v) => onChange(v as T)} disabled={disabled}>
      <SelectTrigger className={cn('w-full', className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
