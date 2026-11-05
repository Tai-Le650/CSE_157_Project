import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, FileJson, Play, ShieldCheck, Square, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Empty, Field, KeyValue, Notice, NumberInput, Section, Stat } from '@/components/common/Bits'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { PageHeader } from '@/components/common/PageHeader'
import { SimpleSelect } from '@/components/common/Pickers'
import { ToneBadge } from '@/components/common/StatusBadge'
import { ConfusionMatrix } from '@/components/charts/Bars'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState, useWorkspaceIsDemo } from '@/hooks/useAppState'
import { useHosted } from '@/hooks/useSessionInfo'
import { api } from '@/services/api'
import { dateTime, num, pct } from '@/lib/format'
import type { Evaluation, ModelDetail, ModelSummary } from '@/types/api'

function EvaluationView({ evaluation, trainingData }: { evaluation: Evaluation | undefined; trainingData?: Record<string, unknown> }) {
  if (!evaluation) return <p className="text-sm text-muted-foreground">No evaluation recorded.</p>
  if (evaluation.status !== 'evaluated') {
    return (
      <div className="space-y-3">
        <Notice tone="warning" title={evaluation.status === 'insufficient_grouped_data' ? 'Insufficient grouped data — no metrics reported' : evaluation.status === 'not_recorded' ? 'Evaluation not recorded' : evaluation.status}>
          {evaluation.message}
        </Notice>
        {evaluation.groups_per_label ? (
          <KeyValue items={Object.entries(evaluation.groups_per_label).map(([label, groups]) => [label, `${groups} group(s)${evaluation.classes_lacking_groups?.includes(label) ? ' — needs ≥ 2' : ''}`])} />
        ) : null}
      </div>
    )
  }
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Accuracy" value={pct(evaluation.accuracy)} hint={`${evaluation.windows} windows`} />
        <Stat label="Macro precision" value={num(evaluation.macro?.precision, 3)} />
        <Stat label="Macro recall" value={num(evaluation.macro?.recall, 3)} />
        <Stat label="Macro F1" value={num(evaluation.macro?.f1, 3)} />
      </div>
      <p className="text-xs text-muted-foreground">
        {evaluation.method}, {evaluation.n_splits} folds over {evaluation.groups_total} independent groups ({String(trainingData?.group_kind ?? 'session')}). Windows from one session or recording never appear in both training and test folds.
        {trainingData?.group_kind !== 'session' ? ' Some members had no session and were grouped by recording, so results may be optimistic.' : ''}
      </p>
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-medium">Per class</div>
          <Table>
            <TableHeader><TableRow><TableHead>Label</TableHead><TableHead>Precision</TableHead><TableHead>Recall</TableHead><TableHead>F1</TableHead><TableHead>Support</TableHead></TableRow></TableHeader>
            <TableBody>
              {Object.entries(evaluation.per_class ?? {}).map(([label, m]) => (
                <TableRow key={label}>
                  <TableCell className="font-mono text-xs">{label}</TableCell>
                  <TableCell className="tabular">{num(m.precision, 3)}</TableCell>
                  <TableCell className="tabular">{num(m.recall, 3)}</TableCell>
                  <TableCell className="tabular">{num(m.f1, 3)}</TableCell>
                  <TableCell className="tabular">{m.support}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div>
          <div className="mb-2 text-sm font-medium">Confusion matrix (summed over folds)</div>
          {evaluation.confusion_matrix ? <ConfusionMatrix labels={evaluation.confusion_matrix.labels} matrix={evaluation.confusion_matrix.matrix} /> : null}
        </div>
      </div>
      {evaluation.folds?.length ? (
        <div>
          <div className="mb-2 text-sm font-medium">Folds</div>
          <Table>
            <TableHeader><TableRow><TableHead>Fold</TableHead><TableHead>Train windows</TableHead><TableHead>Test windows</TableHead><TableHead>Test groups</TableHead><TableHead>Accuracy</TableHead></TableRow></TableHeader>
            <TableBody>
              {evaluation.folds.map((f) => (
                <TableRow key={f.fold}>
                  <TableCell>{f.fold}</TableCell>
                  <TableCell className="tabular">{f.train_windows}</TableCell>
                  <TableCell className="tabular">{f.test_windows}</TableCell>
                  <TableCell className="max-w-64 truncate font-mono text-xs">{f.test_groups.join(', ')}</TableCell>
                  <TableCell className="tabular">{pct(f.accuracy)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  )
}

export function TrainingPage() {
  const { training } = useAppState()
  const isDemo = useWorkspaceIsDemo()
  const { hosted, limits } = useHosted()
  const online = hosted && limits ? limits : null
  const datasets = useAsync(() => api.datasets.list(), [isDemo])
  const features = useAsync(() => api.training.features(), [])
  const models = useAsync(() => api.models.list(), [isDemo, training?.recent[0]?.status])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [feature, setFeature] = useState<string>('stats-spectral-v1')
  const [windowS, setWindowS] = useState<number>(1.0)
  const [augment, setAugment] = useState(true)
  const [trees, setTrees] = useState(300)
  const [maxDepth, setMaxDepth] = useState<number>(0)
  const [leaf, setLeaf] = useState(1)
  const [folds, setFolds] = useState(5)
  const [jobs, setJobs] = useState(2)
  const [name, setName] = useState('')
  const [viewModel, setViewModel] = useState<ModelDetail | null>(null)
  const [trustTarget, setTrustTarget] = useState<ModelSummary | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ModelSummary | null>(null)
  const { run, pending } = useAction()
  const active = training?.active_job ?? null
  const lastDone = training?.recent.find((j) => j.status === 'done' || j.status === 'failed') ?? null
  const datasetDetail = useAsync(() => (datasetId ? api.datasets.get(datasetId) : Promise.resolve(null)), [datasetId])

  useEffect(() => {
    if (!datasetId && datasets.data?.length) setDatasetId(datasets.data[0].dataset_id)
  }, [datasets.data])

  useEffect(() => {
    const info = features.data?.find((f) => f.version === feature)
    if (info) setWindowS(info.default_window_s)
  }, [feature, features.data])

  const featureOptions = useMemo(() => [
    ...(features.data ?? []).map((f) => ({ value: f.version, label: `${f.version} (${f.feature_count} features)` })),
    { value: 'airwriting-dtw-v1', label: 'airwriting-dtw-v1 (experimental DTW)' },
  ], [features.data])
  const featureInfo = features.data?.find((f) => f.version === feature)
  const effectiveTrees = online ? Math.min(trees, online.max_trees) : trees
  const effectiveFolds = online ? Math.min(folds, online.max_folds) : folds
  const effectiveJobs = online ? 1 : jobs

  const start = () =>
    run('train', () =>
      api.training.start({
        dataset_id: datasetId,
        feature_version: feature,
        window_s: feature === 'airwriting-dtw-v1' ? null : windowS,
        augment,
        n_estimators: effectiveTrees,
        max_depth: maxDepth > 0 ? maxDepth : null,
        min_samples_leaf: leaf,
        n_splits_max: effectiveFolds,
        n_jobs: effectiveJobs,
        name: name || null,
      }), 'Training started in a background process')

  return (
    <>
      <PageHeader title="Model Training" description="Train a RandomForest on versioned features. Training runs in a separate process, so live acquisition stays responsive." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,26rem)_1fr]">
        <Section title="New training job">
          <div className="space-y-4">
            <Field label="Dataset">
              <SimpleSelect value={datasetId} onChange={setDatasetId} options={(datasets.data ?? []).map((d) => ({ value: d.dataset_id, label: `${d.name} (${d.members})` }))} placeholder="No datasets yet" />
            </Field>
            {datasetDetail.data ? (
              datasetDetail.data.readiness.ready ? <ToneBadge tone="success">Dataset ready</ToneBadge> : <Notice tone="warning" title="Dataset not ready">{datasetDetail.data.readiness.problems.map((p) => p.message).join(' · ')}</Notice>
            ) : null}
            <Field label="Feature pipeline" hint={featureInfo?.description ?? (feature === 'airwriting-dtw-v1' ? '1-nearest-neighbour DTW on gyro sequences per trial. Experimental; used from the Command Mapping page panel.' : undefined)}>
              <SimpleSelect value={feature} onChange={setFeature} options={featureOptions} />
            </Field>
            {feature !== 'airwriting-dtw-v1' ? (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Window (s)" hint="Fixed for the model; recognition uses the same length"><NumberInput value={windowS} onChange={setWindowS} min={0.3} max={3} step={0.1} disabled={feature === 'summary-60-v1'} /></Field>
                <Field label="Shift augmentation" hint="±0.12 s and ±0.25 s around each peak">
                  <div className="flex h-9 items-center"><Switch checked={augment} onCheckedChange={setAugment} disabled={feature !== 'stats-spectral-v1'} /></div>
                </Field>
                <Field label="Trees"><NumberInput value={effectiveTrees} onChange={(v) => setTrees(Math.round(v))} min={10} max={online?.max_trees ?? 2000} /></Field>
                <Field label="Max depth" hint="0 = unlimited"><NumberInput value={maxDepth} onChange={(v) => setMaxDepth(Math.round(v))} min={0} max={100} /></Field>
                <Field label="Min samples per leaf"><NumberInput value={leaf} onChange={(v) => setLeaf(Math.round(v))} min={1} max={50} /></Field>
                <Field label="Max folds"><NumberInput value={effectiveFolds} onChange={(v) => setFolds(Math.round(v))} min={2} max={online?.max_folds ?? 10} /></Field>
                <Field label="CPU cores" hint={online ? 'Always 1 in the online demo' : 'Keep low while streaming'}><NumberInput value={effectiveJobs} onChange={(v) => setJobs(Math.round(v))} min={1} max={8} disabled={Boolean(online)} /></Field>
              </div>
            ) : null}
            {online ? (
              <Notice title="Online demo limits">
                Forests are capped at {online.max_trees} trees and {online.max_folds} folds on 1 CPU core, and the free server trains one model at a time for all visitors, so training can take a few minutes.
              </Notice>
            ) : null}
            <Field label="Model name (optional)"><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
            <Button disabled={!datasetId || Boolean(active) || pending === 'train'} onClick={() => void start()}><Play /> Train model</Button>
          </div>
        </Section>

        <div className="space-y-5">
          <Section title="Job progress" actions={active ? <Button size="sm" variant="outline" onClick={() => run('cancel', () => api.training.cancel(active.job_id), 'Training cancelled')}><Square /> Cancel</Button> : null}>
            {active ? (
              <div className="space-y-2">
                <div className="flex justify-between text-sm"><span className="font-medium capitalize">{active.stage.replace(/_/g, ' ')}</span><span className="tabular">{pct(active.progress, 0)}</span></div>
                <Progress value={active.progress * 100} />
                <p className="text-sm text-muted-foreground">{active.message}</p>
              </div>
            ) : lastDone ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  {lastDone.status === 'done' ? <CheckCircle2 className="size-4 text-success" /> : null}
                  Last job {lastDone.status} · {dateTime(lastDone.finished_at)}
                </div>
                <p className="text-muted-foreground">{lastDone.message}</p>
              </div>
            ) : (
              <Empty title="No training jobs yet" />
            )}
          </Section>
          {lastDone?.status === 'done' && !active ? (
            <Section title="Latest results" description={lastDone.model_id ? `Model ${lastDone.model_id}` : undefined}>
              <EvaluationView evaluation={lastDone.result.evaluation} trainingData={lastDone.result.training_data} />
              {lastDone.result.training_data ? (
                <div className="mt-4 text-xs text-muted-foreground">
                  Windows per label: {JSON.stringify(lastDone.result.training_data.windows_per_label)} · rejected windows: {JSON.stringify(lastDone.result.training_data.rejected_windows)}
                </div>
              ) : null}
            </Section>
          ) : null}
          {lastDone?.status === 'failed' ? <Notice tone="danger" title="Training failed">{lastDone.message}</Notice> : null}
        </div>
      </div>

      <Section title="Models" description={isDemo ? 'Demo models (usable only in Demo Mode)' : 'Real models; joblib files load only when trusted and their SHA-256 matches'} className="mt-5">
        {models.data?.length ? (
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Features</TableHead><TableHead>Window</TableHead><TableHead>Labels</TableHead><TableHead>Evaluation</TableHead><TableHead>Created</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {models.data.map((m) => (
                <TableRow key={m.model_id}>
                  <TableCell>
                    <div className="font-medium">{m.name}</div>
                    <div className="font-mono text-xs text-muted-foreground">{m.model_id}</div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{m.feature_version}</TableCell>
                  <TableCell className="tabular text-xs">{m.window_s ? `${m.window_s} s` : '—'}</TableCell>
                  <TableCell className="max-w-48 truncate text-xs">{m.labels?.join(', ') ?? '—'}</TableCell>
                  <TableCell className="text-xs">{m.evaluation_summary.status === 'evaluated' ? `${pct(m.evaluation_summary.accuracy)} acc · F1 ${num(m.evaluation_summary.macro_f1, 2)}` : m.evaluation_summary.status ?? '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{dateTime(m.created_at)}</TableCell>
                  <TableCell className="space-x-1">
                    {m.selected ? <ToneBadge tone="primary">selected</ToneBadge> : null}
                    {m.compatibility.compatible ? <ToneBadge tone="success">compatible</ToneBadge> : <ToneBadge tone="warning" className="max-w-56 truncate" >{m.compatibility.reasons[0]}</ToneBadge>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      {m.source === 'legacy_cli' && !m.trusted ? <Button size="xs" variant="outline" onClick={() => setTrustTarget(m)}><ShieldCheck /> Trust…</Button> : null}
                      {m.compatibility.compatible && !m.selected ? <Button size="xs" onClick={() => run('select', () => api.models.select(m.model_id), 'Model selected').then(() => void models.reload())}>Select</Button> : null}
                      <Button size="icon-xs" variant="ghost" aria-label="Details" onClick={() => run('detail', () => api.models.get(m.model_id)).then((d) => d && setViewModel(d))}><FileJson /></Button>
                      <Button size="icon-xs" variant="ghost" aria-label="Delete" onClick={() => setDeleteTarget(m)}><Trash2 /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <Empty title="No models yet" description="Train one above. A legacy models/gestures.joblib from src/train.py appears here automatically (untrusted until you confirm)." />
        )}
      </Section>

      <Dialog open={viewModel !== null} onOpenChange={(open) => !open && setViewModel(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>{viewModel?.name}</DialogTitle>
            <DialogDescription className="font-mono text-xs">{viewModel?.file.absolute}</DialogDescription>
          </DialogHeader>
          {viewModel ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Input className="max-w-sm" defaultValue={viewModel.name} onBlur={(e) => e.target.value !== viewModel.name && run('rename', () => api.models.rename(viewModel.model_id, e.target.value), 'Renamed').then(() => void models.reload())} />
                {viewModel.compatibility.warnings.map((w) => <ToneBadge key={w} tone="warning">{w}</ToneBadge>)}
              </div>
              <EvaluationView evaluation={viewModel.manifest.evaluation} trainingData={viewModel.manifest.training_data as Record<string, unknown>} />
              <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(viewModel.manifest, null, 2)}</pre>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={trustTarget !== null}
        onOpenChange={(open) => !open && setTrustTarget(null)}
        title="Trust this legacy model file?"
        description={<><p>Loading a joblib file runs Python code stored in it. Only trust models/gestures.joblib if you created it yourself with src/train.py.</p><p>Its training data, scikit-learn version and sampling rate were not recorded, so the app can only check the feature version (summary-60-v1).</p></>}
        confirmLabel="I created this file — trust it"
        onConfirm={() => trustTarget && run('trust', () => api.models.trust(trustTarget.model_id), 'Legacy model trusted').then(() => void models.reload())}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`Delete ${deleteTarget?.name}?`}
        description={deleteTarget?.source === 'legacy_cli' ? 'Only the registry entry is removed; models/gestures.joblib stays on disk for the CLI.' : 'The model folder (artifact and manifest) is deleted from the models directory.'}
        destructive
        confirmLabel="Delete"
        onConfirm={() => deleteTarget && run('delete', () => api.models.remove(deleteTarget.model_id), 'Model deleted').then(() => void models.reload())}
      />
    </>
  )
}
