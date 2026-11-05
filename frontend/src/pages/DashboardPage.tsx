import { useState } from 'react'
import { Link } from 'react-router'
import { AlertTriangle, CheckCircle2, Info, OctagonX, Play, Shield, ShieldOff, Square, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { PageHeader } from '@/components/common/PageHeader'
import { Empty, KeyValue, Section, Stat } from '@/components/common/Bits'
import { DemoBadge, SensorStatusBadge, ToneBadge } from '@/components/common/StatusBadge'
import { LiveSignalChart } from '@/components/charts/LiveSignalChart'
import { ArmDialog } from '@/components/control/ArmDialog'
import { useEmergencyStop } from '@/components/layout/EmergencyStop'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState } from '@/hooks/useAppState'
import { useTopicState } from '@/hooks/useTopic'
import { api } from '@/services/api'
import { count, hz, ms, num, pct, timeOfDay } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ModelSummary, Prediction } from '@/types/api'

const LEVEL_ICON = { info: Info, warning: AlertTriangle, error: XCircle, debug: Info }

export function DashboardPage() {
  const state = useAppState()
  const { sensors, status, control, settings, recognition, detections, recorder, log } = state
  const prediction = useTopicState<Prediction | null>('predictions', recognition?.last_prediction ?? null, 'prediction', 200)
  const models = useAsync(() => api.models.list(), [settings?.selected_model_id, status?.workspace])
  const selectedModel: ModelSummary | undefined = models.data?.find((m) => m.selected)
  const primarySensor = settings?.selected_sensor_id && sensors.some((s) => s.sensor_id === settings.selected_sensor_id) ? settings.selected_sensor_id : sensors.find((s) => s.status === 'streaming')?.sensor_id ?? null
  const { run, pending } = useAction()
  const [armOpen, setArmOpen] = useState(false)
  const estop = useEmergencyStop()

  return (
    <>
      <PageHeader title="Dashboard" description="Live overview of sensors, recognition and PC control. Every value comes from the backend; nothing here is estimated unless labelled." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Section title="Sensors" description="Measured from device timestamps" actions={<Button variant="outline" size="sm" asChild><Link to="/sensors">Manage</Link></Button>}>
          {sensors.length ? (
            <div className="space-y-3">
              {sensors.map((s) => (
                <div key={s.sensor_id} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 font-medium">
                      {s.sensor_id}
                      {s.simulated ? <DemoBadge /> : null}
                      {s.hand !== 'unassigned' ? <span className="text-xs capitalize text-muted-foreground">{s.hand}</span> : null}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">{s.port} · {count(s.totals.valid_samples)} valid samples</div>
                  </div>
                  <div className="text-right">
                    <SensorStatusBadge status={s.status} />
                    <div className="tabular mt-1 text-xs text-muted-foreground">{hz(s.rates.device_hz)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No sensors connected" description={status?.workspace === 'demo' ? 'Connect a simulated sensor to try the full workflow.' : 'Plug in the XIAO MG24 Sense and connect its COM port.'} action={<Button asChild size="sm"><Link to="/sensors">Connect a sensor</Link></Button>} />
          )}
        </Section>

        <Section title="Status" description={`Primary mode: ${status?.primary_mode ?? '—'}`}>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Recording" value={recorder?.state.active ? <span className="text-destructive">{recorder.state.phase}</span> : 'Idle'} hint={recorder?.state.active ? `${recorder.state.label_id ?? ''} ${recorder.state.trial}/${recorder.state.trials || '∞'}` : `${recorder?.staging.length ?? 0} staged`} />
            <Stat label="Recognition" value={recognition?.running ? <span className="text-primary">Running</span> : 'Stopped'} hint={recognition?.model?.name ?? 'No model running'} />
            <Stat label="PC control" value={control?.armed ? <span className="text-destructive">Armed</span> : control?.estop_latched ? <span className="text-destructive">E-stop</span> : 'Disarmed'} hint={control?.pc_control_enabled ? (control.simulated_actions ? 'Actions simulated (Demo)' : 'Allowed in Settings') : 'Disabled in Settings'} />
            <Stat label="Training" value={status?.training_active ? 'Running' : 'Idle'} hint={`${status?.clients ?? 0} browser tab(s) connected`} />
          </div>
          {status && (status.ui_frames_dropped > 0 || status.ui_samples_dropped > 0) ? (
            <p className="mt-3 text-xs text-muted-foreground">Display-only drops: {status.ui_frames_dropped} chart frames, {status.ui_samples_dropped} samples (recording is unaffected).</p>
          ) : null}
        </Section>

        <Section title="Selected model" actions={<Button variant="outline" size="sm" asChild><Link to="/training">Models</Link></Button>}>
          {selectedModel ? (
            <KeyValue
              columns={1}
              items={[
                ['Name', selectedModel.name],
                ['Features', selectedModel.feature_version],
                ['Window', selectedModel.window_s ? `${selectedModel.window_s} s` : '—'],
                ['Labels', selectedModel.labels?.join(', ') ?? '—'],
                ['Evaluation', selectedModel.evaluation_summary.status === 'evaluated' ? `accuracy ${pct(selectedModel.evaluation_summary.accuracy)} · macro F1 ${num(selectedModel.evaluation_summary.macro_f1, 2)}` : selectedModel.evaluation_summary.status ?? '—'],
              ]}
            />
          ) : (
            <Empty title="No model selected" description="Train a model and select it on the Model Training page." />
          )}
        </Section>

        <Section title="Latest prediction" description={recognition?.running ? `Window ${recognition.model?.window_s} s · hop ${recognition.config.hop_s} s` : 'Recognition is stopped'}>
          {prediction && recognition?.running ? (
            <div className="space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-2xl font-semibold">{prediction.label}</span>
                <span className={cn('tabular text-lg font-semibold', prediction.above_threshold ? 'text-primary' : 'text-muted-foreground')}>{pct(prediction.score, 0)}</span>
              </div>
              <KeyValue columns={1} items={[['Time', timeOfDay(prediction.at)], ['Processing latency', ms(prediction.latency_ms)], ['Above threshold', prediction.above_threshold ? 'yes' : 'no']]} />
              {prediction.simulated ? <DemoBadge /> : null}
            </div>
          ) : (
            <Empty title="No live prediction" description="Start Live Recognition to see predictions here." />
          )}
        </Section>

        <Section title="Live acceleration magnitude |a|" description={primarySensor ? `Sensor ${primarySensor}, last 10 s` : 'No streaming sensor'} className="lg:col-span-2">
          <LiveSignalChart sensorId={primarySensor} channels={['amag']} windowS={10} height={170} accelUnit={settings?.display.accel_unit ?? 'g'} />
        </Section>

        <Section title="Controls" description="Quick access; full options live on each page">
          <div className="grid gap-2">
            <Button variant="outline" asChild><Link to="/recorder"><Play /> {recorder?.state.active ? 'Recording in progress…' : 'Record gestures'}</Link></Button>
            {recognition?.running ? (
              <Button variant="outline" disabled={pending === 'recog'} onClick={() => run('recog', () => api.recognition.stop(), 'Recognition stopped')}><Square /> Stop recognition</Button>
            ) : (
              <Button variant="outline" disabled={pending === 'recog' || !settings?.selected_model_id} onClick={() => run('recog', () => api.recognition.start({}), 'Recognition started')}><Play /> Start recognition</Button>
            )}
            {control?.armed ? (
              <Button variant="outline" onClick={() => run('disarm', () => api.control.disarm(), 'PC control disarmed')}><ShieldOff /> Disarm PC control</Button>
            ) : (
              <Button variant="outline" onClick={() => setArmOpen(true)} disabled={control?.estop_latched}><Shield /> Arm PC control…</Button>
            )}
            <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={() => void estop()}><OctagonX /> Emergency Stop</Button>
          </div>
        </Section>

        <Section title="Detection history" description="Most recent first" className="lg:col-span-2">
          {detections.length ? (
            <ScrollArea className="h-64">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="py-1.5 font-medium">Time</th><th className="font-medium">Gesture</th><th className="font-medium">Score</th><th className="font-medium">Mapped action</th><th className="font-medium">Outcome</th></tr>
                </thead>
                <tbody>
                  {[...detections].reverse().map((d) => (
                    <tr key={d.detection_id} className="border-t border-border/60">
                      <td className="tabular py-1.5 text-muted-foreground">{timeOfDay(d.at)}</td>
                      <td className="font-mono">{d.label}</td>
                      <td className="tabular">{pct(d.score, 0)}</td>
                      <td>{d.mapped_action ?? <span className="text-muted-foreground">no mapping</span>}</td>
                      <td><OutcomeBadge outcome={d.outcome} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollArea>
          ) : (
            <Empty title="No detections yet" description="Detections appear when a non-idle gesture passes the threshold, debounce and cooldown." />
          )}
        </Section>

        <Section title="Activity log">
          <ScrollArea className="h-64 pr-3">
            <ul className="space-y-2 text-sm">
              {[...log].reverse().map((entry) => {
                const Icon = LEVEL_ICON[entry.level] ?? Info
                return (
                  <li key={entry.id} className="flex gap-2">
                    <Icon className={cn('mt-0.5 size-4 shrink-0', entry.level === 'error' ? 'text-destructive' : entry.level === 'warning' ? 'text-warning-foreground dark:text-warning' : 'text-muted-foreground')} />
                    <div className="min-w-0">
                      <div className="leading-snug">{entry.message}</div>
                      <div className="text-xs text-muted-foreground">{timeOfDay(entry.ts)} · {entry.category}</div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </ScrollArea>
        </Section>
      </div>
      <ArmDialog open={armOpen} onOpenChange={setArmOpen} />
    </>
  )
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const map: Record<string, { tone: 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'primary'; label: string; icon?: React.ReactNode }> = {
    executed: { tone: 'success', label: 'executed', icon: <CheckCircle2 className="size-3" /> },
    simulated: { tone: 'primary', label: 'simulated' },
    queued: { tone: 'info', label: 'queued' },
    preview: { tone: 'muted', label: 'preview (disarmed)' },
    unmapped: { tone: 'muted', label: 'unmapped' },
    blocked: { tone: 'warning', label: 'blocked' },
    error: { tone: 'danger', label: 'error' },
  }
  const entry = map[outcome] ?? { tone: 'muted' as const, label: outcome }
  return <ToneBadge tone={entry.tone} className="gap-1">{entry.icon}{entry.label}</ToneBadge>
}
