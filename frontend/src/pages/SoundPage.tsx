import { useEffect, useMemo, useState } from 'react'
import { Mic, MicOff, Volume2 } from 'lucide-react'
import type uPlot from 'uplot'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Field, KeyValue, Notice, NumberInput, Section } from '@/components/common/Bits'
import { PageHeader } from '@/components/common/PageHeader'
import { DemoBadge, ToneBadge } from '@/components/common/StatusBadge'
import { UPlotChart } from '@/components/charts/UPlotChart'
import { axisTheme } from '@/components/charts/uplotHelpers'
import { useAction, useAsync } from '@/hooks/useAsync'
import { useAppState } from '@/hooks/useAppState'
import { useTheme } from '@/hooks/useTheme'
import { useTopicState } from '@/hooks/useTopic'
import { api } from '@/services/api'
import { cssVar } from '@/lib/units'
import { num, timeOfDay } from '@/lib/format'
import type { SoundState } from '@/types/api'

export function SoundPage() {
  const { settings } = useAppState()
  const { resolvedTheme } = useTheme()
  const initial = useAsync(() => api.advanced.sound(), [settings?.demo_mode])
  const live = useTopicState<SoundState | null>('sound', null, 'sound', 100)
  const sound = live ?? initial.data ?? null
  const [threshold, setThreshold] = useState(settings?.sound.threshold ?? 0.5)
  const [windowS, setWindowS] = useState(settings?.sound.active_window_s ?? 8)
  const [refractory, setRefractory] = useState(settings?.sound.refractory_s ?? 1)
  const { run } = useAction()

  useEffect(() => {
    if (settings) {
      setThreshold(settings.sound.threshold)
      setWindowS(settings.sound.active_window_s)
      setRefractory(settings.sound.refractory_s)
    }
  }, [settings?.sound.threshold, settings?.sound.active_window_s, settings?.sound.refractory_s])

  const options = useMemo<Omit<uPlot.Options, 'width' | 'height'>>(() => {
    const axis = axisTheme()
    return {
      legend: { show: false },
      scales: { x: { time: false }, y: { range: [0, 1] } },
      axes: [{ ...axis, values: (_u, ticks) => ticks.map(() => '') }, { ...axis, label: 'level', size: 48 }],
      series: [{}, { stroke: cssVar('--series-gmag', '#f59e0b'), width: 1.5, points: { show: false } }],
    }
  }, [resolvedTheme])
  const data = useMemo<uPlot.AlignedData>(() => [sound?.levels.map((l) => l.t) ?? [], sound?.levels.map((l) => l.level) ?? []], [sound?.levels])

  return (
    <>
      <PageHeader title="Sound Activation" description="Optional wake signal: a clap or tap activates gesture actions for a short window. The microphone is a separate source from the IMU." />
      {!sound?.available && !sound?.simulated ? (
        <Section title={<span className="flex items-center gap-2"><MicOff className="size-4" /> Unavailable with the current firmware</span>}>
          <div className="space-y-4">
            <Notice tone="warning" title="No compatible microphone stream">{sound?.reason}</Notice>
            <div className="text-sm">
              <div className="mb-2 font-medium">What would make it available</div>
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                <li>Firmware that streams a microphone level (or short-time energy) alongside the IMU lines, with its own device timestamps.</li>
                <li>A documented line format so the backend can parse it without guessing.</li>
                <li>Measurements of true and false activation rates, as listed in the project proposal.</li>
              </ul>
            </div>
            <p className="text-xs text-muted-foreground">Until then, these settings are not presented as effective. Turn on Demo Mode to try the activation logic with a clearly labelled simulated microphone.</p>
          </div>
        </Section>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,24rem)_1fr]">
          <Section title={<span className="flex items-center gap-2">Simulated microphone <DemoBadge /></span>} description="Background noise with an occasional simulated clap">
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {sound?.source_running ? (
                  <>
                    <Button onClick={() => run('clap', () => api.advanced.clap())}><Volume2 /> Simulate clap</Button>
                    <Button variant="outline" onClick={() => run('stop', () => api.advanced.stopDemoMic())}>Stop microphone</Button>
                  </>
                ) : (
                  <Button onClick={() => run('start', () => api.advanced.startDemoMic(), 'Simulated microphone started')}><Mic /> Start simulated microphone</Button>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Threshold"><NumberInput value={threshold} onChange={setThreshold} min={0.05} max={1} step={0.05} /></Field>
                <Field label="Active for (s)"><NumberInput value={windowS} onChange={setWindowS} min={1} max={120} /></Field>
                <Field label="Refractory (s)"><NumberInput value={refractory} onChange={setRefractory} min={0} max={10} step={0.5} /></Field>
              </div>
              <Button variant="outline" onClick={() => run('save', () => api.settings.patch({ sound: { threshold, active_window_s: windowS, refractory_s: refractory } }), 'Sound settings saved')}>Save settings</Button>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>Require sound activation before gesture actions</span>
                <Switch checked={Boolean(settings?.control.sound_activation_required)} onCheckedChange={(v) => run('req', () => api.settings.patch({ control: { sound_activation_required: v } }))} />
              </label>
            </div>
          </Section>
          <Section title="Activation state" actions={sound?.state === 'active' ? <ToneBadge tone="success">ACTIVE {num(sound.active_remaining_s, 1)} s</ToneBadge> : <ToneBadge tone="muted">{sound?.state ?? '—'}</ToneBadge>}>
            <UPlotChart options={options} data={data} height={180} />
            <div className="mt-4">
              <KeyValue items={[['Level', num(sound?.level ?? null, 2)], ['Events', sound?.events.length ?? 0], ['Last event', sound?.events.length ? timeOfDay(sound.events[sound.events.length - 1].at) : '—'], ['Gates actions', settings?.control.sound_activation_required ? 'yes' : 'no']]} />
            </div>
          </Section>
        </div>
      )}
    </>
  )
}
