import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Field, Notice } from '@/components/common/Bits'
import { SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge } from '@/components/common/StatusBadge'
import { api, ApiError, errorMessage } from '@/services/api'
import { hz, num, seconds } from '@/lib/format'
import { CHANNEL_LABELS, CHANNELS } from '@/lib/units'
import type { Channel, SpectrumResult } from '@/types/api'
import { PlotlyChart } from './PlotlyChart'

export type SpectrumSource =
  | { source: 'live'; sensor_id: string; live_seconds: number; simulated?: boolean }
  | { source: 'recording'; recording_id: string; recipe_name?: string | null }
  | { source: 'derivative'; recording_id: string; derivative_id: string }

export function SpectrumPanel({ target, initialChannel = 'gz', autoRefreshDefault = false }: { target: SpectrumSource | null; initialChannel?: Channel; autoRefreshDefault?: boolean }) {
  const [channel, setChannel] = useState<Channel>(initialChannel)
  const [windowSize, setWindowSize] = useState(128)
  const [hop, setHop] = useState(32)
  const [position, setPosition] = useState<'most_energetic' | 'latest'>(target?.source === 'live' ? 'latest' : 'most_energetic')
  const [auto, setAuto] = useState(autoRefreshDefault && target?.source === 'live')
  const [result, setResult] = useState<SpectrumResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const targetKey = JSON.stringify(target)

  const load = useCallback(async () => {
    if (!target) return
    setBusy(true)
    try {
      const source = target.source === 'live' ? { source: 'live', sensor_id: target.sensor_id, live_seconds: target.live_seconds } : target
      const response = await api.analysis.spectrum({ ...source, channel, window: windowSize, hop, fft_position: position })
      setResult(response)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError && err.code === 'repair_required' ? 'This recording is flagged. Choose a repair recipe (applied in memory) or create a derivative first.' : errorMessage(err))
    } finally {
      setBusy(false)
    }
  }, [targetKey, channel, windowSize, hop, position])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!auto || target?.source !== 'live') return
    const timer = setInterval(() => void load(), 1500)
    return () => clearInterval(timer)
  }, [auto, load, target?.source])

  const fftData = useMemo(() => (result ? [{ type: 'scatter', mode: 'lines', x: result.fft.frequency_hz, y: result.fft.magnitude, line: { color: '#3b82f6', width: 1.6 }, hovertemplate: '%{x:.2f} Hz<br>%{y:.4f}<extra></extra>' }] : []), [result])
  const fftLayout = useMemo(() => (result ? { xaxis: { title: { text: 'Frequency (Hz)' }, range: [0, Math.min(25, result.fs_hz / 2)] }, yaxis: { title: { text: `Magnitude (${result.unit})` } } } : {}), [result])
  const stftData = useMemo(
    () =>
      result
        ? [{ type: 'heatmap', x: result.stft.time_s, y: result.stft.frequency_hz, z: result.stft.db, colorscale: 'Viridis', colorbar: { title: { text: 'dB' }, thickness: 12 }, hovertemplate: 't %{x:.2f} s<br>%{y:.2f} Hz<br>%{z:.1f} dB<extra></extra>' }]
        : [],
    [result],
  )
  const stftLayout = useMemo(() => (result ? { xaxis: { title: { text: 'Time (s)' } }, yaxis: { title: { text: 'Frequency (Hz)' }, range: [0, Math.min(25, result.fs_hz / 2)] } } : {}), [result])

  if (!target) return <p className="text-sm text-muted-foreground">Choose a source to analyse.</p>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Field label="Channel">
          <SimpleSelect value={channel} onChange={setChannel} options={CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABELS[c] }))} />
        </Field>
        <Field label="Window (samples)">
          <SimpleSelect value={String(windowSize)} onChange={(v) => setWindowSize(Number(v))} options={['64', '128', '256', '512'].map((v) => ({ value: v, label: v }))} />
        </Field>
        <Field label="Hop (samples)">
          <SimpleSelect value={String(hop)} onChange={(v) => setHop(Number(v))} options={['8', '16', '32', '64'].map((v) => ({ value: v, label: v }))} />
        </Field>
        <Field label="FFT window position">
          <SimpleSelect value={position} onChange={setPosition} options={[{ value: 'most_energetic', label: 'Most energetic' }, { value: 'latest', label: 'Latest' }]} />
        </Field>
        <div className="flex items-end gap-2">
          <Button variant="outline" onClick={() => void load()} disabled={busy}>
            <RefreshCw className={busy ? 'animate-spin' : ''} /> Compute
          </Button>
          {target.source === 'live' ? (
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={auto} onCheckedChange={setAuto} /> Auto
            </label>
          ) : null}
        </div>
      </div>
      {error ? <Notice tone="warning" title="Spectrum unavailable">{error}</Notice> : null}
      {result ? (
        <>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
            <span>Rate used: <b className="text-foreground">{hz(result.fs_hz, 2)}</b> (measured median)</span>
            <span>Window: <b className="text-foreground">{seconds(result.window_s, 3)}</b></span>
            <span>Bin spacing: <b className="text-foreground">{num(result.bin_spacing_hz, 3)} Hz</b></span>
            <span>Dominant: <b className="text-foreground">{result.fft.dominant_hz !== null ? `${num(result.fft.dominant_hz, 2)} Hz` : '—'}</b></span>
            <span>FFT window starts at {seconds(result.fft.start_s, 2)}</span>
            {result.recipe ? <span>Recipe: {result.recipe}</span> : null}
            {target.source === 'live' && target.simulated ? <DemoBadge /> : null}
          </div>
          <p className="text-xs text-muted-foreground">{result.note}</p>
          <div className="grid gap-4 xl:grid-cols-2">
            <div>
              <div className="mb-1 text-sm font-medium">FFT ({result.window} samples, Hann)</div>
              <PlotlyChart data={fftData} layout={fftLayout} height={260} />
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">STFT spectrogram (hop {result.hop})</div>
              <PlotlyChart data={stftData} layout={stftLayout} height={260} />
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
