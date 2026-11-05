import { useEffect, useMemo, useState } from 'react'
import { Download, Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { KeyValue, Notice, Section, Stat } from '@/components/common/Bits'
import { PageHeader } from '@/components/common/PageHeader'
import { SensorSelect, SimpleSelect } from '@/components/common/Pickers'
import { DemoBadge, SensorStatusBadge } from '@/components/common/StatusBadge'
import { LiveSignalChart } from '@/components/charts/LiveSignalChart'
import { SpectrumPanel } from '@/components/charts/SpectrumPanel'
import { useAction } from '@/hooks/useAsync'
import { useAppState } from '@/hooks/useAppState'
import { count, hz } from '@/lib/format'
import { ACCEL_CHANNELS, CHANNEL_LABELS, GYRO_CHANNELS, type AccelUnit, type GyroUnit } from '@/lib/units'
import { api } from '@/services/api'
import type { Channel } from '@/types/api'

export function LiveDataPage() {
  const { sensors, settings, status } = useAppState()
  const [sensorId, setSensorId] = useState<string | null>(null)
  const [channels, setChannels] = useState<Channel[]>(['ax', 'ay', 'az', 'gx', 'gy', 'gz'])
  const [windowS, setWindowS] = useState<number>(settings?.display.window_s ?? 10)
  const [paused, setPaused] = useState(false)
  const [accelUnit, setAccelUnit] = useState<AccelUnit>(settings?.display.accel_unit ?? 'g')
  const [gyroUnit, setGyroUnit] = useState<GyroUnit>(settings?.display.gyro_unit ?? 'deg/s')
  const { run } = useAction()

  useEffect(() => {
    if (!sensorId || !sensors.some((s) => s.sensor_id === sensorId)) {
      const preferred = settings?.selected_sensor_id && sensors.some((s) => s.sensor_id === settings.selected_sensor_id) ? settings.selected_sensor_id : sensors.find((s) => s.status === 'streaming')?.sensor_id ?? sensors[0]?.sensor_id ?? null
      setSensorId(preferred)
    }
  }, [sensors, settings?.selected_sensor_id])

  const sensor = sensors.find((s) => s.sensor_id === sensorId) ?? null
  const accelChannels = useMemo(() => ACCEL_CHANNELS.filter((c) => channels.includes(c)), [channels])
  const gyroChannels = useMemo(() => GYRO_CHANNELS.filter((c) => channels.includes(c)), [channels])

  return (
    <>
      <PageHeader
        title="Live Sensor Data"
        description="Accelerometer (g) and gyroscope (°/s) as streamed. Pausing freezes the display only; acquisition and recording continue."
        actions={
          <>
            <Button variant="outline" onClick={() => setPaused((p) => !p)}>{paused ? <Play /> : <Pause />} {paused ? 'Resume display' : 'Pause display'}</Button>
            <Button variant="outline" disabled={!sensorId} onClick={() => sensorId && run('export', () => api.sensors.exportBuffer(sensorId, windowS))}><Download /> Export {windowS} s CSV</Button>
          </>
        }
      />
      <Section title="View" contentClassName="space-y-4">
        <div className="grid gap-4 md:grid-cols-[14rem_1fr]">
          <div className="space-y-1.5">
            <div className="text-sm font-medium">Sensor</div>
            <SensorSelect value={sensorId} onChange={setSensorId} />
            {sensor ? <div className="flex items-center gap-2 pt-1"><SensorStatusBadge status={sensor.status} />{sensor.simulated ? <DemoBadge /> : null}</div> : null}
          </div>
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="w-24 text-sm font-medium">Channels</span>
              <ToggleGroup type="multiple" variant="outline" value={channels} onValueChange={(v) => setChannels(v as Channel[])}>
                {(['ax', 'ay', 'az', 'amag', 'gx', 'gy', 'gz', 'gmag'] as Channel[]).map((c) => (
                  <ToggleGroupItem key={c} value={c} className="px-3 font-mono text-xs">{CHANNEL_LABELS[c]}</ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="w-24 text-sm font-medium">Window</span>
              <SimpleSelect className="w-28" value={String(windowS)} onChange={(v) => setWindowS(Number(v))} options={['5', '10', '30', '60'].map((v) => ({ value: v, label: `${v} s` }))} />
              <span className="ml-4 text-sm font-medium">Units</span>
              <SimpleSelect className="w-28" value={accelUnit} onChange={setAccelUnit} options={[{ value: 'g', label: 'g' }, { value: 'm/s2', label: 'm/s²' }]} />
              <SimpleSelect className="w-28" value={gyroUnit} onChange={setGyroUnit} options={[{ value: 'deg/s', label: '°/s' }, { value: 'rad/s', label: 'rad/s' }]} />
              <span className="text-xs text-muted-foreground">Drag or Ctrl+wheel to zoom · Shift+wheel to pan · double-click to resume live</span>
            </div>
          </div>
        </div>
      </Section>
      <div className="mt-5 grid gap-5 2xl:grid-cols-[1fr_22rem]">
        <div className="space-y-5">
          {accelChannels.length ? (
            <Section title="Accelerometer">
              <LiveSignalChart sensorId={sensorId} channels={accelChannels} windowS={windowS} paused={paused} accelUnit={accelUnit} gyroUnit={gyroUnit} height={240} title={paused ? 'Display paused' : undefined} />
            </Section>
          ) : null}
          {gyroChannels.length ? (
            <Section title="Gyroscope">
              <LiveSignalChart sensorId={sensorId} channels={gyroChannels} windowS={windowS} paused={paused} accelUnit={accelUnit} gyroUnit={gyroUnit} height={240} title={paused ? 'Display paused' : undefined} />
            </Section>
          ) : null}
          {!channels.length ? <Notice tone="info" title="No channels selected">Choose at least one channel above.</Notice> : null}
          <Section title="Live spectrum (FFT / STFT)" description="Computed by the backend from the live buffer after linear resampling to the measured median rate">
            {sensor && sensor.status === 'streaming' ? (
              <SpectrumPanel key={sensorId} target={{ source: 'live', sensor_id: sensor.sensor_id, live_seconds: Math.min(windowS, 30), simulated: sensor.simulated }} autoRefreshDefault />
            ) : (
              <p className="text-sm text-muted-foreground">Connect a streaming sensor to compute spectra.</p>
            )}
          </Section>
        </div>
        <Section title="Validation counters" description={sensor ? `${sensor.sensor_id} since connecting` : undefined}>
          {sensor ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Device rate" value={hz(sensor.rates.device_hz)} />
                <Stat label="Valid samples" value={count(sensor.totals.valid_samples)} />
              </div>
              <KeyValue
                columns={1}
                items={[
                  ['Malformed lines', count(sensor.counters.malformed_total)],
                  ['Timestamp glitches', count(sensor.timing.glitches)],
                  ['Out-of-order rows', count(sensor.timing.backward_steps)],
                  ['Duplicate timestamps', count(sensor.timing.duplicates)],
                  ['Clock resets', count(sensor.timing.resets)],
                  ['Gaps', count(sensor.timing.gaps)],
                  ['Estimated dropped samples', count(sensor.timing.estimated_missing)],
                  ['Display frames dropped', count(status?.ui_frames_dropped)],
                ]}
              />
              <p className="text-xs text-muted-foreground">Rows with invalid timestamps stay in recordings exactly as received; they are only hidden from charts and recognition.</p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No sensor selected.</p>
          )}
        </Section>
      </div>
    </>
  )
}
