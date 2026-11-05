import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Empty, Field, KeyValue, Notice, NumberInput, Section, Stat } from '@/components/common/Bits'
import { PageHeader } from '@/components/common/PageHeader'
import { SensorSelect, SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge, ToneBadge } from '@/components/common/StatusBadge'
import { ProbabilityBars } from '@/components/charts/Bars'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState, useWorkspaceIsDemo } from '@/hooks/useAppState'
import { useTopicState } from '@/hooks/useTopic'
import { api } from '@/services/api'
import { humanize, ms, num, pct, timeOfDay } from '@/lib/format'
import type { MappingProfile, Prediction } from '@/types/api'
import { OutcomeBadge } from './DashboardPage'

export function RecognitionPage() {
  const { recognition, settings, detections, control } = useAppState()
  const isDemo = useWorkspaceIsDemo()
  const models = useAsync(() => api.models.list(), [isDemo, settings?.selected_model_id])
  const profiles = useAsync<MappingProfile[]>(() => api.mappings.profiles(), [settings?.active_profile_id])
  const prediction = useTopicState<Prediction | null>('predictions', recognition?.last_prediction ?? null, 'prediction', 120)
  const [modelId, setModelId] = useState<string | null>(null)
  const [sensorId, setSensorId] = useState<string | null>(null)
  const inference = settings?.inference
  const [hop, setHop] = useState(inference?.hop_s ?? 0.1)
  const [threshold, setThreshold] = useState(inference?.threshold ?? 0.85)
  const [smoothing, setSmoothing] = useState(inference?.smoothing_k ?? 3)
  const [debounce, setDebounce] = useState(inference?.debounce_n ?? 2)
  const [cooldown, setCooldown] = useState(inference?.cooldown_s ?? 1.2)
  const [rearm, setRearm] = useState(inference?.require_idle_rearm ?? true)
  const { run, pending } = useAction()
  const running = recognition?.running ?? false

  useEffect(() => {
    if (!modelId && settings?.selected_model_id) setModelId(settings.selected_model_id)
    if (!sensorId && settings?.selected_sensor_id) setSensorId(settings.selected_sensor_id)
  }, [settings?.selected_model_id, settings?.selected_sensor_id])

  const compatible = (models.data ?? []).filter((m) => m.compatibility.compatible)
  const chosen = compatible.find((m) => m.model_id === modelId)
  const windowS = running ? recognition?.model?.window_s : chosen?.window_s
  const activeProfile = profiles.data?.find((p) => p.profile_id === settings?.active_profile_id)
  const mappingFor = useMemo(() => {
    const map: Record<string, string> = {}
    for (const m of activeProfile?.mappings ?? []) if (m.enabled) map[m.label_id] = m.description
    return map
  }, [activeProfile])

  const start = () => run('start', () => api.recognition.start({ model_id: modelId, sensor_id: sensorId, hop_s: hop, threshold, smoothing_k: smoothing, debounce_n: debounce, cooldown_s: cooldown, require_idle_rearm: rearm }), 'Recognition started')
  const saveDefaults = () => run('defaults', () => api.settings.patch({ inference: { hop_s: hop, threshold, smoothing_k: smoothing, debounce_n: debounce, cooldown_s: cooldown, require_idle_rearm: rearm } }), 'Saved as defaults')

  return (
    <>
      <PageHeader title="Live Recognition" description="Continuously windows the live buffer, extracts the model's features and predicts. Idle is a valid class and never triggers an action." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,24rem)_1fr]">
        <Section title="Configuration">
          <div className="space-y-4">
            <Field label="Model" hint={compatible.length ? undefined : 'No compatible models yet — train or trust one on the Model Training page.'}>
              <SimpleSelect value={modelId} onChange={setModelId} options={compatible.map((m) => ({ value: m.model_id, label: `${m.name} · ${m.feature_version}` }))} placeholder="Choose a model" disabled={running} />
            </Field>
            <Field label="Sensor">
              <SensorSelect value={sensorId} onChange={setSensorId} onlyStreaming />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Window (s)" hint="Set when the model was trained">
                <div className="tabular flex h-9 items-center rounded-md border border-border bg-muted/40 px-3 text-sm">{windowS ?? '—'}</div>
              </Field>
              <Field label="Hop (s)" hint={windowS ? `Overlap ${num(Math.max(0, windowS - hop), 2)} s (${pct(Math.max(0, windowS - hop) / windowS, 0)})` : undefined}>
                <NumberInput value={hop} onChange={setHop} min={0.02} max={2} step={0.05} disabled={running} />
              </Field>
            </div>
            <Field label={`Threshold: ${num(threshold, 2)}`} hint="Minimum smoothed probability for a non-idle detection">
              <Slider value={[threshold]} min={0.3} max={1} step={0.01} onValueChange={([v]) => setThreshold(v)} disabled={running} />
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Smoothing" hint="windows averaged"><NumberInput value={smoothing} onChange={(v) => setSmoothing(Math.round(v))} min={1} max={20} disabled={running} /></Field>
              <Field label="Debounce" hint="consecutive windows"><NumberInput value={debounce} onChange={(v) => setDebounce(Math.round(v))} min={1} max={20} disabled={running} /></Field>
              <Field label="Cooldown (s)"><NumberInput value={cooldown} onChange={setCooldown} min={0} max={30} step={0.1} disabled={running} /></Field>
            </div>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Require a confident idle before the next detection</span>
              <Switch checked={rearm} onCheckedChange={setRearm} disabled={running} />
            </label>
            <div className="flex flex-wrap gap-2">
              {running ? (
                <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={() => run('stop', () => api.recognition.stop(), 'Recognition stopped')}><Square /> Stop</Button>
              ) : (
                <Button disabled={!modelId || !sensorId || pending === 'start'} onClick={() => void start()}><Play /> Start recognition</Button>
              )}
              <Button variant="outline" disabled={running} onClick={() => void saveDefaults()}>Save as defaults</Button>
            </div>
            <Notice tone="info" title={control?.armed ? (control.simulated_actions ? 'PC control armed (simulated)' : 'PC control ARMED') : 'PC control is disarmed'}>
              {control?.armed ? 'Detections run their mapped action through the safety gate.' : 'Detections show what would happen without touching the OS.'} <Link className="text-primary underline-offset-2 hover:underline" to="/mappings">Command Mapping</Link>
            </Notice>
          </div>
        </Section>

        <div className="space-y-5">
          <Section title="Current prediction" actions={prediction?.simulated ? <DemoBadge /> : null} description={recognition?.message}>
            {running && prediction ? (
              <div className="grid gap-5 lg:grid-cols-[16rem_1fr]">
                <div className="space-y-3">
                  <div className="rounded-xl border border-border/70 bg-muted/30 p-4 text-center">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Prediction</div>
                    <div className="mt-1 font-mono text-2xl font-semibold">{prediction.label}</div>
                    <div className={prediction.above_threshold ? 'tabular text-3xl font-semibold text-primary' : 'tabular text-3xl font-semibold text-muted-foreground'}>{pct(prediction.score, 0)}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{prediction.above_threshold ? 'above threshold' : 'below threshold'}</div>
                  </div>
                  <KeyValue columns={1} items={[
                    ['Time', timeOfDay(prediction.at)],
                    ['Processing latency', ms(prediction.latency_ms)],
                    ['Feature compute', ms(prediction.processing_ms, 2)],
                    ['Mapped action', mappingFor[prediction.label] ?? (recognition?.model?.idle_labels.includes(prediction.label) ? 'idle (never acts)' : 'none')],
                    ['Re-armed', prediction.rearmed ? 'yes' : 'waiting for idle'],
                    ['Suppressed', prediction.suppressed ? humanize(prediction.suppressed) : '—'],
                  ]} />
                  <p className="text-xs text-muted-foreground">Latency is measured from receipt of the newest sample to the prediction, plus the {prediction.window_s} s window. Motion-to-action latency is not measured.</p>
                </div>
                <div>
                  <div className="mb-2 text-sm font-medium">Smoothed class probabilities</div>
                  <ProbabilityBars probabilities={prediction.probabilities} highlight={prediction.label} threshold={recognition?.config.threshold as number | undefined} />
                </div>
              </div>
            ) : (
              <Empty title={running ? 'Waiting for the first window…' : 'Recognition is stopped'} description={running ? 'Predictions appear once a full window of valid samples is buffered.' : 'Choose a model and sensor, then press Start.'} />
            )}
          </Section>
          {running ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Windows" value={recognition?.counters.windows ?? 0} />
              <Stat label="Detections" value={recognition?.counters.detections ?? 0} />
              <Stat label="Skipped" value={Object.entries(recognition?.counters ?? {}).filter(([k]) => k.startsWith('skipped')).reduce((a, [, v]) => a + v, 0)} hint={Object.entries(recognition?.counters ?? {}).filter(([k]) => k.startsWith('skipped')).map(([k, v]) => `${k.replace('skipped_', '')} ${v}`).join(', ') || undefined} />
              <Stat label="Suppressed" value={Object.entries(recognition?.counters ?? {}).filter(([k]) => k.startsWith('suppressed')).reduce((a, [, v]) => a + v, 0)} hint="cooldown / waiting for idle" />
            </div>
          ) : null}
          <Section title="Detection history">
            {detections.length ? (
              <Table>
                <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Gesture</TableHead><TableHead>Score</TableHead><TableHead>Mapped action</TableHead><TableHead>Outcome</TableHead><TableHead>Sensor</TableHead></TableRow></TableHeader>
                <TableBody>
                  {[...detections].reverse().slice(0, 40).map((d) => (
                    <TableRow key={d.detection_id}>
                      <TableCell className="tabular text-xs text-muted-foreground">{timeOfDay(d.at)}</TableCell>
                      <TableCell className="font-mono text-xs">{d.label}</TableCell>
                      <TableCell className="tabular">{pct(d.score, 0)}</TableCell>
                      <TableCell>{d.mapped_action ?? <span className="text-muted-foreground">no mapping</span>}</TableCell>
                      <TableCell><OutcomeBadge outcome={d.outcome} /></TableCell>
                      <TableCell className="text-xs">{d.sensor_id}{d.simulated ? <ToneBadge tone="primary" className="ml-1">sim</ToneBadge> : null}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty title="No detections yet" />
            )}
          </Section>
        </div>
      </div>
    </>
  )
}
