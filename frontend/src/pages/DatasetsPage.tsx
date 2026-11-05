import { useMemo, useState } from 'react'
import { FolderPlus, Search, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Empty, Section } from '@/components/common/Bits'
import { PageHeader } from '@/components/common/PageHeader'
import { LabelSelect, SimpleSelect } from '@/components/common/Pickers'
import { ToneBadge, ValidationBadge } from '@/components/common/StatusBadge'
import { DatasetPanel } from '@/components/datasets/DatasetPanel'
import { ImportPanel } from '@/components/datasets/ImportPanel'
import { LabelManager } from '@/components/datasets/LabelManager'
import { RecordingDetailDialog } from '@/components/datasets/RecordingDetailDialog'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useWorkspaceIsDemo } from '@/hooks/useAppState'
import { api } from '@/services/api'
import { dateTime, hz, seconds, shortId } from '@/lib/format'

const ALL = '__all__'

export function DatasetsPage() {
  const isDemo = useWorkspaceIsDemo()
  const [q, setQ] = useState('')
  const [label, setLabel] = useState<string | null>(null)
  const [kind, setKind] = useState<string>(ALL)
  const [source, setSource] = useState<string>(ALL)
  const [state, setState] = useState<string>(ALL)
  const [selected, setSelected] = useState<string[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [targetDataset, setTargetDataset] = useState<string | null>(null)
  const [targetSession, setTargetSession] = useState<string | null>(null)
  const { run } = useAction()
  const params = { q: q || undefined, label_id: label ?? undefined, kind: kind === ALL ? undefined : kind, source: source === ALL ? undefined : source, state: state === ALL ? undefined : state, limit: 500 }
  const recordings = useAsync(() => api.recordings.list(params), [q, label, kind, source, state, isDemo])
  const labels = useAsync(() => api.labels.list(), [isDemo])
  const sessions = useAsync(() => api.sessions.list(), [isDemo])
  const datasets = useAsync(() => api.datasets.list(), [isDemo])
  const items = recordings.data?.items ?? []
  const allSelected = items.length > 0 && items.every((r) => selected.includes(r.recording_id))
  const refreshAll = () => {
    void recordings.reload()
    void labels.reload()
    void sessions.reload()
    void datasets.reload()
  }
  const datasetOptions = useMemo(() => (datasets.data ?? []).map((d) => ({ value: d.dataset_id, label: d.name })), [datasets.data])

  return (
    <>
      <PageHeader title="Dataset Manager" description="Recordings, labelled segments, validation and repair, imports, and the datasets used for training. Datasets reference recordings; raw files are never duplicated or rewritten." />
      <Tabs defaultValue="recordings">
        <TabsList className="mb-4">
          <TabsTrigger value="recordings">Recordings ({recordings.data?.total ?? 0})</TabsTrigger>
          <TabsTrigger value="datasets">Datasets ({datasets.data?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="import">Import</TabsTrigger>
          <TabsTrigger value="labels">Labels & sessions</TabsTrigger>
        </TabsList>

        <TabsContent value="recordings">
          <Section title="Recordings" description={isDemo ? 'Demo workspace — simulated recordings only' : 'Real recordings'} contentClassName="space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_12rem_10rem_10rem_10rem]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-9" placeholder="Search ID, notes, sensor, file…" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <LabelSelect labels={labels.data ?? []} value={label} onChange={setLabel} allowNone noneLabel="Any label" includeDisabled placeholder="Any label" />
              <SimpleSelect value={kind} onChange={setKind} options={[{ value: ALL, label: 'Any kind' }, { value: 'trial', label: 'Trials' }, { value: 'continuous', label: 'Continuous' }]} />
              <SimpleSelect value={source} onChange={setSource} options={[{ value: ALL, label: 'Any source' }, { value: 'live', label: 'Live' }, { value: 'demo', label: 'Demo' }, { value: 'import', label: 'Imported' }, { value: 'legacy_cli', label: 'Legacy CLI' }]} />
              <SimpleSelect value={state} onChange={setState} options={[{ value: ALL, label: 'Any validation' }, { value: 'valid', label: 'Valid' }, { value: 'flagged', label: 'Needs repair' }, { value: 'invalid', label: 'Invalid' }]} />
            </div>
            {selected.length ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
                <span className="font-medium">{selected.length} selected</span>
                <div className="w-52"><SimpleSelect value={targetDataset} onChange={setTargetDataset} options={datasetOptions} placeholder="Choose dataset" /></div>
                <Button size="sm" disabled={!targetDataset} onClick={() => run('add', () => api.datasets.addMembers(targetDataset as string, selected.map((id) => ({ recording_id: id }))), (r) => `Added ${r.added}${r.skipped.length ? `, skipped ${r.skipped.length} (${r.skipped[0].reason})` : ''}`).then(() => void datasets.reload())}><FolderPlus /> Add to dataset</Button>
                <div className="ml-4 w-52"><SimpleSelect value={targetSession} onChange={setTargetSession} options={(sessions.data ?? []).map((s) => ({ value: s.session_id, label: s.name }))} placeholder="Choose session" /></div>
                <Button size="sm" variant="outline" disabled={!targetSession} onClick={() => run('assign', () => api.sessions.assign(targetSession, selected), (r) => `Updated ${r.updated} recording(s)`).then(() => void recordings.reload())}><Users /> Assign session</Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>Clear</Button>
              </div>
            ) : null}
            {items.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"><Checkbox checked={allSelected} onCheckedChange={(v) => setSelected(v ? items.map((r) => r.recording_id) : [])} aria-label="Select all" /></TableHead>
                    <TableHead>Recording</TableHead><TableHead>Label</TableHead><TableHead>Kind</TableHead><TableHead>Source</TableHead><TableHead>Sensor</TableHead><TableHead>Duration</TableHead><TableHead>Samples</TableHead><TableHead>Rate</TableHead><TableHead>Recorded</TableHead><TableHead>Validation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((r) => (
                    <TableRow key={r.recording_id} className="cursor-pointer" onClick={() => setOpenId(r.recording_id)}>
                      <TableCell onClick={(e) => e.stopPropagation()}><Checkbox checked={selected.includes(r.recording_id)} onCheckedChange={(v) => setSelected(v ? [...selected, r.recording_id] : selected.filter((id) => id !== r.recording_id))} aria-label={`Select ${r.recording_id}`} /></TableCell>
                      <TableCell className="font-mono text-xs" title={r.recording_id}>{shortId(r.recording_id)}{r.segment_count ? <span className="ml-1 text-muted-foreground">· {r.segment_count} seg</span> : null}</TableCell>
                      <TableCell className="font-mono text-xs">{r.label_id ?? '—'}</TableCell>
                      <TableCell className="text-xs">{r.kind}</TableCell>
                      <TableCell className="text-xs">{r.source === 'legacy_cli' ? 'legacy CLI' : r.source}</TableCell>
                      <TableCell className="text-xs">{r.sensor_id ?? '—'}</TableCell>
                      <TableCell className="tabular text-xs">{seconds(r.duration_s)}</TableCell>
                      <TableCell className="tabular text-xs">{r.sample_count}</TableCell>
                      <TableCell className="tabular text-xs">{hz(r.fs_median_hz)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground" title={`Added ${dateTime(r.created_at)}`}>{r.start_time ? dateTime(r.start_time) : <span>unknown <span className="text-muted-foreground/70">(added {dateTime(r.created_at)})</span></span>}</TableCell>
                      <TableCell className="space-x-1"><ValidationBadge state={r.validation_state} />{r.source_changed ? <ToneBadge tone="danger">changed</ToneBadge> : null}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty title="No recordings match" description="Record trials in the Gesture Recorder or import files on the Import tab." />
            )}
          </Section>
        </TabsContent>

        <TabsContent value="datasets">
          <DatasetPanel datasets={datasets.data ?? []} onChanged={() => void datasets.reload()} onOpenRecording={setOpenId} />
        </TabsContent>

        <TabsContent value="import">
          <ImportPanel labels={labels.data ?? []} sessions={sessions.data ?? []} onChanged={refreshAll} />
        </TabsContent>

        <TabsContent value="labels">
          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <Section title="Labels" description="Built-in IDs are fixed so legacy files and models keep working. Rename and merge are explicit and logged.">
              <LabelManager labels={labels.data ?? []} onChanged={() => void labels.reload()} />
            </Section>
            <Section title="Sessions" description="A session is one sensor mounting/setup; evaluation never splits a session across train and test">
              {sessions.data?.length ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Recordings</TableHead><TableHead>Created</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {sessions.data.map((s) => (
                      <TableRow key={s.session_id}>
                        <TableCell>
                          <Input className="h-8" defaultValue={s.name} onBlur={(e) => e.target.value !== s.name && run('rename', () => api.sessions.update(s.session_id, { name: e.target.value }), 'Session renamed')} />
                        </TableCell>
                        <TableCell className="tabular">{s.recordings}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{dateTime(s.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <Empty title="No sessions yet" description="The recorder creates one automatically; start a new one whenever you re-mount the sensor." />
              )}
            </Section>
          </div>
        </TabsContent>
      </Tabs>
      <RecordingDetailDialog recordingId={openId} labels={labels.data ?? []} sessions={sessions.data ?? []} onClose={() => setOpenId(null)} onChanged={() => void recordings.reload()} />
    </>
  )
}
