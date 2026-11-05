import { useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw, Scissors, Trash2, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Field, KeyValue, Notice, Section } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { LabelSelect, SimpleSelect } from '@/components/common/Pickers'
import { ToneBadge, ValidationBadge } from '@/components/common/StatusBadge'
import { StaticSignalChart } from '@/components/charts/StaticSignalChart'
import { SpectrumPanel, type SpectrumSource } from '@/components/charts/SpectrumPanel'
import { useAction, useAsync } from '@/hooks/useAsync'
import { api, errorMessage } from '@/services/api'
import { bytes, count, dateTime, hz, num, seconds } from '@/lib/format'
import type { Label, RecordingDetail, Session, SignalPreview } from '@/types/api'

const SEGMENT_COLORS = ['rgba(59,130,246,0.14)', 'rgba(234,88,12,0.14)', 'rgba(22,163,74,0.14)', 'rgba(219,39,119,0.14)', 'rgba(124,58,237,0.14)']

export function RecordingDetailDialog({ recordingId, labels, sessions, onClose, onChanged }: { recordingId: string | null; labels: Label[]; sessions: Session[]; onClose: () => void; onChanged: () => void }) {
  const detail = useAsync<RecordingDetail | null>(() => (recordingId ? api.recordings.get(recordingId) : Promise.resolve(null)), [recordingId])
  const recipes = useAsync(() => api.recordings.recipes(), [])
  const [preview, setPreview] = useState<SignalPreview | null>(null)
  const [derivativeId, setDerivativeId] = useState<string | null>(null)
  const [segmentMode, setSegmentMode] = useState(false)
  const [segmentLabel, setSegmentLabel] = useState<string | null>(null)
  const [recipe, setRecipe] = useState('default-v1')
  const [spectrumRecipe, setSpectrumRecipe] = useState<string>('default-resampled-v1')
  const [deleteMode, setDeleteMode] = useState<'metadata' | 'disk'>('metadata')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [notes, setNotes] = useState('')
  const { run } = useAction()
  const rec = detail.data ?? null

  useEffect(() => {
    setDerivativeId(null)
    setSegmentMode(false)
  }, [recordingId])

  useEffect(() => {
    if (rec) {
      setNotes(rec.notes)
      setSegmentLabel(rec.label_id && rec.label_id !== 'idle' ? rec.label_id : labels.find((l) => l.enabled && !l.is_idle)?.label_id ?? null)
    }
  }, [rec?.recording_id])

  useEffect(() => {
    setPreview(null)
    if (!recordingId) return
    void api.recordings.preview(recordingId, derivativeId).then(setPreview).catch((err) => toast.error(errorMessage(err)))
  }, [recordingId, derivativeId, rec?.segments.length])

  const reload = async () => {
    await detail.reload()
    onChanged()
  }

  const overlay = useMemo(() => (rec?.segments ?? []).map((s, i) => ({ start_s: s.start_s, end_s: s.end_s, label: s.label_id, color: SEGMENT_COLORS[i % SEGMENT_COLORS.length] })), [rec?.segments])

  const spectrumTarget: SpectrumSource | null = rec
    ? derivativeId
      ? { source: 'derivative', recording_id: rec.recording_id, derivative_id: derivativeId }
      : rec.validation_state === 'flagged'
        ? { source: 'recording', recording_id: rec.recording_id, recipe_name: spectrumRecipe }
        : { source: 'recording', recording_id: rec.recording_id }
    : null

  return (
    <Dialog open={recordingId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2 font-mono text-base">
            {recordingId}
            {rec ? <ValidationBadge state={rec.validation_state} /> : null}
            {rec?.source === 'demo' ? <ToneBadge tone="primary">simulated</ToneBadge> : null}
            {rec?.source_changed ? <ToneBadge tone="danger">file changed since registration</ToneBadge> : null}
          </DialogTitle>
          <DialogDescription>{rec ? `${rec.kind} · ${rec.label_id ?? 'no label'} · ${seconds(rec.duration_s)} · ${count(rec.sample_count)} rows · ${hz(rec.fs_median_hz, 2)} median` : 'Loading…'}</DialogDescription>
        </DialogHeader>
        {rec ? (
          <Tabs defaultValue="signal">
            <TabsList>
              <TabsTrigger value="signal">Signal & segments</TabsTrigger>
              <TabsTrigger value="validation">Validation</TabsTrigger>
              <TabsTrigger value="repair">Repair ({rec.derivatives.length})</TabsTrigger>
              <TabsTrigger value="spectrum">FFT / STFT</TabsTrigger>
              <TabsTrigger value="details">Details</TabsTrigger>
            </TabsList>

            <TabsContent value="signal" className="space-y-4 pt-3">
              <div className="flex flex-wrap items-center gap-3">
                {rec.derivatives.length ? (
                  <SimpleSelect className="w-80" value={derivativeId ?? 'raw'} onChange={(v) => setDerivativeId(v === 'raw' ? null : v)} options={[{ value: 'raw', label: 'Original (raw, flagged rows hidden)' }, ...rec.derivatives.map((d) => ({ value: d.derivative_id, label: `Derivative ${d.recipe_name} (${d.sample_count} rows)` }))]} />
                ) : null}
                <label className="flex items-center gap-2 text-sm"><Switch checked={segmentMode} onCheckedChange={setSegmentMode} /> <Scissors className="size-4" /> Label segments by dragging</label>
                {segmentMode ? <div className="w-64"><LabelSelect labels={labels} value={segmentLabel} onChange={setSegmentLabel} /></div> : null}
              </div>
              {rec.kind === 'continuous' && !rec.segments.length ? <Notice tone="info" title="Continuous recording">It mixes idle periods and several movements, so it is never used as one training trial. Turn on segment labelling and drag across each movement (and some idle stretches).</Notice> : null}
              {preview ? (
                <>
                  <StaticSignalChart preview={preview} channels={['ax', 'ay', 'az']} height={190} segments={overlay} selectMode={segmentMode} onSelectRange={(start, end) => segmentLabel && run('seg', () => api.recordings.addSegment(rec.recording_id, { label_id: segmentLabel, start_s: Number(start.toFixed(3)), end_s: Number(end.toFixed(3)) }), `Segment ${start.toFixed(2)}–${end.toFixed(2)} s labelled ${segmentLabel}`).then(() => reload())} />
                  <StaticSignalChart preview={preview} channels={['gx', 'gy', 'gz']} height={190} segments={overlay} selectMode={segmentMode} onSelectRange={(start, end) => segmentLabel && run('seg', () => api.recordings.addSegment(rec.recording_id, { label_id: segmentLabel, start_s: Number(start.toFixed(3)), end_s: Number(end.toFixed(3)) }), `Segment labelled ${segmentLabel}`).then(() => reload())} />
                  <p className="text-xs text-muted-foreground">
                    {preview.decimated ? `Showing ${preview.points} of ${preview.total_points} points. ` : ''}
                    {preview.markers.filter((m) => m.kind !== 'invalid_row').length ? `Dashed lines mark ${preview.markers.filter((m) => m.kind !== 'invalid_row').length} row(s) with invalid timestamps (kept in the raw file, hidden here). ` : ''}
                    Timeline starts at the first valid sample.
                  </p>
                </>
              ) : (
                <div className="h-48 animate-pulse rounded-lg bg-muted" />
              )}
              {rec.segments.length ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Label</TableHead><TableHead>Start</TableHead><TableHead>End</TableHead><TableHead>Length</TableHead><TableHead /></TableRow></TableHeader>
                  <TableBody>
                    {rec.segments.map((s) => (
                      <TableRow key={s.segment_id}>
                        <TableCell className="font-mono text-xs">{s.label_id}</TableCell>
                        <TableCell className="tabular">{seconds(s.start_s, 3)}</TableCell>
                        <TableCell className="tabular">{seconds(s.end_s, 3)}</TableCell>
                        <TableCell className="tabular">{seconds(s.duration_s, 3)}</TableCell>
                        <TableCell className="text-right"><Button size="icon-xs" variant="ghost" aria-label="Delete segment" onClick={() => run('delseg', () => api.recordings.deleteSegment(s.segment_id), 'Segment deleted').then(() => reload())}><Trash2 /></Button></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : null}
            </TabsContent>

            <TabsContent value="validation" className="space-y-4 pt-3">
              {rec.validation.issues.length ? (
                <ul className="space-y-2">
                  {rec.validation.issues.map((i) => (
                    <li key={i.code}><Notice tone={i.severity === 'error' ? 'danger' : i.severity === 'repair_required' ? 'warning' : 'info'} title={i.message} /></li>
                  ))}
                </ul>
              ) : (
                <Notice tone="info" title="No issues found">Timestamps increase, values are finite and there are enough samples.</Notice>
              )}
              <div className="grid gap-4 md:grid-cols-2">
                <Section title="Measured">
                  <KeyValue columns={1} items={[
                    ['Rows', count(rec.validation.rows.total)],
                    ['Valid samples', count(rec.validation.good_samples)],
                    ['Invalid format rows', count(rec.validation.rows.invalid_format)],
                    ['Duplicate timestamps', count(rec.validation.measured_invalid.duplicate_timestamps)],
                    ['Timestamp glitches', count(rec.validation.measured_invalid.timestamp_glitches)],
                    ['Out-of-order rows', count(rec.validation.measured_invalid.backward_steps)],
                    ['Clock segments (epochs)', count(rec.validation.epochs.length)],
                    ['Median rate', hz(rec.validation.rates.fs_median_hz, 2)],
                    ['Mean rate', hz(rec.validation.rates.fs_mean_hz, 2)],
                    ['Duration', seconds(rec.validation.duration_s, 3)],
                  ]} />
                </Section>
                <Section title="Estimated">
                  <KeyValue columns={1} items={[
                    ['Estimated dropped samples', count(rec.validation.estimated_dropped.samples)],
                    ['Gaps', count(rec.validation.estimated_dropped.gaps)],
                    ['Total gap time', seconds(rec.validation.estimated_dropped.gap_total_s, 3)],
                    ['Largest gap', rec.validation.estimated_dropped.largest_gap_ms ? `${num(rec.validation.estimated_dropped.largest_gap_ms, 1)} ms` : '—'],
                  ]} />
                  <p className="mt-2 text-xs text-muted-foreground">{rec.validation.estimated_dropped.note}</p>
                </Section>
              </div>
              {rec.validation.rows.examples.length ? (
                <Section title="Example invalid rows">
                  <ul className="space-y-1 font-mono text-xs">{rec.validation.rows.examples.map((e) => <li key={e.line}>line {e.line} · {e.reason}: {e.text}</li>)}</ul>
                </Section>
              ) : null}
              <Button variant="outline" size="sm" onClick={() => run('reval', () => api.recordings.revalidate(rec.recording_id), 'Revalidated').then(() => reload())}><RefreshCw /> Re-check file and hash</Button>
            </TabsContent>

            <TabsContent value="repair" className="space-y-4 pt-3">
              <Notice tone="info" title="Originals are never modified">A derivative is a new file in data/processed with a manifest (source hash, recipe, per-step counts). There is no timestamp sorting step.</Notice>
              <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
                <Field label="Recipe" hint={recipes.data?.find((r) => r.name === recipe)?.description}>
                  <SimpleSelect value={recipe} onChange={setRecipe} options={(recipes.data ?? []).map((r) => ({ value: r.name, label: r.name }))} />
                </Field>
                <Button onClick={() => run('der', () => api.recordings.createDerivative(rec.recording_id, recipe), 'Derivative created').then(() => reload())}><Wrench /> Create derivative</Button>
              </div>
              {rec.derivatives.length ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Recipe</TableHead><TableHead>Rows</TableHead><TableHead>Rate</TableHead><TableHead>Uniform</TableHead><TableHead>Steps</TableHead><TableHead>Created</TableHead><TableHead /></TableRow></TableHeader>
                  <TableBody>
                    {rec.derivatives.map((d) => (
                      <TableRow key={d.derivative_id}>
                        <TableCell className="font-mono text-xs">{d.recipe_name}</TableCell>
                        <TableCell className="tabular">{count(d.sample_count)}</TableCell>
                        <TableCell className="tabular text-xs">{hz(d.fs_hz, 2)}</TableCell>
                        <TableCell>{d.uniform ? 'yes' : 'no'}</TableCell>
                        <TableCell className="max-w-72 text-xs text-muted-foreground">{d.step_counts.map((s) => `${String(s.op)} −${String(s.removed ?? 0)}`).join(', ')}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{dateTime(d.created_at)}</TableCell>
                        <TableCell className="text-right"><Button size="icon-xs" variant="ghost" aria-label="Delete derivative" onClick={() => run('delder', () => api.recordings.deleteDerivative(d.derivative_id), 'Derivative deleted').then(() => reload())}><Trash2 /></Button></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : null}
            </TabsContent>

            <TabsContent value="spectrum" className="space-y-4 pt-3">
              {rec.validation_state === 'flagged' && !derivativeId ? (
                <Field label="Repair recipe applied in memory for this analysis" hint="Required because the recording is flagged. Or choose a saved derivative on the Signal tab.">
                  <SimpleSelect className="w-72" value={spectrumRecipe} onChange={setSpectrumRecipe} options={(recipes.data ?? []).map((r) => ({ value: r.name, label: r.name }))} />
                </Field>
              ) : null}
              <SpectrumPanel key={`${rec.recording_id}-${derivativeId}-${spectrumRecipe}`} target={spectrumTarget} />
            </TabsContent>

            <TabsContent value="details" className="space-y-4 pt-3">
              <div className="grid gap-4 md:grid-cols-2">
                <Section title="Metadata">
                  <div className="space-y-3">
                    <Field label="Label">
                      <LabelSelect labels={labels} value={rec.label_id} onChange={(v) => run('label', () => api.recordings.update(rec.recording_id, v ? { label_id: v } : { clear_label: true }), 'Label updated').then(() => reload())} includeDisabled allowNone />
                    </Field>
                    <Field label="Kind" hint="Continuous recordings need segments before training">
                      <SimpleSelect value={rec.kind} onChange={(v) => run('kind', () => api.recordings.update(rec.recording_id, { kind: v }), 'Updated').then(() => reload())} options={[{ value: 'trial', label: 'Trial (one gesture)' }, { value: 'continuous', label: 'Continuous (needs segments)' }]} />
                    </Field>
                    <Field label="Session">
                      <SimpleSelect value={rec.session_id ?? '__none__'} onChange={(v) => run('session', () => api.recordings.update(rec.recording_id, v === '__none__' ? { clear_session: true } : { session_id: v }), 'Session updated').then(() => reload())} options={[{ value: '__none__', label: 'No session' }, ...sessions.map((s) => ({ value: s.session_id, label: s.name }))]} />
                    </Field>
                    <Field label="Notes">
                      <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== rec.notes && run('notes', () => api.recordings.update(rec.recording_id, { notes }), 'Notes saved').then(() => reload())} />
                    </Field>
                  </div>
                </Section>
                <Section title="File & provenance">
                  <KeyValue columns={1} items={[
                    ['Source', rec.source],
                    ['Sensor', rec.sensor_id ? `${rec.sensor_id} (${rec.sensor_hand})` : '—'],
                    ['Start time', rec.start_time ? dateTime(rec.start_time) : 'unknown (not recorded in source)'],
                    ['Header / time unit', `${rec.header_alias} · ${rec.time_unit}`],
                    ['Units', `${rec.units.accel}, ${rec.units.gyro}`],
                    ['Stored at', `${rec.file.base}/${rec.file.path}`],
                    ['Size', bytes(rec.file.size_bytes)],
                    ['SHA-256', <span className="font-mono text-xs" title={rec.sha256}>{rec.sha256.slice(0, 16)}…</span>],
                    ['Datasets', rec.datasets.map((d) => d.name).join(', ') || '—'],
                  ]} />
                  <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(rec.provenance, null, 2)}</pre>
                  <Button className="mt-3" size="sm" variant="outline" onClick={() => run('dl', () => api.recordings.downloadFile(rec.recording_id))}><Download /> Download original</Button>
                </Section>
              </div>
              <Section title="Delete">
                <RadioGroup value={deleteMode} onValueChange={(v) => setDeleteMode(v as 'metadata' | 'disk')} className="space-y-2">
                  <label className="flex items-start gap-2 text-sm"><RadioGroupItem value="metadata" className="mt-0.5" /> <span><b>Remove from library</b> — deletes metadata, segments and dataset memberships; the file stays on disk.</span></label>
                  <label className="flex items-start gap-2 text-sm"><RadioGroupItem value="disk" className="mt-0.5" disabled={!rec.app_owned} /> <span><b>Delete from disk</b> — also deletes the file and its derivatives. {rec.app_owned ? 'Allowed because this app created the file.' : 'Unavailable: legacy CLI files and original reference files are never deleted by the app.'}</span></label>
                </RadioGroup>
                <Button className="mt-3" variant="outline" onClick={() => setConfirmDelete(true)}><Trash2 /> Delete…</Button>
              </Section>
            </TabsContent>
          </Tabs>
        ) : (
          <div className="h-64 animate-pulse rounded-lg bg-muted" />
        )}
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={deleteMode === 'disk' ? 'Delete the file from disk?' : 'Remove from library?'}
          description={deleteMode === 'disk' ? 'The CSV, its metadata file and any derivatives are deleted permanently.' : 'The file stays on disk; it can be recovered later with “Recover orphaned recordings”.'}
          destructive={deleteMode === 'disk'}
          confirmLabel={deleteMode === 'disk' ? 'Delete file' : 'Remove'}
          onConfirm={() => rec && run('delete', () => api.recordings.remove(rec.recording_id, deleteMode), deleteMode === 'disk' ? 'File deleted' : 'Removed from library').then(() => { onChanged(); onClose() })}
        />
      </DialogContent>
    </Dialog>
  )
}
