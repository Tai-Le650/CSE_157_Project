import { useEffect, useMemo, useState } from 'react'
import { Circle, Download, Eye, Plus, Save, Square, Tags, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Empty, Field, Notice, NumberInput, Section } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { LabelSelect, SensorChecklist, SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge, ValidationBadge } from '@/components/common/StatusBadge'
import { StaticSignalChart } from '@/components/charts/StaticSignalChart'
import { LabelManager } from '@/components/datasets/LabelManager'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState, useStreamingSensors, useWorkspaceIsDemo } from '@/hooks/useAppState'
import { api, errorMessage } from '@/services/api'
import { dateTime, hz, seconds } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { SignalPreview, StagedTrial } from '@/types/api'

function PhaseDisplay() {
  const { recorder } = useAppState()
  const state = recorder?.state
  if (!state?.active) {
    return (
      <div className="flex h-44 flex-col items-center justify-center rounded-xl border border-dashed border-border text-center">
        <Circle className="mb-2 size-7 text-muted-foreground" />
        <div className="font-medium">Ready</div>
        <div className="text-sm text-muted-foreground">{state?.message || 'Choose a label and press Start.'}</div>
      </div>
    )
  }
  const recording = state.phase === 'recording'
  const progress = state.duration_s && state.elapsed_s !== null ? Math.min(100, (state.elapsed_s / state.duration_s) * 100) : 0
  return (
    <div className={cn('flex h-44 flex-col items-center justify-center rounded-xl border text-center transition-colors', recording ? 'border-destructive/40 bg-destructive/5' : 'border-primary/30 bg-primary/5')}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {state.mode === 'continuous' ? 'Continuous recording' : `Trial ${state.trial} of ${state.trials}`} · {state.label_id ?? 'unlabelled'}
      </div>
      <div className={cn('my-1 text-5xl font-semibold tabular-nums', recording && 'text-destructive')}>
        {state.phase === 'countdown' ? Math.ceil(state.countdown_remaining_s ?? 0) : recording ? 'GO' : state.phase === 'pause' ? '…' : ''}
      </div>
      <div className="text-sm">{state.message}</div>
      {recording && state.mode === 'trials' ? <Progress className="mt-3 w-2/3" value={progress} /> : null}
    </div>
  )
}

function PreviewDialog({ trial, onClose }: { trial: StagedTrial | null; onClose: () => void }) {
  const [preview, setPreview] = useState<SignalPreview | null>(null)
  useEffect(() => {
    setPreview(null)
    if (trial) void api.recorder.preview(trial.staging_id).then(setPreview).catch((err) => toast.error(errorMessage(err)))
  }, [trial?.staging_id])
  return (
    <Dialog open={trial !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{trial?.label_id ?? 'Unlabelled'} · {trial?.sensor_id}</DialogTitle>
          <DialogDescription>{trial ? `${seconds(trial.duration_s)} · ${trial.sample_count} samples · ${hz(trial.fs_median_hz)} median` : ''}</DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className="space-y-4">
            <StaticSignalChart preview={preview} channels={['ax', 'ay', 'az']} height={200} />
            <StaticSignalChart preview={preview} channels={['gx', 'gy', 'gz']} height={200} />
          </div>
        ) : (
          <div className="h-40 animate-pulse rounded-lg bg-muted" />
        )}
        {trial?.issues.length ? <Notice tone="warning" title="Validation">{trial.issues.map((i) => i.message).join(' · ')}</Notice> : null}
      </DialogContent>
    </Dialog>
  )
}

export function RecorderPage() {
  const { recorder, settings } = useAppState()
  const streaming = useStreamingSensors()
  const isDemo = useWorkspaceIsDemo()
  const labels = useAsync(() => api.labels.list(), [isDemo])
  const sessions = useAsync(() => api.sessions.list(), [isDemo, recorder?.state.session_id])
  const [label, setLabel] = useState<string | null>('swipe_left')
  const [sensorIds, setSensorIds] = useState<string[]>([])
  const [duration, setDuration] = useState(settings?.recording.trial_duration_s ?? 1.5)
  const [countdown, setCountdown] = useState(settings?.recording.countdown_s ?? 3)
  const [trials, setTrials] = useState(settings?.recording.trials_per_set ?? 10)
  const [pause, setPause] = useState(settings?.recording.pause_between_s ?? 1)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [previewTrial, setPreviewTrial] = useState<StagedTrial | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [labelsOpen, setLabelsOpen] = useState(false)
  const [editNotes, setEditNotes] = useState<{ id: string; text: string } | null>(null)
  const { run, pending } = useAction()
  const staging = recorder?.staging ?? []
  const active = recorder?.state.active ?? false

  useEffect(() => {
    if (!sensorIds.length && streaming.length) setSensorIds([streaming[0].sensor_id])
    setSensorIds((ids) => ids.filter((id) => streaming.some((s) => s.sensor_id === id)))
  }, [streaming.map((s) => s.sensor_id).join()])

  useEffect(() => {
    if (recorder?.state.session_id && !sessionId) setSessionId(recorder.state.session_id)
  }, [recorder?.state.session_id])

  const sessionOptions = useMemo(() => (sessions.data ?? []).map((s) => ({ value: s.session_id, label: `${s.name} (${s.recordings})` })), [sessions.data])
  const allSelected = staging.length > 0 && selected.length === staging.length

  const startTrials = () =>
    run('start', () => api.recorder.startTrials({ label_id: label as string, sensor_ids: sensorIds, duration_s: duration, countdown_s: countdown, trials, pause_s: pause, session_id: sessionId, notes }))
  const startContinuous = () => run('cont', () => api.recorder.startContinuous({ label_id: label, sensor_ids: sensorIds, session_id: sessionId, notes }))
  const newSession = () =>
    run('session', async () => {
      const created = await api.recorder.newSession(`Session ${new Date().toLocaleString()}`)
      setSessionId(created.session_id)
      await sessions.reload()
      return created
    }, 'New session started — use one session per sensor mounting')

  return (
    <>
      <PageHeader
        title="Gesture Recorder"
        description="Record repeated labelled trials after a countdown. Trials stay in staging until you save them into data/raw (immutable) or discard them."
        actions={<Button variant="outline" onClick={() => setLabelsOpen(true)}><Tags /> Manage labels</Button>}
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,28rem)_1fr]">
        <Section title="Setup" description={isDemo ? 'Demo sensors perform the selected gesture at GO' : 'Perform the gesture right after GO, then return to the starting pose'}>
          <div className="space-y-4">
            <Field label="Label">
              <LabelSelect labels={labels.data ?? []} value={label} onChange={setLabel} />
            </Field>
            <Field label="Sensors" hint="Select two sensors for dual-sensor trials (one file per sensor, shared capture ID).">
              <SensorChecklist value={sensorIds} onChange={setSensorIds} sensors={streaming} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Trial duration (s)"><NumberInput value={duration} onChange={setDuration} min={0.3} max={30} step={0.1} /></Field>
              <Field label="Countdown (s)"><NumberInput value={countdown} onChange={setCountdown} min={0} max={10} step={0.5} /></Field>
              <Field label="Trials"><NumberInput value={trials} onChange={(v) => setTrials(Math.round(v))} min={1} max={200} /></Field>
              <Field label="Pause between (s)"><NumberInput value={pause} onChange={setPause} min={0} max={30} step={0.5} /></Field>
            </div>
            <Field label="Session" hint="Evaluation keeps sessions together; start a new one whenever you re-mount the sensor.">
              <div className="flex gap-2">
                <SimpleSelect value={sessionId} onChange={setSessionId} options={sessionOptions} placeholder="New session on start" />
                <Button variant="outline" size="icon" aria-label="New session" onClick={() => void newSession()}><Plus /></Button>
              </div>
            </Field>
            <Field label="Notes (saved with each trial)">
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="e.g. right wrist, strap 2 cm above the joint" />
            </Field>
            <div className="flex flex-wrap gap-2">
              {active ? (
                <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={() => run('stop', () => api.recorder.stop())}><Square /> Stop</Button>
              ) : (
                <>
                  <Button disabled={!label || !sensorIds.length || pending === 'start'} onClick={() => void startTrials()}><Circle /> Start {trials} trial{trials === 1 ? '' : 's'}</Button>
                  <Button variant="outline" disabled={!sensorIds.length || pending === 'cont'} onClick={() => void startContinuous()}>Start continuous</Button>
                </>
              )}
            </div>
            {!streaming.length ? <Notice tone="warning" title="No streaming sensor">Connect a sensor on the Sensor Connections page first.</Notice> : null}
          </div>
        </Section>

        <div className="space-y-5">
          <Section title="Recorder" actions={recorder?.state.active && isDemo ? <DemoBadge /> : null}>
            <PhaseDisplay />
          </Section>
          <Section
            title={`Staged trials (${staging.length})`}
            description="Review before saving. Saving moves files into data/raw/YYYY/MM/DD with a SHA-256 hash; they are never rewritten."
            actions={
              <>
                <Button size="sm" disabled={!selected.length} onClick={() => run('save', async () => { const r = await api.recorder.save(selected); setSelected([]); return r }, (r) => `Saved ${r.saved.length} recording(s)${r.errors.length ? `, ${r.errors.length} failed` : ''}`)}><Save /> Save selected</Button>
                <Button size="sm" variant="outline" disabled={!selected.length} onClick={() => setConfirmDiscard(true)}><Trash2 /> Discard…</Button>
              </>
            }
          >
            {staging.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"><Checkbox checked={allSelected} onCheckedChange={(v) => setSelected(v ? staging.map((s) => s.staging_id) : [])} aria-label="Select all" /></TableHead>
                    <TableHead>Label</TableHead><TableHead>Sensor</TableHead><TableHead>Kind</TableHead><TableHead>Duration</TableHead><TableHead>Samples</TableHead><TableHead>Rate</TableHead><TableHead>Validation</TableHead><TableHead>Started</TableHead><TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...staging].reverse().map((s) => (
                    <TableRow key={s.staging_id}>
                      <TableCell><Checkbox checked={selected.includes(s.staging_id)} onCheckedChange={(v) => setSelected(v ? [...selected, s.staging_id] : selected.filter((id) => id !== s.staging_id))} aria-label={`Select ${s.staging_id}`} /></TableCell>
                      <TableCell className="font-mono text-xs">{s.label_id ?? '—'}</TableCell>
                      <TableCell>{s.sensor_id}</TableCell>
                      <TableCell className="text-xs">{s.kind}</TableCell>
                      <TableCell className="tabular">{seconds(s.duration_s)}</TableCell>
                      <TableCell className="tabular">{s.sample_count}</TableCell>
                      <TableCell className="tabular text-xs">{hz(s.fs_median_hz)}</TableCell>
                      <TableCell>
                        {s.issues.length ? (
                          <Tooltip><TooltipTrigger><ValidationBadge state={s.validation_state} /></TooltipTrigger><TooltipContent className="max-w-sm">{s.issues.map((i) => i.message).join(' · ')}</TooltipContent></Tooltip>
                        ) : <ValidationBadge state={s.validation_state} />}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{dateTime(s.start_time)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="icon-xs" variant="ghost" aria-label="Preview" onClick={() => setPreviewTrial(s)}><Eye /></Button>
                          <Button size="xs" variant="ghost" onClick={() => setEditNotes({ id: s.staging_id, text: s.notes })}>Notes</Button>
                          <Button size="icon-xs" variant="ghost" aria-label="Export CSV" onClick={() => run('export', () => api.recorder.exportCsv(s.staging_id))}><Download /></Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty title="Nothing staged" description="Captured trials appear here for review." />
            )}
          </Section>
        </div>
      </div>
      <PreviewDialog trial={previewTrial} onClose={() => setPreviewTrial(null)} />
      <ConfirmDialog open={confirmDiscard} onOpenChange={setConfirmDiscard} title={`Discard ${selected.length} staged trial(s)?`} description="The staged files are deleted permanently. Saved recordings are not affected." destructive confirmLabel="Discard" onConfirm={() => run('discard', async () => { const r = await api.recorder.discard(selected); setSelected([]); return r }, 'Discarded')} />
      <ConfirmDialog open={editNotes !== null} onOpenChange={(open) => !open && setEditNotes(null)} title="Trial notes" confirmLabel="Save notes" onConfirm={() => editNotes && run('notes', () => api.recorder.updateStaged(editNotes.id, { notes: editNotes.text }), 'Notes saved')}>
        <Textarea rows={3} value={editNotes?.text ?? ''} onChange={(e) => editNotes && setEditNotes({ ...editNotes, text: e.target.value })} />
      </ConfirmDialog>
      <Dialog open={labelsOpen} onOpenChange={setLabelsOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Labels</DialogTitle>
            <DialogDescription>Active now: Idle, Swipe Left, Swipe Right and Twist. Other built-in labels are defined but disabled until you enable them.</DialogDescription>
          </DialogHeader>
          <LabelManager labels={labels.data ?? []} onChanged={() => void labels.reload()} />
        </DialogContent>
      </Dialog>
    </>
  )
}
