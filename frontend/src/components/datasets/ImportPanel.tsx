import { useRef, useState } from 'react'
import { FolderSearch, LifeBuoy, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { Field, Notice, Section } from '@/components/common/Bits'
import { LabelSelect, SimpleSelect } from '@/components/common/Pickers'
import { ToneBadge } from '@/components/common/StatusBadge'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useWorkspaceIsDemo } from '@/hooks/useAppState'
import { api } from '@/services/api'
import { bytes } from '@/lib/format'
import type { Label, Session } from '@/types/api'

export function ImportPanel({ labels, sessions, onChanged }: { labels: Label[]; sessions: Session[]; onChanged: () => void }) {
  const isDemo = useWorkspaceIsDemo()
  const known = useAsync(() => api.imports.known(), [isDemo])
  const [keys, setKeys] = useState<string[]>([])
  const [sessionMode, setSessionMode] = useState<'batch' | 'per_file' | 'none'>('batch')
  const [kind, setKind] = useState<'trial' | 'continuous'>('trial')
  const [label, setLabel] = useState<string | null>(null)
  const [timeUnit, setTimeUnit] = useState<string>('auto')
  const [session, setSession] = useState<string>('__none__')
  const [notes, setNotes] = useState('')
  const [legacy, setLegacy] = useState<Awaited<ReturnType<typeof api.imports.rescanLegacy>> | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const { run, pending } = useAction()

  if (isDemo) {
    return <Notice tone="info" title="Imports are disabled in Demo Mode">Importing brings real recordings into the real library. Turn Demo Mode off in Settings to import.</Notice>
  }

  const upload = async () => {
    const files = Array.from(fileInput.current?.files ?? [])
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      form.append('kind', kind)
      if (label) form.append('label_id', label)
      if (timeUnit !== 'auto') form.append('time_unit', timeUnit)
      if (session !== '__none__') form.append('session_id', session)
      form.append('notes', notes)
      await run('upload', () => api.imports.upload(form), (r) => `${file.name}: imported (${r.validation_state})`)
    }
    if (fileInput.current) fileInput.current.value = ''
    onChanged()
  }

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Section title="Project reference recordings" description="Copied into data/raw/imports with SHA-256 provenance. The originals in imu_capture/ are never modified.">
        <div className="space-y-4">
          <Table>
            <TableHeader>
              <TableRow><TableHead className="w-8" /><TableHead>File</TableHead><TableHead>Size</TableHead><TableHead>Label hint</TableHead><TableHead>Status</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {(known.data ?? []).map((s) => (
                <TableRow key={s.key}>
                  <TableCell><Checkbox disabled={!s.exists || Boolean(s.imported_recording_id)} checked={keys.includes(s.key)} onCheckedChange={(v) => setKeys(v ? [...keys, s.key] : keys.filter((k) => k !== s.key))} aria-label={`Select ${s.key}`} /></TableCell>
                  <TableCell>
                    <div className="font-mono text-xs">{s.path}</div>
                    <div className="text-xs text-muted-foreground">{s.description}</div>
                  </TableCell>
                  <TableCell className="tabular text-xs">{bytes(s.size_bytes)}</TableCell>
                  <TableCell className="font-mono text-xs">{s.label_hint}</TableCell>
                  <TableCell>{!s.exists ? <ToneBadge tone="danger">missing</ToneBadge> : s.imported_recording_id ? <ToneBadge tone="success">imported</ToneBadge> : <ToneBadge tone="muted">not imported</ToneBadge>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Field label="Sessions" hint="The three files were recorded minutes apart, so one session is the conservative default (it avoids leakage across files).">
            <SimpleSelect value={sessionMode} onChange={setSessionMode} options={[{ value: 'batch', label: 'One session for the batch' }, { value: 'per_file', label: 'One session per file' }, { value: 'none', label: 'No session' }]} />
          </Field>
          <Button disabled={!keys.length || pending === 'known'} onClick={() => run('known', () => api.imports.importKnown(keys, sessionMode), (r) => `Imported ${r.imported.length}, skipped ${r.skipped.length}`).then(() => { setKeys([]); void known.reload(); onChanged() })}>Import selected</Button>
          <p className="text-xs text-muted-foreground">They are imported as continuous recordings (about two movements plus idle each) and need labelled segments before training. They contain 1–3 rows with corrupted timestamps, so they will show “Needs repair”.</p>
        </div>
      </Section>

      <Section title="Upload CSV" description="Headers t_us or time_us (device microseconds), or time with an explicit unit, plus ax, ay, az (g) and gx, gy, gz (°/s)">
        <div className="space-y-3">
          <Input ref={fileInput} type="file" accept=".csv,text/csv" multiple />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Kind"><SimpleSelect value={kind} onChange={setKind} options={[{ value: 'trial', label: 'Trial (one gesture)' }, { value: 'continuous', label: 'Continuous (needs segments)' }]} /></Field>
            <Field label="Label"><LabelSelect labels={labels} value={label} onChange={setLabel} allowNone includeDisabled /></Field>
            <Field label="Unit of a 'time' column" hint="Only used for a column named time; never guessed"><SimpleSelect value={timeUnit} onChange={setTimeUnit} options={[{ value: 'auto', label: 't_us / time_us file' }, { value: 's', label: 'seconds' }, { value: 'ms', label: 'milliseconds' }, { value: 'us', label: 'microseconds' }]} /></Field>
            <Field label="Session"><SimpleSelect value={session} onChange={setSession} options={[{ value: '__none__', label: 'No session' }, ...sessions.map((s) => ({ value: s.session_id, label: s.name }))]} /></Field>
          </div>
          <Field label="Notes"><Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          <Button disabled={pending === 'upload'} onClick={() => void upload()}><Upload /> Validate & import</Button>
        </div>
      </Section>

      <Section title="Legacy CLI trials" description="Registers data/<label>_<number>.csv files from src/collect.py in place (nothing is copied or renamed)">
        <div className="space-y-3">
          <Button variant="outline" onClick={() => run('legacy', () => api.imports.rescanLegacy(), (r) => `${r.registered.length} new, ${r.changed.length} changed, ${r.unchanged.length} unchanged`).then((r) => { if (r) setLegacy(r); onChanged() })}><FolderSearch /> Scan data/*.csv</Button>
          {legacy ? (
            <div className="text-sm text-muted-foreground">
              Folder {legacy.folder}: {legacy.registered.length} registered, {legacy.changed.length} changed, {legacy.unchanged.length} unchanged, {legacy.skipped.length} skipped.
              {legacy.skipped.length ? <ul className="mt-1 list-disc pl-5 text-xs">{legacy.skipped.map((s) => <li key={s.file}>{s.file}: {s.reason}</li>)}</ul> : null}
            </div>
          ) : null}
          <p className="text-xs text-muted-foreground">Legacy trials have no session information, so evaluation groups them by recording and warns that results may be optimistic. Assign sessions in the Recordings tab when you know them.</p>
        </div>
      </Section>

      <Section title="Recovery" description="Re-register app recordings whose metadata row was removed (reads their .meta.json files)">
        <Button variant="outline" onClick={() => run('recover', () => api.recordings.recover(), (r) => `Recovered ${r.recovered.length} recording(s)`).then(() => onChanged())}><LifeBuoy /> Recover orphaned recordings</Button>
      </Section>
    </div>
  )
}
