import { useEffect, useState } from 'react'
import { Download, Plus, Trash2, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Empty, Field, Notice, Section } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { SimpleSelect } from '@/components/common/Pickers'
import { ToneBadge, ValidationBadge } from '@/components/common/StatusBadge'
import { DistributionBars } from '@/components/charts/Bars'
import { useAction, useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { hz, seconds, shortId } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DatasetDetail, DatasetSummary } from '@/types/api'

export function DatasetPanel({ datasets, onChanged, onOpenRecording }: { datasets: DatasetSummary[]; onChanged: () => void; onOpenRecording: (id: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [recipe, setRecipe] = useState('default-v1')
  const [confirmRepair, setConfirmRepair] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [removeIds, setRemoveIds] = useState<number[]>([])
  const { run } = useAction()
  const detail = useAsync<DatasetDetail | null>(() => (selected ? api.datasets.get(selected) : Promise.resolve(null)), [selected])
  const ds = detail.data ?? null

  useEffect(() => {
    if (!selected && datasets.length) setSelected(datasets[0].dataset_id)
    if (selected && !datasets.some((d) => d.dataset_id === selected)) setSelected(datasets[0]?.dataset_id ?? null)
  }, [datasets])

  const refresh = async () => {
    await detail.reload()
    onChanged()
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[20rem_1fr]">
      <Section title="Datasets" description="Definitions that reference recordings (no file copies)">
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input placeholder="New dataset name" value={name} onChange={(e) => setName(e.target.value)} />
            <Button size="icon" aria-label="Create dataset" disabled={!name.trim()} onClick={() => run('create', () => api.datasets.create(name.trim()), 'Dataset created').then((d) => { setName(''); if (d) setSelected(d.dataset_id); onChanged() })}><Plus /></Button>
          </div>
          {datasets.length ? (
            <ul className="space-y-1.5">
              {datasets.map((d) => (
                <li key={d.dataset_id}>
                  <button className={cn('w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors', d.dataset_id === selected ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted/50')} onClick={() => setSelected(d.dataset_id)}>
                    <div className="font-medium">{d.name}</div>
                    <div className="text-xs text-muted-foreground">{d.members} member(s) · {Object.keys(d.distribution).length} label(s)</div>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="No datasets" description="Create one, then add recordings from the Recordings tab." />
          )}
        </div>
      </Section>

      {ds ? (
        <div className="space-y-5">
          <Section
            title={ds.name}
            description={`${ds.member_count} member(s) · created ${new Date(ds.created_at).toLocaleDateString()}`}
            actions={
              <>
                <Button size="sm" variant="outline" onClick={() => run('export', () => api.datasets.export(ds.dataset_id), 'Export downloaded (also saved under data/exports)')}><Download /> Export ZIP</Button>
                <Button size="icon-sm" variant="ghost" aria-label="Delete dataset" onClick={() => setConfirmDelete(true)}><Trash2 /></Button>
              </>
            }
          >
            <div className="grid gap-5 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-sm font-medium">Class distribution</div>
                <DistributionBars distribution={ds.by_label} />
                <p className="mt-3 text-xs text-muted-foreground">Sampling rates: {ds.rate_check.min_hz ? `${hz(ds.rate_check.min_hz)} – ${hz(ds.rate_check.max_hz)}` : 'not measured'}{ds.rate_check.compatible ? '' : ' (mixed — flagged)'}</p>
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium">Training readiness</div>
                {ds.readiness.ready ? <ToneBadge tone="success">Ready to train</ToneBadge> : <ToneBadge tone="danger">Not ready</ToneBadge>}
                {ds.readiness.problems.map((p) => <Notice key={p.code} tone="danger" title={p.message} />)}
                {ds.readiness.warnings.map((w, i) => <Notice key={`${w.code}-${i}`} tone="warning" title={w.message} />)}
                {ds.members.some((m) => m.needs_repair) ? (
                  <div className="flex flex-wrap items-end gap-2 pt-2">
                    <Field label="Repair recipe for flagged members"><SimpleSelect className="w-56" value={recipe} onChange={setRecipe} options={[{ value: 'default-v1', label: 'default-v1' }, { value: 'default-resampled-v1', label: 'default-resampled-v1' }, { value: 'legacy-analyze-v1', label: 'legacy-analyze-v1' }]} /></Field>
                    <Button variant="outline" onClick={() => setConfirmRepair(true)}><Wrench /> Apply…</Button>
                  </div>
                ) : null}
              </div>
            </div>
          </Section>
          <Section title="Members" actions={removeIds.length ? <Button size="sm" variant="outline" onClick={() => run('rm', () => api.datasets.removeMembers(ds.dataset_id, removeIds), 'Removed from dataset').then(() => { setRemoveIds([]); void refresh() })}><Trash2 /> Remove {removeIds.length}</Button> : null}>
            {ds.members.length ? (
              <Table>
                <TableHeader><TableRow><TableHead className="w-8" /><TableHead>Recording</TableHead><TableHead>Label</TableHead><TableHead>Type</TableHead><TableHead>Length</TableHead><TableHead>Session</TableHead><TableHead>Validation</TableHead><TableHead>Uses</TableHead></TableRow></TableHeader>
                <TableBody>
                  {ds.members.map((m) => (
                    <TableRow key={m.member_id}>
                      <TableCell><input type="checkbox" className="accent-primary" checked={removeIds.includes(m.member_id)} onChange={(e) => setRemoveIds(e.target.checked ? [...removeIds, m.member_id] : removeIds.filter((id) => id !== m.member_id))} aria-label="Select member" /></TableCell>
                      <TableCell><button className="font-mono text-xs text-primary hover:underline" onClick={() => onOpenRecording(m.recording_id)}>{shortId(m.recording_id)}</button></TableCell>
                      <TableCell className="font-mono text-xs">{m.label_id}</TableCell>
                      <TableCell className="text-xs">{m.segment ? `segment ${m.segment.start_s.toFixed(2)}–${m.segment.end_s.toFixed(2)} s` : m.kind}</TableCell>
                      <TableCell className="tabular text-xs">{seconds(m.duration_s)}</TableCell>
                      <TableCell className="text-xs">{m.session_id ? shortId(m.session_id) : <span className="text-muted-foreground">none</span>}</TableCell>
                      <TableCell><ValidationBadge state={m.validation_state} /></TableCell>
                      <TableCell className="text-xs">{m.derivative_id ? 'derivative' : m.needs_repair ? <span className="text-destructive">needs repair</span> : 'raw'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Empty title="No members" description="Select recordings on the Recordings tab and choose “Add to dataset”." />
            )}
          </Section>
        </div>
      ) : (
        <Empty title="Select or create a dataset" />
      )}
      <ConfirmDialog open={confirmRepair} onOpenChange={setConfirmRepair} title={`Apply ${recipe} to flagged members?`} description="Creates one derivative per flagged recording and points the members at it. Original files are not modified." confirmLabel="Create derivatives" onConfirm={() => ds && run('repair', () => api.datasets.repairFlagged(ds.dataset_id, recipe), (r) => `${r.derivatives_created} derivative(s) created`).then(() => refresh())} />
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete this dataset definition?" description="Only the dataset is deleted. Its recordings stay in the library and on disk." destructive confirmLabel="Delete dataset" onConfirm={() => ds && run('del', () => api.datasets.remove(ds.dataset_id), 'Dataset deleted').then(() => { setSelected(null); onChanged() })} />
    </div>
  )
}
