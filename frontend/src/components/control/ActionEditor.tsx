import { Toggle } from '@/components/ui/toggle'
import { NumberInput } from '@/components/common/Bits'
import { SimpleSelect } from '@/components/common/Pickers'
import type { Allowlist, GestureAction } from '@/types/api'

const TYPE_OPTIONS: { value: GestureAction['type']; label: string }[] = [
  { value: 'key', label: 'Key' },
  { value: 'hotkey', label: 'Shortcut' },
  { value: 'click', label: 'Click' },
  { value: 'double_click', label: 'Double-click' },
  { value: 'scroll', label: 'Scroll' },
]

const KEY_NAMES: Record<string, string> = {
  left: '← Left', right: '→ Right', up: '↑ Up', down: '↓ Down', space: 'Space', enter: 'Enter', tab: 'Tab', esc: 'Esc',
  pageup: 'Page Up', pagedown: 'Page Down', home: 'Home', end: 'End', volumeup: 'Volume Up', volumedown: 'Volume Down',
  volumemute: 'Mute', playpause: 'Play/Pause', nexttrack: 'Next track', prevtrack: 'Previous track',
}

export function defaultAction(type: GestureAction['type']): GestureAction {
  switch (type) {
    case 'key':
      return { type: 'key', key: 'right' }
    case 'hotkey':
      return { type: 'hotkey', modifiers: ['ctrl'], key: 'tab' }
    case 'click':
      return { type: 'click', button: 'left' }
    case 'double_click':
      return { type: 'double_click', button: 'left' }
    case 'scroll':
      return { type: 'scroll', notches: -3 }
  }
}

export function ActionEditor({ value, onChange, allowlist, disabled }: { value: GestureAction; onChange: (value: GestureAction) => void; allowlist: Allowlist | null; disabled?: boolean }) {
  const keys = (allowlist?.keys ?? Object.keys(KEY_NAMES)).map((k) => ({ value: k, label: KEY_NAMES[k] ?? k.toUpperCase() }))
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SimpleSelect className="w-36" value={value.type} onChange={(t) => onChange(defaultAction(t))} options={TYPE_OPTIONS} disabled={disabled} />
      {value.type === 'key' ? <SimpleSelect className="w-40" value={value.key} onChange={(key) => onChange({ ...value, key })} options={keys} disabled={disabled} /> : null}
      {value.type === 'hotkey' ? (
        <>
          {(allowlist?.modifiers ?? ['ctrl', 'alt', 'shift']).map((mod) => (
            <Toggle
              key={mod}
              size="sm"
              variant="outline"
              disabled={disabled}
              pressed={value.modifiers.includes(mod)}
              onPressedChange={(on) => {
                const next = on ? [...value.modifiers, mod] : value.modifiers.filter((m) => m !== mod)
                if (next.length) onChange({ ...value, modifiers: next })
              }}
              className="capitalize"
            >
              {mod}
            </Toggle>
          ))}
          <span className="text-muted-foreground">+</span>
          <SimpleSelect className="w-40" value={value.key} onChange={(key) => onChange({ ...value, key })} options={keys} disabled={disabled} />
        </>
      ) : null}
      {value.type === 'click' ? (
        <SimpleSelect className="w-32" value={value.button} onChange={(button) => onChange({ type: 'click', button })} options={[{ value: 'left', label: 'Left' }, { value: 'right', label: 'Right' }, { value: 'middle', label: 'Middle' }]} disabled={disabled} />
      ) : null}
      {value.type === 'scroll' ? (
        <div className="flex items-center gap-2 text-sm">
          <NumberInput className="w-20" value={value.notches} min={-20} max={20} step={1} disabled={disabled} onChange={(n) => onChange({ type: 'scroll', notches: Math.trunc(n) || -1 })} />
          <span className="text-muted-foreground">notches ({value.notches > 0 ? 'up' : 'down'})</span>
        </div>
      ) : null}
    </div>
  )
}
