import { useState } from 'react'
import { GitMerge, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Field } from '@/components/common/Bits'
import { LabelSelect } from '@/components/common/Pickers'
import { ToneBadge } from '@/components/common/StatusBadge'
import { useAction } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { Label } from '@/types/api'

export function LabelManager({ labels, onChanged }: { labels: Label[]; onChanged: () => void }) {
  const { run } = useAction()
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')
  const [names, setNames] = useState<Record<string, string>>({})
  const [mergeSource, setMergeSource] = useState<string | null>(null)
  const [mergeTarget, setMergeTarget] = useState<string | null>(null)
  const [confirmMerge, setConfirmMerge] = useState(false)
  const [renameTarget, setRenameTarget] = useState<{ id: string; next: string } | null>(null)

  const act = async (key: string, fn: () => Promise<unknown>, message?: string) => {
    await run(key, fn, message)
    onChanged()
  }

  return (
    <div className="space-y-5">
      <Table>
        <TableHeader>
          <TableRow><TableHead>ID</TableHead><TableHead>Display name</TableHead><TableHead>Use</TableHead><TableHead>Enabled</TableHead><TableHead /></TableRow>
        </TableHeader>
        <TableBody>
          {labels.map((label) => (
            <TableRow key={label.label_id}>
              <TableCell className="font-mono text-xs">
                {label.label_id} {label.builtin ? <ToneBadge tone="muted" className="ml-1">built-in</ToneBadge> : null} {label.is_idle ? <ToneBadge tone="info" className="ml-1">never acts</ToneBadge> : null}
              </TableCell>
              <TableCell>
                <Input
                  className="h-8"
                  value={names[label.label_id] ?? label.display_name}
                  onChange={(e) => setNames({ ...names, [label.label_id]: e.target.value })}
                  onBlur={() => {
                    const next = names[label.label_id]
                    if (next !== undefined && next.trim() && next !== label.display_name) void act('name', () => api.labels.update(label.label_id, { display_name: next.trim() }), 'Display name updated')
                  }}
                />
              </TableCell>
              <TableCell className="tabular text-xs text-muted-foreground">{label.recordings} rec · {label.segments} seg</TableCell>
              <TableCell>
                <Switch checked={label.enabled} disabled={label.is_idle} onCheckedChange={(v) => void act('enable', () => api.labels.update(label.label_id, { enabled: v }))} />
              </TableCell>
              <TableCell className="text-right">
                {!label.builtin ? (
                  <div className="flex justify-end gap-1">
                    <Button size="xs" variant="ghost" onClick={() => setRenameTarget({ id: label.label_id, next: label.label_id })}>Rename ID</Button>
                    <Button size="icon-xs" variant="ghost" aria-label="Delete label" disabled={label.recordings + label.segments > 0} onClick={() => void act('del', () => api.labels.remove(label.label_id), 'Label deleted')}><Trash2 /></Button>
                  </div>
                ) : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="grid gap-3 rounded-lg border border-border/70 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <Field label="New label ID" hint="Lowercase letters, digits and underscores, e.g. thumbs_up or char_a">
          <Input value={newId} onChange={(e) => setNewId(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))} maxLength={48} />
        </Field>
        <Field label="Display name">
          <Input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={80} />
        </Field>
        <Button
          disabled={!newId || !newName}
          onClick={() =>
            void act('create', () => api.labels.create({ label_id: newId, display_name: newName }), 'Label created').then(() => {
              setNewId('')
              setNewName('')
            })
          }
        >
          <Plus /> Add label
        </Button>
      </div>

      <div className="grid gap-3 rounded-lg border border-border/70 p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <Field label="Merge label" hint="Moves its recordings and segments; never done automatically (Flick Up is not Swipe Up)">
          <LabelSelect labels={labels} value={mergeSource} onChange={setMergeSource} includeDisabled />
        </Field>
        <Field label="Into">
          <LabelSelect labels={labels} value={mergeTarget} onChange={setMergeTarget} includeDisabled />
        </Field>
        <Button variant="outline" disabled={!mergeSource || !mergeTarget || mergeSource === mergeTarget} onClick={() => setConfirmMerge(true)}><GitMerge /> Merge…</Button>
      </div>

      <ConfirmDialog
        open={confirmMerge}
        onOpenChange={setConfirmMerge}
        title={`Merge ${mergeSource} into ${mergeTarget}?`}
        description="Every recording and segment labelled with the first label will be relabelled. Mappings for it are removed. The change is logged and cannot be undone automatically."
        destructive
        confirmLabel="Merge labels"
        onConfirm={() => mergeSource && mergeTarget && void act('merge', () => api.labels.merge(mergeSource, mergeTarget), 'Labels merged')}
      />
      <ConfirmDialog
        open={renameTarget !== null}
        onOpenChange={(open) => !open && setRenameTarget(null)}
        title="Rename label ID"
        description="Rewrites every recording, segment and mapping that uses this custom label."
        confirmLabel="Rename"
        onConfirm={() => renameTarget && renameTarget.next !== renameTarget.id && void act('rename', () => api.labels.rename(renameTarget.id, renameTarget.next), 'Label renamed')}
      >
        <Input value={renameTarget?.next ?? ''} onChange={(e) => renameTarget && setRenameTarget({ ...renameTarget, next: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} />
      </ConfirmDialog>
    </div>
  )
}
