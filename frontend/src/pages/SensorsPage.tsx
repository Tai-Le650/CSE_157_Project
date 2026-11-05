import { useEffect, useMemo, useState } from 'react'
import { Cable, Plug, PlugZap, RefreshCw, Shuffle, Trash2, Unplug } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Empty, Field, KeyValue, Notice, NumberInput, Section, Stat } from '@/components/common/Bits'
import { PageHeader } from '@/components/common/PageHeader'
import { SensorSelect, SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge, SensorStatusBadge, ToneBadge } from '@/components/common/StatusBadge'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState, useWorkspaceIsDemo } from '@/hooks/useAppState'
import { useTopicState } from '@/hooks/useTopic'
import { api } from '@/services/api'
import { count, dateTime, hz, ms, num, seconds } from '@/lib/format'
import type { Hand, SensorState, SyncState } from '@/types/api'

const HANDS: { value: Hand; label: string }[] = [
  { value: 'right', label: 'Right' },
  { value: 'left', label: 'Left' },
  { value: 'unassigned', label: 'Unassigned' },
]

function ConnectRealCard() {
  const { settings, sensors } = useAppState()
  const ports = useAsync(() => api.system.ports(), [], 4000)
  const [port, setPort] = useState<string | null>(null)
  const [baud, setBaud] = useState<number>(settings?.acquisition.default_baud ?? 115200)
  const [sensorId, setSensorId] = useState('S1')
  const [hand, setHand] = useState<Hand>('right')
  const { run, pending } = useAction()

  useEffect(() => {
    if (!port && ports.data?.length) setPort(ports.data.find((p) => !p.owned_by)?.device ?? null)
  }, [ports.data, port])

  useEffect(() => {
    const used = new Set(sensors.map((s) => s.sensor_id))
    if (used.has(sensorId)) {
      for (let i = 1; i < 10; i++) if (!used.has(`S${i}`)) return setSensorId(`S${i}`)
    }
  }, [sensors])

  return (
    <Section title="Connect a sensor" description="One program can own a COM port at a time" actions={<Button variant="ghost" size="sm" onClick={() => void ports.reload()}><RefreshCw /> Refresh</Button>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="COM port">
            <SimpleSelect value={port} onChange={setPort} placeholder={ports.data?.length ? 'Choose a port' : 'No ports found'} options={(ports.data ?? []).map((p) => ({ value: p.device, label: `${p.device}${p.owned_by ? ` (owned by ${p.owned_by})` : ''} — ${p.description}` }))} />
          </Field>
          <Field label="Baud rate" hint="Must match Serial.begin() in the firmware (115200 in the included sketches).">
            <NumberInput value={baud} onChange={setBaud} min={300} max={4000000} step={1} />
          </Field>
          <Field label="Sensor ID" hint="Unique; letters, digits, - or _.">
            <Input value={sensorId} onChange={(e) => setSensorId(e.target.value.trim())} maxLength={32} />
          </Field>
          <Field label="Worn on">
            <SimpleSelect value={hand} onChange={setHand} options={HANDS} />
          </Field>
        </div>
        <Button disabled={!port || !sensorId || pending === 'connect'} onClick={() => run('connect', () => api.sensors.connect({ port, baud, sensor_id: sensorId, hand }), `Connecting ${sensorId} on ${port}`)}>
          <Plug /> Connect
        </Button>
        <Notice tone="info" title="Close other programs first">Arduino Serial Monitor/Plotter and the CLI tools (check_stream.py, collect.py, control.py) cannot use the port while this backend owns it, and vice versa.</Notice>
        {ports.data?.length ? (
          <Table>
            <TableHeader>
              <TableRow><TableHead>Port</TableHead><TableHead>Description</TableHead><TableHead>VID:PID</TableHead><TableHead>Serial</TableHead><TableHead>Owner</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {ports.data.map((p) => (
                <TableRow key={p.device}>
                  <TableCell className="font-mono">{p.device}</TableCell>
                  <TableCell className="max-w-56 truncate">{p.description}</TableCell>
                  <TableCell className="font-mono text-xs">{p.vid ? `${p.vid}:${p.pid}` : '—'}</TableCell>
                  <TableCell className="font-mono text-xs">{p.serial_number ?? '—'}</TableCell>
                  <TableCell>{p.owned_by ?? <span className="text-muted-foreground">free</span>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <Empty icon={<Cable className="size-6" />} title="No COM ports detected" description="Connect the XIAO MG24 Sense with a USB-C data cable. The list refreshes every few seconds." />
        )}
      </div>
    </Section>
  )
}

function ConnectDemoCard() {
  const { sensors } = useAppState()
  const [sensorId, setSensorId] = useState('1')
  const [rate, setRate] = useState(100)
  const [auto, setAuto] = useState(false)
  const [hand, setHand] = useState<Hand>('right')
  const { run, pending } = useAction()
  useEffect(() => {
    const used = new Set(sensors.map((s) => s.sensor_id))
    for (let i = 1; i < 10; i++) if (!used.has(`DEMO-${i}`)) return setSensorId(String(i))
  }, [sensors])
  return (
    <Section title={<span className="flex items-center gap-2">Connect a simulated sensor <DemoBadge /></span>} description="Generates firmware-format CSV lines through the same parser and clock checks as real hardware">
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Sensor ID" hint="Saved as DEMO-<id>">
            <Input value={sensorId} onChange={(e) => setSensorId(e.target.value.trim())} maxLength={20} />
          </Field>
          <Field label="Simulated rate (Hz)">
            <NumberInput value={rate} onChange={setRate} min={20} max={500} />
          </Field>
          <Field label="Worn on">
            <SimpleSelect value={hand} onChange={setHand} options={HANDS} />
          </Field>
          <Field label="Random gestures" hint="Performs a swipe or twist every few seconds">
            <div className="flex h-9 items-center"><Switch checked={auto} onCheckedChange={setAuto} /></div>
          </Field>
        </div>
        <Button disabled={!sensorId || pending === 'connect'} onClick={() => run('connect', () => api.sensors.connect({ sensor_id: sensorId, simulated: true, demo_rate_hz: rate, demo_auto: auto, hand }), 'Simulated sensor connected')}>
          <PlugZap /> Connect simulated sensor
        </Button>
      </div>
    </Section>
  )
}

function SensorCard({ sensor }: { sensor: SensorState }) {
  const { run, pending } = useAction()
  const [rename, setRename] = useState(sensor.sensor_id)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const active = ['connecting', 'waiting_for_data', 'streaming', 'stalled'].includes(sensor.status)
  const timing = sensor.timing
  const counters = sensor.counters
  return (
    <Section
      title={<span className="flex flex-wrap items-center gap-2">{sensor.sensor_id} {sensor.simulated ? <DemoBadge /> : null} <SensorStatusBadge status={sensor.status} /></span>}
      description={`${sensor.port} · ${sensor.baud} baud · connected ${dateTime(sensor.connected_at)}`}
      actions={
        <>
          {active ? (
            <Button size="sm" variant="outline" disabled={pending === 'disc'} onClick={() => run('disc', () => api.sensors.disconnect(sensor.sensor_id), 'Disconnected')}><Unplug /> Disconnect</Button>
          ) : (
            <Button size="sm" variant="outline" disabled={pending === 'rec'} onClick={() => run('rec', () => api.sensors.reconnect(sensor.sensor_id), 'Reconnecting')}><RefreshCw /> Reconnect</Button>
          )}
          <Button size="icon-sm" variant="ghost" aria-label="Remove from list" onClick={() => setConfirmRemove(true)}><Trash2 /></Button>
        </>
      }
    >
      <div className="space-y-4">
        {sensor.error ? <Notice tone="danger" title={sensor.error.message}>{sensor.error.hint}</Notice> : null}
        {sensor.device_error ? <Notice tone="danger" title="Device reported an error">{sensor.device_error}</Notice> : null}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Device rate" value={hz(sensor.rates.device_hz)} hint="(n−1)/span of device timestamps, last 5 s" />
          <Stat label="Median-interval rate" value={hz(timing.median_interval_hz ?? null)} hint={timing.median_interval_us ? `median Δt ${num(timing.median_interval_us, 0)} µs` : undefined} />
          <Stat label="Line arrival rate" value={hz(sensor.rates.arrival_hz)} hint="host receive side" />
          <Stat label="Valid samples" value={count(sensor.totals.valid_samples)} hint={`${count(sensor.totals.samples)} parsed`} />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <div>
            <div className="mb-2 text-sm font-medium">Validation counters (measured)</div>
            <KeyValue
              items={[
                ['Lines received', count(counters.lines_total)],
                ['Malformed lines', `${count(counters.malformed_total)}${counters.malformed && Object.keys(counters.malformed).length ? ` (${Object.entries(counters.malformed).map(([k, v]) => `${k} ${v}`).join(', ')})` : ''}`],
                ['Diagnostic lines', count(counters.diagnostics)],
                ['Partial first line dropped', count(counters.partial_lines_dropped)],
                ['Timestamp glitches', count(timing.glitches)],
                ['Out-of-order rows', count(timing.backward_steps)],
                ['Duplicate timestamps', count(timing.duplicates)],
                ['Clock resets', count(timing.resets)],
                ['micros() wraps', count(timing.wraps)],
                ['Gaps', count(timing.gaps)],
              ]}
            />
            <p className="mt-2 text-xs text-muted-foreground">Estimated dropped samples: <b className="text-foreground">{count(timing.estimated_missing)}</b> (from gaps; the firmware sends no sequence numbers, so this is an estimate).</p>
          </div>
          <div>
            <div className="mb-2 text-sm font-medium">Clock and identity</div>
            <KeyValue
              items={[
                ['Clock epoch', sensor.clock.epoch ?? '—'],
                ['First device time', sensor.clock.first_device_t_us !== null ? `${count(sensor.clock.first_device_t_us)} µs` : '—'],
                ['Last raw timestamp', sensor.clock.last_device_t_raw !== null ? `${count(sensor.clock.last_device_t_raw)} µs` : '—'],
                ['Last valid sample', sensor.clock.last_valid_sample_age_s !== null ? `${seconds(sensor.clock.last_valid_sample_age_s, 2)} ago` : '—'],
                ['Header seen', sensor.header_alias ?? 'not observed'],
                ['Stalls / disconnects', `${sensor.totals.stalls} / ${sensor.totals.disconnects}`],
              ]}
            />
            <p className="mt-2 text-xs text-muted-foreground">
              {sensor.column_order_assumed ? 'No header seen since connecting: columns are read in the documented order t,ax,ay,az,gx,gy,gz (g and °/s).' : sensor.firmware_hint}
            </p>
            {sensor.last_diagnostic ? <p className="mt-1 text-xs text-muted-foreground">Last diagnostic: <code className="font-mono">{sensor.last_diagnostic}</code></p> : null}
          </div>
        </div>
        <div className="grid gap-3 border-t border-border/60 pt-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <Field label="Worn on">
            <SimpleSelect value={sensor.hand} onChange={(hand) => run('hand', () => api.sensors.update(sensor.sensor_id, { hand }), 'Updated')} options={HANDS} />
          </Field>
          <Field label="Sensor ID" hint={active ? 'Disconnect to change the ID' : undefined}>
            <Input value={rename} onChange={(e) => setRename(e.target.value.trim())} disabled={active} maxLength={32} />
          </Field>
          <Button variant="outline" disabled={active || rename === sensor.sensor_id || !rename} onClick={() => run('rename', () => api.sensors.update(sensor.sensor_id, { sensor_id: rename }), 'Renamed')}>Rename</Button>
        </div>
        {sensor.simulated && sensor.demo ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-4">
            <span className="text-sm font-medium">Simulate:</span>
            {['swipe_left', 'swipe_right', 'wrist_rotation'].map((g) => (
              <Button key={g} size="sm" variant="outline" onClick={() => run('perform', () => api.demo.perform(sensor.sensor_id, g))}>{g}</Button>
            ))}
            <label className="ml-auto flex items-center gap-2 text-sm">
              <Shuffle className="size-4" /> Random gestures
              <Switch checked={Boolean(sensor.demo.auto)} onCheckedChange={(v) => run('auto', () => api.demo.auto(sensor.sensor_id, v))} />
            </label>
            {sensor.demo.current_gesture ? <ToneBadge tone="primary">performing {sensor.demo.current_gesture}</ToneBadge> : null}
          </div>
        ) : null}
      </div>
      <ConfirmDialog open={confirmRemove} onOpenChange={setConfirmRemove} title={`Remove ${sensor.sensor_id}?`} description="Disconnects the sensor and removes it from the live list. Recordings are not affected." confirmLabel="Remove" onConfirm={() => run('remove', () => api.sensors.remove(sensor.sensor_id), 'Removed')} />
    </Section>
  )
}

function SyncCard() {
  const isDemo = useWorkspaceIsDemo()
  const { sensors } = useAppState()
  const sync = useTopicState<SyncState | null>('sync', null, 'sync')
  const initial = useAsync(() => api.advanced.sync(), [], 3000)
  const state = sync ?? initial.data ?? null
  const streaming = sensors.filter((s) => s.status === 'streaming')
  const [a, setA] = useState<string | null>(null)
  const [b, setB] = useState<string | null>(null)
  const [duration, setDuration] = useState(10)
  const [taps, setTaps] = useState(5)
  const { run, pending } = useAction()
  useEffect(() => {
    if (!a && streaming[0]) setA(streaming[0].sensor_id)
    if (!b && streaming[1]) setB(streaming[1].sensor_id)
  }, [streaming.length])
  const latest = useMemo(() => state?.measurements.find((m) => a && b && [...m.sensor_ids].sort().join() === [a, b].sort().join()), [state, a, b])
  return (
    <Section title="Two-sensor synchronization" description="Each board has its own clock; alignment is estimated from host receive times, then measured">
      <div className="space-y-4">
        {streaming.length < 2 ? <Notice tone="info" title="Connect two streaming sensors">Dual-sensor recording works from the Gesture Recorder (one file per sensor, shared capture ID). Alignment measurement needs two streaming sensors.</Notice> : null}
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Sensor A"><SensorSelect value={a} onChange={setA} onlyStreaming /></Field>
          <Field label="Sensor B"><SensorSelect value={b} onChange={setB} onlyStreaming /></Field>
          <Field label="Duration (s)"><NumberInput value={duration} onChange={setDuration} min={3} max={60} /></Field>
          {isDemo ? <Field label="Simulated taps"><NumberInput value={taps} onChange={setTaps} min={3} max={20} /></Field> : <div />}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!a || !b || a === b || state?.measuring || pending === 'sync'} onClick={() => run('sync', () => api.advanced.measureSync([a as string, b as string], duration, isDemo ? taps : 0), isDemo ? 'Measuring with simulated taps' : 'Tap both sensors together firmly, about once per second')}>Measure alignment</Button>
          {state?.message ? <span className="text-sm text-muted-foreground">{state.message}</span> : null}
        </div>
        {state ? (
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(state.alignments).map(([sid, al]) => (
              <Stat key={sid} label={`${sid} clock model`} value={al.ready ? `offset ${num((al.offset_us ?? 0) / 1000, 1)} ms` : 'collecting…'} hint={al.ready ? `drift ${num(al.drift_ppm, 1)} ppm · envelope σ ${num(al.envelope_residual_us, 0)} µs · ${al.points} points` : `${al.points} points`} />
            ))}
          </div>
        ) : null}
        {latest ? (
          <div className="rounded-lg border border-border/70 p-3 text-sm">
            <div className="flex items-center gap-2 font-medium">Latest measurement {latest.details.simulated ? <DemoBadge /> : <ToneBadge tone="success">hardware</ToneBadge>}</div>
            <KeyValue items={[['Paired events', latest.events_used], ['Mean |error|', ms(latest.mean_abs_error_ms)], ['Max |error|', ms(latest.max_abs_error_ms)], ['When', dateTime(latest.created_at)]]} />
            <p className="mt-2 text-xs text-muted-foreground">{latest.details.note} Combined two-sensor inference is not implemented yet; it would require a recorded max error ≤ 20 ms.</p>
          </div>
        ) : null}
      </div>
    </Section>
  )
}

export function SensorsPage() {
  const { sensors } = useAppState()
  const isDemo = useWorkspaceIsDemo()
  return (
    <>
      <PageHeader title="Sensor Connections" description="Discover COM ports, connect XIAO MG24 Sense boards, and watch each sensor's own buffer, clock, counters and health." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,26rem)_1fr]">
        <div className="space-y-5">{isDemo ? <ConnectDemoCard /> : <ConnectRealCard />}</div>
        <div className="space-y-5">
          {sensors.length ? sensors.map((s) => <SensorCard key={s.sensor_id} sensor={s} />) : <Empty title="No sensors yet" description="Connected sensors appear here with live health and counters." />}
          <SyncCard />
        </div>
      </div>
    </>
  )
}
