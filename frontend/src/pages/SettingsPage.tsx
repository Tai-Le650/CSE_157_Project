import { useEffect, useState } from 'react'
import { AlertTriangle, FolderCog } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { Field, KeyValue, Notice, NumberInput, Section } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { SimpleSelect } from '@/components/common/Pickers'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState } from '@/hooks/useAppState'
import { useTheme } from '@/hooks/useTheme'
import { api } from '@/services/api'
import type { AppSettings } from '@/types/api'

type Draft = Omit<AppSettings, 'cursor' | 'sound'>

export function SettingsPage() {
  const { settings, status, control } = useAppState()
  const { setLocalTheme } = useTheme()
  const storage = useAsync(() => api.settings.storage(), [])
  const capabilities = useAsync(() => api.advanced.capabilities(), [settings?.demo_mode])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [dirty, setDirty] = useState<Set<keyof Draft>>(new Set())
  const [demoConfirm, setDemoConfirm] = useState<boolean | null>(null)
  const [pcConfirm, setPcConfirm] = useState(false)
  const [dataDir, setDataDir] = useState('')
  const { run } = useAction()

  useEffect(() => {
    if (!settings) return
    setDraft((current) => {
      if (!current) return settings
      const next = { ...current }
      for (const key of Object.keys(settings) as (keyof Draft)[]) {
        if (!dirty.has(key) && key in next) (next as Record<string, unknown>)[key] = settings[key]
      }
      return next
    })
  }, [settings])

  if (!settings || !draft) return <PageHeader title="Settings" description="Loading…" />

  const save = (section: keyof Draft, label: string) => {
    const payload = section === 'control' ? { ...draft.control, pc_control_enabled: settings.control.pc_control_enabled } : draft[section]
    return run(section, () => api.settings.patch({ [section]: payload }), `${label} saved`).then(() => setDirty((d) => { const n = new Set(d); n.delete(section); return n }))
  }
  const set = <K extends keyof Draft>(section: K, value: Partial<Draft[K]>) => {
    setDirty((d) => new Set(d).add(section))
    setDraft({ ...draft, [section]: { ...(draft[section] as object), ...value } as Draft[K] })
  }
  const soundAvailable = capabilities.data?.sound_activation?.available ?? false

  return (
    <>
      <PageHeader title="Settings" description="Persisted in data/app.db. Settings that the hardware or firmware decide (such as the IMU sample rate) are measured, not configurable here." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Section title="Appearance">
          <RadioGroup value={settings.theme} onValueChange={(v) => { setLocalTheme(v as AppSettings['theme']); void run('theme', () => api.settings.patch({ theme: v })) }} className="flex gap-6">
            {(['light', 'dark', 'system'] as const).map((t) => (
              <label key={t} className="flex items-center gap-2 text-sm capitalize"><RadioGroupItem value={t} /> {t}</label>
            ))}
          </RadioGroup>
        </Section>

        <Section title="Mode">
          <div className="space-y-3">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span><b>Demo Mode</b> — simulated sensors only; every OS action is simulated; data and models are kept in a separate demo workspace</span>
              <Switch checked={settings.demo_mode} onCheckedChange={(v) => setDemoConfirm(v)} />
            </label>
            <p className="text-xs text-muted-foreground">Switching disconnects all sensors, stops recognition and disarms PC control. It is refused while recording or training.</p>
          </div>
        </Section>

        <Section title="Acquisition" actions={<Button size="sm" variant="outline" onClick={() => save('acquisition', 'Acquisition')}>Save</Button>}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Default baud rate" hint="Must match the firmware (115200)"><NumberInput value={draft.acquisition.default_baud} onChange={(v) => set('acquisition', { default_baud: Math.round(v) })} min={300} max={4000000} /></Field>
            <Field label="Stall timeout (s)"><NumberInput value={draft.acquisition.stall_timeout_s} onChange={(v) => set('acquisition', { stall_timeout_s: v })} min={0.3} max={30} step={0.1} /></Field>
            <Field label="Auto-reconnect" hint="Never re-arms PC control"><div className="flex h-9 items-center"><Switch checked={draft.acquisition.auto_reconnect} onCheckedChange={(v) => set('acquisition', { auto_reconnect: v })} /></div></Field>
          </div>
        </Section>

        <Section title="Recording defaults" actions={<Button size="sm" variant="outline" onClick={() => save('recording', 'Recording defaults')}>Save</Button>}>
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="Trial (s)"><NumberInput value={draft.recording.trial_duration_s} onChange={(v) => set('recording', { trial_duration_s: v })} min={0.3} max={30} step={0.1} /></Field>
            <Field label="Countdown (s)"><NumberInput value={draft.recording.countdown_s} onChange={(v) => set('recording', { countdown_s: v })} min={0} max={10} step={0.5} /></Field>
            <Field label="Trials"><NumberInput value={draft.recording.trials_per_set} onChange={(v) => set('recording', { trials_per_set: Math.round(v) })} min={1} max={200} /></Field>
            <Field label="Pause (s)"><NumberInput value={draft.recording.pause_between_s} onChange={(v) => set('recording', { pause_between_s: v })} min={0} max={30} step={0.5} /></Field>
          </div>
        </Section>

        <Section title="Display" actions={<Button size="sm" variant="outline" onClick={() => save('display', 'Display')}>Save</Button>}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Default window (s)"><NumberInput value={draft.display.window_s} onChange={(v) => set('display', { window_s: v })} min={1} max={60} /></Field>
            <Field label="Acceleration unit"><SimpleSelect value={draft.display.accel_unit} onChange={(v) => set('display', { accel_unit: v })} options={[{ value: 'g', label: 'g' }, { value: 'm/s2', label: 'm/s² (×9.80665)' }]} /></Field>
            <Field label="Angular-rate unit"><SimpleSelect value={draft.display.gyro_unit} onChange={(v) => set('display', { gyro_unit: v })} options={[{ value: 'deg/s', label: '°/s' }, { value: 'rad/s', label: 'rad/s (×π/180)' }]} /></Field>
          </div>
        </Section>

        <Section title="Inference defaults" actions={<Button size="sm" variant="outline" onClick={() => save('inference', 'Inference defaults')}>Save</Button>}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Hop (s)"><NumberInput value={draft.inference.hop_s} onChange={(v) => set('inference', { hop_s: v })} min={0.02} max={2} step={0.05} /></Field>
            <Field label="Threshold"><NumberInput value={draft.inference.threshold} onChange={(v) => set('inference', { threshold: v })} min={0.05} max={1} step={0.01} /></Field>
            <Field label="Cooldown (s)"><NumberInput value={draft.inference.cooldown_s} onChange={(v) => set('inference', { cooldown_s: v })} min={0} max={30} step={0.1} /></Field>
            <Field label="Smoothing (windows)"><NumberInput value={draft.inference.smoothing_k} onChange={(v) => set('inference', { smoothing_k: Math.round(v) })} min={1} max={20} /></Field>
            <Field label="Debounce (windows)"><NumberInput value={draft.inference.debounce_n} onChange={(v) => set('inference', { debounce_n: Math.round(v) })} min={1} max={20} /></Field>
            <Field label="Idle re-arm"><div className="flex h-9 items-center"><Switch checked={draft.inference.require_idle_rearm} onCheckedChange={(v) => set('inference', { require_idle_rearm: v })} /></div></Field>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">The window length is fixed by each model when it is trained.</p>
        </Section>

        <Section title={<span className="flex items-center gap-2"><AlertTriangle className="size-4 text-destructive" /> PC control</span>} actions={<Button size="sm" variant="outline" onClick={() => save('control', 'PC control settings')}>Save</Button>}>
          <div className="space-y-4">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span><b>Allow PC control</b> — master switch; when off, arming is impossible (default off)</span>
              <Switch checked={settings.control.pc_control_enabled} onCheckedChange={(v) => (v ? setPcConfirm(true) : void run('pc', () => api.settings.patch({ control: { pc_control_enabled: false } }), 'PC control disabled'))} />
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Heartbeat timeout (s)" hint="Disarm if this tab stops responding"><NumberInput value={draft.control.heartbeat_timeout_s} onChange={(v) => set('control', { heartbeat_timeout_s: v })} min={1} max={30} /></Field>
              <Field label="Auto-disarm after idle (min)" hint="0 = never"><NumberInput value={draft.control.auto_disarm_idle_minutes} onChange={(v) => set('control', { auto_disarm_idle_minutes: v })} min={0} max={240} /></Field>
              <Field label="Global E-stop hotkey" hint="Registered only while armed"><Input value={draft.control.global_estop_hotkey} onChange={(e) => set('control', { global_estop_hotkey: e.target.value })} /></Field>
            </div>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Enable the system-wide E-stop hotkey (status: {control?.global_hotkey.status})</span>
              <Switch checked={draft.control.global_hotkey_enabled} onCheckedChange={(v) => set('control', { global_hotkey_enabled: v })} />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Require sound activation before actions {soundAvailable ? '' : '(unavailable: no microphone stream)'}</span>
              <Switch checked={draft.control.sound_activation_required} disabled={!soundAvailable && !draft.control.sound_activation_required} onCheckedChange={(v) => set('control', { sound_activation_required: v })} />
            </label>
          </div>
        </Section>

        <Section title={<span className="flex items-center gap-2"><FolderCog className="size-4" /> Storage</span>}>
          <div className="space-y-3">
            <KeyValue columns={1} items={[
              ['Data directory', storage.data?.data_dir ?? status?.data_dir ?? '—'],
              ['Models directory', storage.data?.models_dir ?? '—'],
              ['Legacy CLI data', storage.data?.cli_data_dir ?? '—'],
            ]} />
            {storage.data?.restart_required ? <Notice tone="warning" title="Restart required">New data directory {storage.data.pending_data_dir ?? '(default)'} takes effect after the backend restarts.</Notice> : null}
            <div className="flex gap-2">
              <Input placeholder="Absolute folder, e.g. C:\GestureData (blank = default)" value={dataDir} onChange={(e) => setDataDir(e.target.value)} />
              <Button variant="outline" onClick={() => run('storage', () => api.settings.setStorage(dataDir.trim() || null), 'Saved; restart the backend to apply').then(() => void storage.reload())}>Set</Button>
            </div>
            <p className="text-xs text-muted-foreground">The folder holds app.db, raw recordings, derivatives and exports. Keeping it inside OneDrive works, but OneDrive may briefly lock files while syncing.</p>
          </div>
        </Section>

        <Section title="About">
          <KeyValue columns={1} items={[
            ['Application', `${status?.app ?? 'Gesture-to-PC'} ${status?.version ?? ''}`],
            ['Backend address', '127.0.0.1 only (not reachable from other computers)'],
            ['Selected model', settings.selected_model_id ?? '—'],
            ['Selected sensor', settings.selected_sensor_id ?? '—'],
            ['API documentation', <a className="text-primary hover:underline" href="/docs" target="_blank" rel="noreferrer">/docs (OpenAPI)</a>],
          ]} />
        </Section>
      </div>
      <ConfirmDialog
        open={demoConfirm !== null}
        onOpenChange={(open) => !open && setDemoConfirm(null)}
        title={demoConfirm ? 'Turn Demo Mode on?' : 'Turn Demo Mode off?'}
        description={demoConfirm ? 'All sensors disconnect and PC control is disarmed. Only simulated sensors can connect; all actions are simulated; demo data is stored separately.' : 'All simulated sensors disconnect. Real COM ports and real PC control become available again.'}
        confirmLabel={demoConfirm ? 'Enable Demo Mode' : 'Disable Demo Mode'}
        onConfirm={() => demoConfirm !== null && run('demo', () => api.settings.setDemoMode(demoConfirm), demoConfirm ? 'Demo Mode on' : 'Demo Mode off')}
      />
      <ConfirmDialog
        open={pcConfirm}
        onOpenChange={setPcConfirm}
        title="Allow PC control?"
        description="This only allows arming; nothing happens until you explicitly arm PC control with recognition running. Armed gestures press keys and click in the focused window."
        destructive
        confirmLabel="Allow PC control"
        onConfirm={() => run('pc', () => api.settings.patch({ control: { pc_control_enabled: true } }), 'PC control allowed (still disarmed)')}
      />
    </>
  )
}
