import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Copy, FlaskConical, MousePointer2, Plus, Shield, ShieldOff, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Empty, Field, KeyValue, Notice, NumberInput, Section } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { SensorSelect, SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge, ToneBadge } from '@/components/common/StatusBadge'
import { ActionEditor, defaultAction } from '@/components/control/ActionEditor'
import { ArmDialog } from '@/components/control/ArmDialog'
import { useEmergencyStop } from '@/components/layout/EmergencyStop'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState, useWorkspaceIsDemo } from '@/hooks/useAppState'
import { useTopicState } from '@/hooks/useTopic'
import { api } from '@/services/api'
import { dateTime, num, timeOfDay } from '@/lib/format'
import type { CursorState, GestureAction, Label, MappingProfile } from '@/types/api'
import { OutcomeBadge } from './DashboardPage'

function MappingRow({ profile, label, allowlist, onChanged }: { profile: MappingProfile; label: Label; allowlist: Awaited<ReturnType<typeof api.mappings.allowlist>> | null; onChanged: () => void }) {
  const existing = profile.mappings.find((m) => m.label_id === label.label_id)
  const [action, setAction] = useState<GestureAction>(existing?.action ?? defaultAction('key'))
  const [enabled, setEnabled] = useState(existing?.enabled ?? false)
  const { run } = useAction()
  useEffect(() => {
    setAction(existing?.action ?? defaultAction('key'))
    setEnabled(existing?.enabled ?? false)
  }, [existing?.mapping_id, JSON.stringify(existing?.action), existing?.enabled])
  const dirty = !existing || JSON.stringify(existing.action) !== JSON.stringify(action) || existing.enabled !== enabled
  const readOnly = profile.read_only
  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{label.display_name}</div>
        <div className="font-mono text-xs text-muted-foreground">{label.label_id}{!label.enabled ? ' · label disabled' : ''}</div>
      </TableCell>
      <TableCell><ActionEditor value={action} onChange={setAction} allowlist={allowlist} disabled={readOnly} /></TableCell>
      <TableCell><Switch checked={enabled} onCheckedChange={setEnabled} disabled={readOnly} aria-label="Enabled" /></TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button size="xs" variant="outline" onClick={() => run('sim', () => api.mappings.simulate({ action }), (r) => `${r.description} — simulation only, nothing was sent`)}><FlaskConical /> Test</Button>
          {!readOnly ? (
            <>
              <Button size="xs" disabled={!dirty} onClick={() => run('save', () => api.mappings.upsert(profile.profile_id, label.label_id, action, enabled), 'Mapping saved').then(onChanged)}>Save</Button>
              {existing ? <Button size="icon-xs" variant="ghost" aria-label="Remove mapping" onClick={() => run('rm', () => api.mappings.remove(profile.profile_id, label.label_id), 'Mapping removed').then(onChanged)}><Trash2 /></Button> : null}
            </>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  )
}

function CursorCard() {
  const { control } = useAppState()
  const cursorLive = useTopicState<CursorState | null>('cursor', null, 'cursor')
  const initial = useAsync(() => api.advanced.cursor(), [], 5000)
  const cursor = cursorLive ?? initial.data ?? null
  const [sensorId, setSensorId] = useState<string | null>(null)
  const [cfg, setCfg] = useState<CursorState['settings'] | null>(null)
  const { run, pending } = useAction()
  useEffect(() => {
    if (cursor && !cfg) setCfg(cursor.settings)
    if (cursor?.calibrated_sensor_id && !sensorId) setSensorId(cursor.calibrated_sensor_id)
  }, [cursor])
  if (!cursor || !cfg) return null
  return (
    <Section title={<span className="flex items-center gap-2"><MousePointer2 className="size-4" /> Cursor mode <ToneBadge tone="warning">unverified on hardware</ToneBadge></span>} description="Gyro rate → cursor velocity (v = k·ω) with stillness bias calibration, dead zone and a speed cap. Every move passes the same safety gate.">
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
          <Field label="Sensor"><SensorSelect value={sensorId} onChange={setSensorId} onlyStreaming /></Field>
          <Button variant="outline" disabled={!sensorId || pending === 'cal'} onClick={() => sensorId && run('cal', () => api.advanced.calibrateCursor(sensorId, 2), (r) => `Calibrated: suggested dead zone ${num(r.suggested_dead_zone_dps, 1)} °/s`).then(() => void initial.reload())}>Calibrate (hold still 2 s)</Button>
          {cursor.active ? (
            <Button onClick={() => run('stop', () => api.advanced.stopCursor(), 'Cursor mode off')}>Stop cursor</Button>
          ) : (
            <Button disabled={!sensorId || !control?.armed || cursor.calibrated_sensor_id !== sensorId} onClick={() => sensorId && run('start', () => api.advanced.startCursor(sensorId), 'Cursor mode on')}>Start cursor</Button>
          )}
        </div>
        <KeyValue items={[
          ['Calibrated', cursor.calibrated ? `${cursor.calibrated_sensor_id} at ${dateTime(cursor.calibrated_at)}` : 'not yet'],
          ['Bias (°/s)', Object.entries(cursor.settings.bias_dps).map(([k, v]) => `${k} ${num(v, 2)}`).join(' · ')],
          ['State', cursor.active ? `on · ${cursor.moves} moves` : cursor.message],
          ['Last velocity', `${num(cursor.last_velocity_px_s[0], 0)}, ${num(cursor.last_velocity_px_s[1], 0)} px/s`],
        ]} />
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="X axis"><SimpleSelect value={cfg.x_axis} onChange={(v) => setCfg({ ...cfg, x_axis: v })} options={['gx', 'gy', 'gz'].map((a) => ({ value: a as 'gx', label: a }))} /></Field>
          <Field label="Y axis"><SimpleSelect value={cfg.y_axis} onChange={(v) => setCfg({ ...cfg, y_axis: v })} options={['gx', 'gy', 'gz'].map((a) => ({ value: a as 'gx', label: a }))} /></Field>
          <Field label="Gain (px per °)"><NumberInput value={cfg.gain_px_per_deg} onChange={(v) => setCfg({ ...cfg, gain_px_per_deg: v })} min={0.1} max={100} step={0.5} /></Field>
          <Field label="Dead zone (°/s)"><NumberInput value={cfg.dead_zone_dps} onChange={(v) => setCfg({ ...cfg, dead_zone_dps: v })} min={0} max={200} step={0.5} /></Field>
          <Field label="Max speed (px/s)"><NumberInput value={cfg.max_speed_px_s} onChange={(v) => setCfg({ ...cfg, max_speed_px_s: v })} min={10} max={10000} step={50} /></Field>
          <label className="flex items-end gap-2 pb-2 text-sm"><Switch checked={cfg.invert_x} onCheckedChange={(v) => setCfg({ ...cfg, invert_x: v })} /> Invert X</label>
          <label className="flex items-end gap-2 pb-2 text-sm"><Switch checked={cfg.invert_y} onCheckedChange={(v) => setCfg({ ...cfg, invert_y: v })} /> Invert Y</label>
          <div className="flex items-end"><Button variant="outline" onClick={() => run('cfg', () => api.settings.patch({ cursor: { x_axis: cfg.x_axis, y_axis: cfg.y_axis, invert_x: cfg.invert_x, invert_y: cfg.invert_y, gain_px_per_deg: cfg.gain_px_per_deg, dead_zone_dps: cfg.dead_zone_dps, max_speed_px_s: cfg.max_speed_px_s } }), 'Cursor settings saved')}>Save cursor settings</Button></div>
        </div>
        {!control?.armed ? <p className="text-xs text-muted-foreground">Arm PC control first. Cursor mode stops automatically on disarm, Emergency Stop, sensor loss or stall.</p> : null}
      </div>
    </Section>
  )
}

function AirwritingCard() {
  const models = useAsync(() => api.models.list(), [])
  const airwriting = (models.data ?? []).filter((m) => m.feature_version === 'airwriting-dtw-v1')
  const [modelId, setModelId] = useState<string | null>(null)
  const [sensorId, setSensorId] = useState<string | null>(null)
  const [result, setResult] = useState<{ label: string; distance: number; ranking: { label: string; distance: number }[] } | null>(null)
  const { run } = useAction()
  return (
    <Section title={<span className="flex items-center gap-2">Air-writing <ToneBadge tone="warning">experimental</ToneBadge></span>} description="1-nearest-neighbour DTW over gyro sequences. Train with the airwriting-dtw-v1 pipeline on trials labelled per character (e.g. char_a).">
      {airwriting.length ? (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <Field label="Model"><SimpleSelect value={modelId} onChange={setModelId} options={airwriting.map((m) => ({ value: m.model_id, label: m.name }))} /></Field>
            <Field label="Sensor"><SensorSelect value={sensorId} onChange={setSensorId} onlyStreaming /></Field>
            <Button disabled={!modelId || !sensorId} onClick={() => run('aw', () => api.advanced.classifyAirwriting({ model_id: modelId as string, sensor_id: sensorId as string, seconds: 2 })).then((r) => r && setResult(r))}>Classify last 2 s</Button>
          </div>
          {result ? <p className="text-sm">Best match <b className="font-mono">{result.label}</b> (DTW distance {num(result.distance, 3)}). Runner-up: {result.ranking.slice(1).map((r) => `${r.label} ${num(r.distance, 3)}`).join(', ') || '—'}</p> : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No air-writing model yet. Text entry is not mapped to keystrokes; this panel only classifies.</p>
      )}
    </Section>
  )
}

export function MappingsPage() {
  const { control, settings, clientId } = useAppState()
  const isDemo = useWorkspaceIsDemo()
  const profiles = useAsync(() => api.mappings.profiles(), [settings?.active_profile_id])
  const labels = useAsync(() => api.labels.list(), [isDemo])
  const allowlist = useAsync(() => api.mappings.allowlist(), [])
  const [selected, setSelected] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [armOpen, setArmOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<MappingProfile | null>(null)
  const { run } = useAction()
  const estop = useEmergencyStop()

  useEffect(() => {
    if (!selected && profiles.data?.length) setSelected(settings?.active_profile_id ?? profiles.data[0].profile_id)
  }, [profiles.data])

  const profile = profiles.data?.find((p) => p.profile_id === selected) ?? null
  const rows = useMemo(() => {
    const all = (labels.data ?? []).filter((l) => !l.is_idle)
    const mapped = new Set(profile?.mappings.map((m) => m.label_id))
    return all.filter((l) => l.enabled || mapped.has(l.label_id))
  }, [labels.data, profile])

  return (
    <>
      <PageHeader title="Command Mapping" description="Map recognised gestures to allowlisted keyboard and mouse actions. Nothing reaches Windows unless PC control is enabled in Settings and explicitly armed." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,20rem)_1fr]">
        <div className="space-y-5">
          <Section title="Profiles">
            <div className="space-y-3">
              <RadioGroup value={settings?.active_profile_id ?? ''} onValueChange={(v) => run('active', () => api.mappings.setActive(v), 'Active profile changed').then(() => void profiles.reload())}>
                {(profiles.data ?? []).map((p) => (
                  <div key={p.profile_id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${p.profile_id === selected ? 'border-primary/50 bg-primary/5' : 'border-border'}`}>
                    <RadioGroupItem value={p.profile_id} aria-label={`Activate ${p.name}`} />
                    <button className="min-w-0 flex-1 text-left" onClick={() => setSelected(p.profile_id)}>
                      <div className="truncate text-sm font-medium">{p.name}</div>
                      <div className="text-xs text-muted-foreground">{p.mappings.filter((m) => m.enabled).length} enabled · {p.read_only ? 'read-only' : 'editable'}{p.active ? ' · active' : ''}</div>
                    </button>
                  </div>
                ))}
              </RadioGroup>
              <div className="flex gap-2">
                <Input placeholder="New profile name" value={newName} onChange={(e) => setNewName(e.target.value)} />
                <Button size="icon" aria-label="Create profile" disabled={!newName.trim()} onClick={() => run('create', () => api.mappings.createProfile(newName.trim()), 'Profile created').then((p) => { setNewName(''); if (p) setSelected(p.profile_id); void profiles.reload() })}><Plus /></Button>
              </div>
            </div>
          </Section>

          <Section title="PC control" actions={isDemo ? <DemoBadge /> : null}>
            <div className="space-y-3">
              <KeyValue columns={1} items={[
                ['Allowed in Settings', control?.pc_control_enabled ? 'yes' : <Link className="text-primary hover:underline" to="/settings">no — enable in Settings</Link>],
                ['State', control?.estop_latched ? <span className="text-destructive">E-stop latched</span> : control?.armed ? <span className="font-semibold text-destructive">ARMED</span> : 'disarmed'],
                ['Actions', control?.simulated_actions ? 'simulated (Demo Mode)' : 'real keyboard/mouse'],
                ['Global E-stop hotkey', `${control?.global_hotkey.spec} (${control?.global_hotkey.status})`],
                ['Last disarm', control?.last_disarm_reason ?? '—'],
                ['This tab session', clientId ?? 'not connected'],
              ]} />
              <div className="flex flex-wrap gap-2">
                {control?.armed ? (
                  <Button variant="outline" onClick={() => run('disarm', () => api.control.disarm(), 'Disarmed')}><ShieldOff /> Disarm</Button>
                ) : (
                  <Button onClick={() => setArmOpen(true)} disabled={control?.estop_latched}><Shield /> Arm…</Button>
                )}
                <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={() => void estop()}>Emergency Stop</Button>
              </div>
            </div>
          </Section>
        </div>

        <div className="space-y-5">
          {profile ? (
            <Section
              title={profile.name}
              description={profile.description}
              actions={
                <>
                  <Button size="sm" variant="outline" onClick={() => run('dup', () => api.mappings.createProfile(`${profile.name} copy`, profile.profile_id), 'Copied — entries start disabled').then((p) => { if (p) setSelected(p.profile_id); void profiles.reload() })}><Copy /> Duplicate</Button>
                  {!profile.read_only ? <Button size="icon-sm" variant="ghost" aria-label="Delete profile" onClick={() => setDeleteTarget(profile)}><Trash2 /></Button> : null}
                </>
              }
            >
              {profile.read_only ? <Notice tone="info" title="Preserved read-only profile" className="mb-4">This is the exact mapping from src/control.py (swipe_left→Left, swipe_right→Right, flick_up→Space). Duplicate it to change anything.</Notice> : null}
              <Table>
                <TableHeader><TableRow><TableHead>Gesture</TableHead><TableHead>Action</TableHead><TableHead>Enabled</TableHead><TableHead /></TableRow></TableHeader>
                <TableBody>
                  {rows.map((label) => <MappingRow key={`${profile.profile_id}-${label.label_id}`} profile={profile} label={label} allowlist={allowlist.data ?? null} onChanged={() => void profiles.reload()} />)}
                </TableBody>
              </Table>
              <p className="mt-3 text-xs text-muted-foreground">Idle / No Gesture is never mappable. Allowed: single keys (arrows, space, enter, tab, esc, page/home/end, letters, digits, F1–F12, media), Ctrl/Alt/Shift shortcuts, clicks, double-click and scrolling. Blocked: the Windows key, Alt+F4, Ctrl+Shift+Esc, typing text, launching programs or commands.</p>
            </Section>
          ) : (
            <Empty title="No profile selected" />
          )}

          <Section title="Recent action outcomes">
            {control?.history.length ? (
              <Table>
                <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Gesture</TableHead><TableHead>Action</TableHead><TableHead>Outcome</TableHead><TableHead>Reason</TableHead></TableRow></TableHeader>
                <TableBody>
                  {[...control.history].reverse().slice(0, 30).map((h, i) => (
                    <TableRow key={`${h.at}-${i}`}>
                      <TableCell className="tabular text-xs text-muted-foreground">{timeOfDay(h.at)}</TableCell>
                      <TableCell className="font-mono text-xs">{h.label}</TableCell>
                      <TableCell>{h.description}</TableCell>
                      <TableCell><OutcomeBadge outcome={h.outcome} /></TableCell>
                      <TableCell className="text-xs text-muted-foreground">{h.reason}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty title="No actions yet" />
            )}
          </Section>
          <CursorCard />
          <AirwritingCard />
        </div>
      </div>
      <ArmDialog open={armOpen} onOpenChange={setArmOpen} />
      <ConfirmDialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)} title={`Delete profile ${deleteTarget?.name}?`} destructive confirmLabel="Delete" onConfirm={() => deleteTarget && run('delp', () => api.mappings.deleteProfile(deleteTarget.profile_id), 'Profile deleted').then(() => { setSelected(null); void profiles.reload(); toast.info('If it was active, no profile is active now.') })} />
    </>
  )
}
