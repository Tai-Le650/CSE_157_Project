import type {
  ActivityEntry,
  Allowlist,
  AppSettings,
  Capability,
  ControlState,
  CursorState,
  DatasetDetail,
  DatasetSummary,
  Derivative,
  FeatureInfo,
  GestureAction,
  KnownSource,
  Label,
  MappingProfile,
  ModelDetail,
  ModelSummary,
  PortInfo,
  RecognitionState,
  RecorderSnapshot,
  Recording,
  RecordingDetail,
  RepairRecipe,
  SensorState,
  Session,
  SessionInfo,
  SignalPreview,
  Snapshot,
  SoundState,
  SpectrumResult,
  StagedTrial,
  SyncState,
  SystemStatus,
  TrainingJob,
} from '@/types/api'

export class ApiError extends Error {
  code: string
  status: number
  details: unknown

  constructor(code: string, message: string, status: number, details?: unknown) {
    super(message)
    this.code = code
    this.status = status
    this.details = details
  }

  get reasons(): string[] {
    const details = this.details as { reasons?: unknown } | undefined
    return Array.isArray(details?.reasons) ? (details.reasons as string[]) : []
  }
}

const TOKEN_STORAGE_KEY = 'gesture-to-pc.session-token'
const LOCAL_HOSTNAMES = new Set(['127.0.0.1', 'localhost', '[::1]', '::1'])

let sessionPromise: Promise<SessionInfo> | null = null
let currentSession: SessionInfo | null = null
let sessionError: ApiError | null = null
const sessionListeners = new Set<(info: SessionInfo) => void>()
const replacedListeners = new Set<(info: SessionInfo) => void>()
const sessionErrorListeners = new Set<(error: ApiError | null) => void>()

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

function storeToken(token: string) {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    return
  }
}

export function isHostedSite(): boolean {
  if (currentSession) return currentSession.hosted
  return typeof window !== 'undefined' && !LOCAL_HOSTNAMES.has(window.location.hostname)
}

function unreachableMessage(): string {
  return isHostedSite() ? 'The online demo server is not reachable. It may be waking up, so try again in a minute.' : 'The backend is not reachable. Is backend\\run.py running?'
}

export function currentSessionInfo(): SessionInfo | null {
  return currentSession
}

export function onSessionInfo(listener: (info: SessionInfo) => void): () => void {
  sessionListeners.add(listener)
  if (currentSession) listener(currentSession)
  return () => {
    sessionListeners.delete(listener)
  }
}

export function onSessionReplaced(listener: (info: SessionInfo) => void): () => void {
  replacedListeners.add(listener)
  return () => {
    replacedListeners.delete(listener)
  }
}

export function currentSessionError(): ApiError | null {
  return sessionError
}

export function onSessionError(listener: (error: ApiError | null) => void): () => void {
  sessionErrorListeners.add(listener)
  return () => {
    sessionErrorListeners.delete(listener)
  }
}

function setSessionError(error: ApiError | null) {
  if (sessionError === error) return
  sessionError = error
  for (const listener of sessionErrorListeners) listener(error)
}

function acceptSession(info: SessionInfo) {
  const previous = currentSession
  currentSession = info
  setSessionError(null)
  storeToken(info.token)
  for (const listener of sessionListeners) listener(info)
  if (previous && info.hosted && previous.token !== info.token) {
    for (const listener of replacedListeners) listener(info)
  }
}

export function resetToken() {
  sessionPromise = null
}

export function getSession(): Promise<SessionInfo> {
  if (!sessionPromise) {
    const stored = readStoredToken()
    sessionPromise = fetch('/api/session', { cache: 'no-store', headers: stored ? { 'X-Session-Token': stored } : {} })
      .then(async (response) => {
        const data = await parse(response)
        if (!response.ok) {
          const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error
          const error = new ApiError(err?.code ?? 'session_unavailable', err?.message ?? 'Could not reach the Gesture-to-PC backend', response.status, err?.details)
          setSessionError(error)
          throw error
        }
        const body = data as Omit<SessionInfo, 'hosted' | 'limits'> & Partial<Pick<SessionInfo, 'hosted' | 'limits'>>
        const info: SessionInfo = { ...body, hosted: body.hosted ?? false, limits: body.limits ?? null }
        acceptSession(info)
        return info
      })
      .catch((error: unknown) => {
        sessionPromise = null
        throw error
      })
  }
  return sessionPromise
}

export function getToken(): Promise<string> {
  return getSession().then((info) => info.token)
}

async function sessionToken(): Promise<string> {
  try {
    return await getToken()
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError('network_error', unreachableMessage(), 0)
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined
  const text = await response.text()
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function request<T>(method: Method, path: string, body?: unknown, retry = true): Promise<T> {
  const headers: Record<string, string> = { 'X-Session-Token': await sessionToken() }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(path, { method, headers, body: payload, cache: 'no-store' })
  } catch {
    throw new ApiError('network_error', unreachableMessage(), 0)
  }
  const data = await parse(response)
  if (!response.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | undefined)?.error
    if (response.status === 401 && err?.code === 'invalid_session_token' && retry) {
      resetToken()
      return request<T>(method, path, body, false)
    }
    throw new ApiError(err?.code ?? 'http_error', err?.message ?? response.statusText, response.status, err?.details)
  }
  return data as T
}

export async function download(path: string, method: Method = 'GET', fallbackName = 'download'): Promise<void> {
  const headers: Record<string, string> = { 'X-Session-Token': await sessionToken() }
  const response = await fetch(path, { method, headers })
  if (!response.ok) {
    const data = await parse(response)
    const err = (data as { error?: { code?: string; message?: string } } | undefined)?.error
    throw new ApiError(err?.code ?? 'http_error', err?.message ?? response.statusText, response.status)
  }
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? fallbackName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {})
const put = <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {})
const patch = <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {})
const del = <T>(path: string) => request<T>('DELETE', path)

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  system: {
    health: () => get<{ status: string }>('/api/health'),
    status: () => get<SystemStatus>('/api/status'),
    snapshot: () => get<Snapshot>('/api/snapshot'),
    activity: (limit = 100) => get<ActivityEntry[]>(`/api/activity${qs({ limit })}`),
    ports: () => get<PortInfo[]>('/api/ports'),
  },
  settings: {
    get: () => get<AppSettings>('/api/settings'),
    patch: (values: Record<string, unknown>) => patch<AppSettings>('/api/settings', { values }),
    setDemoMode: (enabled: boolean) => post<AppSettings>('/api/settings/demo-mode', { enabled, confirm: true }),
    storage: () => get<{ data_dir: string; data_dir_is_default: boolean; models_dir: string; cli_data_dir: string; pending_data_dir: string | null; restart_required: boolean }>('/api/settings/storage'),
    setStorage: (dataDir: string | null) => put<{ data_dir: string; restart_required: boolean; pending_data_dir: string | null }>('/api/settings/storage', { data_dir: dataDir }),
  },
  sensors: {
    list: () => get<SensorState[]>('/api/sensors'),
    known: () => get<{ sensor_id: string; hand: string; last_port: string | null; baud: number }[]>('/api/sensors/known'),
    connect: (body: { port?: string | null; baud?: number | null; sensor_id: string; hand: string; simulated?: boolean; demo_rate_hz?: number; demo_auto?: boolean }) => post<SensorState>('/api/sensors', body),
    update: (id: string, body: { sensor_id?: string; hand?: string }) => patch<SensorState>(`/api/sensors/${encodeURIComponent(id)}`, body),
    disconnect: (id: string) => post<SensorState>(`/api/sensors/${encodeURIComponent(id)}/disconnect`),
    reconnect: (id: string) => post<SensorState>(`/api/sensors/${encodeURIComponent(id)}/reconnect`),
    remove: (id: string) => del<void>(`/api/sensors/${encodeURIComponent(id)}`),
    exportBuffer: (id: string, seconds: number) => download(`/api/sensors/${encodeURIComponent(id)}/buffer${qs({ seconds, fmt: 'csv' })}`, 'GET', `${id}_live.csv`),
  },
  demo: {
    perform: (id: string, label: string) => post<{ queued: string }>(`/api/demo/sensors/${encodeURIComponent(id)}/perform`, { label }),
    auto: (id: string, enabled: boolean) => post<{ auto: boolean }>(`/api/demo/sensors/${encodeURIComponent(id)}/auto`, { enabled }),
  },
  control: {
    state: () => get<ControlState>('/api/control'),
    allowlist: () => get<Allowlist>('/api/control/allowlist'),
    arm: (controlSessionId: string) => post<ControlState>('/api/control/arm', { control_session_id: controlSessionId, confirm: true }),
    disarm: () => post<ControlState>('/api/control/disarm', { reason: 'user' }),
    emergencyStop: (source = 'ui_button') => post<ControlState>('/api/control/emergency-stop', { source }),
    reset: () => post<ControlState>('/api/control/reset'),
  },
  recorder: {
    state: () => get<RecorderSnapshot>('/api/recorder'),
    startTrials: (body: { label_id: string; sensor_ids: string[]; duration_s?: number; countdown_s?: number; trials?: number; pause_s?: number; session_id?: string | null; notes?: string }) => post<RecorderSnapshot>('/api/recorder/trials', body),
    startContinuous: (body: { label_id?: string | null; sensor_ids: string[]; session_id?: string | null; notes?: string }) => post<RecorderSnapshot>('/api/recorder/continuous', body),
    stop: () => post<RecorderSnapshot>('/api/recorder/stop'),
    newSession: (name: string, notes = '') => post<Session>('/api/recorder/session', { name, notes }),
    preview: (id: string) => get<SignalPreview>(`/api/recorder/staging/${encodeURIComponent(id)}/preview`),
    updateStaged: (id: string, body: { notes?: string; label_id?: string }) => patch<StagedTrial>(`/api/recorder/staging/${encodeURIComponent(id)}`, body),
    save: (ids: string[]) => post<{ saved: string[]; errors: { staging_id: string; error: string }[] }>('/api/recorder/staging/save', { staging_ids: ids }),
    discard: (ids: string[]) => post<{ discarded: string[] }>('/api/recorder/staging/discard', { staging_ids: ids, confirm: true }),
    exportCsv: (id: string) => download(`/api/recorder/staging/${encodeURIComponent(id)}/export`, 'GET', `${id}.csv`),
  },
  recordings: {
    list: (params: Record<string, string | number | undefined>) => get<{ items: Recording[]; total: number }>(`/api/recordings${qs(params)}`),
    get: (id: string) => get<RecordingDetail>(`/api/recordings/${encodeURIComponent(id)}`),
    preview: (id: string, derivativeId?: string | null) => get<SignalPreview>(`/api/recordings/${encodeURIComponent(id)}/preview${qs({ derivative_id: derivativeId ?? undefined })}`),
    update: (id: string, body: Record<string, unknown>) => patch<Recording>(`/api/recordings/${encodeURIComponent(id)}`, body),
    remove: (id: string, mode: 'metadata' | 'disk') => del<{ removed_files: string[]; kept_files: string[] }>(`/api/recordings/${encodeURIComponent(id)}${qs({ mode, confirm: true })}`),
    revalidate: (id: string) => post<RecordingDetail>(`/api/recordings/${encodeURIComponent(id)}/revalidate`),
    recover: () => post<{ recovered: string[]; skipped: unknown[] }>('/api/recordings/recover'),
    recipes: () => get<RepairRecipe[]>('/api/recordings/recipes'),
    createDerivative: (id: string, recipeName: string) => post<Derivative>(`/api/recordings/${encodeURIComponent(id)}/derivatives`, { recipe_name: recipeName }),
    deleteDerivative: (derivativeId: string) => del<{ removed_files: string[] }>(`/api/recordings/derivatives/${encodeURIComponent(derivativeId)}`),
    addSegment: (id: string, body: { label_id: string; start_s: number; end_s: number; notes?: string }) => post<unknown>(`/api/recordings/${encodeURIComponent(id)}/segments`, body),
    updateSegment: (segmentId: string, body: Record<string, unknown>) => patch<unknown>(`/api/recordings/segments/${encodeURIComponent(segmentId)}`, body),
    deleteSegment: (segmentId: string) => del<void>(`/api/recordings/segments/${encodeURIComponent(segmentId)}`),
    downloadFile: (id: string) => download(`/api/recordings/${encodeURIComponent(id)}/file`, 'GET', `${id}.csv`),
  },
  imports: {
    known: () => get<KnownSource[]>('/api/imports/known'),
    importKnown: (keys: string[], sessionMode: 'batch' | 'per_file' | 'none') => post<{ imported: { recording_id: string; validation_state: string }[]; skipped: { key: string; reason: string }[] }>('/api/imports/known', { keys, session_mode: sessionMode }),
    upload: (form: FormData) => request<{ recording_id: string; validation_state: string; issues: unknown[] }>('POST', '/api/imports/upload', form),
    rescanLegacy: () => post<{ folder: string; registered: string[]; unchanged: string[]; changed: string[]; skipped: { file: string; reason: string }[] }>('/api/imports/legacy/rescan'),
  },
  labels: {
    list: () => get<Label[]>('/api/labels'),
    create: (body: { label_id: string; display_name: string; enabled?: boolean }) => post<Label>('/api/labels', body),
    update: (id: string, body: { display_name?: string; enabled?: boolean; description?: string }) => patch<Label>(`/api/labels/${encodeURIComponent(id)}`, body),
    rename: (id: string, newId: string) => post<Label>(`/api/labels/${encodeURIComponent(id)}/rename`, { new_label_id: newId, confirm: true }),
    merge: (source: string, target: string) => post<unknown>('/api/labels/merge', { source_id: source, target_id: target, confirm: true }),
    remove: (id: string) => del<void>(`/api/labels/${encodeURIComponent(id)}`),
  },
  sessions: {
    list: () => get<Session[]>('/api/sessions'),
    create: (name: string, notes = '') => post<Session>('/api/sessions', { name, notes }),
    update: (id: string, body: { name?: string; notes?: string }) => patch<Session>(`/api/sessions/${encodeURIComponent(id)}`, body),
    assign: (sessionId: string | null, recordingIds: string[]) => post<{ updated: number }>('/api/sessions/assign', { session_id: sessionId, recording_ids: recordingIds }),
  },
  datasets: {
    list: () => get<DatasetSummary[]>('/api/datasets'),
    get: (id: string) => get<DatasetDetail>(`/api/datasets/${encodeURIComponent(id)}`),
    create: (name: string, description = '') => post<DatasetDetail>('/api/datasets', { name, description }),
    update: (id: string, body: { name?: string; description?: string }) => patch<DatasetDetail>(`/api/datasets/${encodeURIComponent(id)}`, body),
    remove: (id: string) => del<{ recordings_untouched: boolean }>(`/api/datasets/${encodeURIComponent(id)}`),
    addMembers: (id: string, items: { recording_id: string; segment_id?: string | null; derivative_id?: string | null }[]) => post<{ added: number; skipped: { recording_id: string; reason: string }[]; dataset: DatasetDetail }>(`/api/datasets/${encodeURIComponent(id)}/members`, { items }),
    removeMembers: (id: string, memberIds: number[]) => post<{ removed: number; dataset: DatasetDetail }>(`/api/datasets/${encodeURIComponent(id)}/members/remove`, { member_ids: memberIds }),
    setMemberDerivative: (id: string, memberId: number, derivativeId: string | null) => put<DatasetDetail>(`/api/datasets/${encodeURIComponent(id)}/members/${memberId}/derivative`, { derivative_id: derivativeId }),
    repairFlagged: (id: string, recipeName: string) => post<{ derivatives_created: number; members_updated: number; dataset: DatasetDetail }>(`/api/datasets/${encodeURIComponent(id)}/repair-flagged`, { recipe_name: recipeName, confirm: true }),
    export: (id: string) => download(`/api/datasets/${encodeURIComponent(id)}/export`, 'POST', 'dataset.zip'),
  },
  analysis: {
    spectrum: (body: Record<string, unknown>) => post<SpectrumResult>('/api/analysis/spectrum', body),
  },
  training: {
    features: () => get<FeatureInfo[]>('/api/training/features'),
    start: (body: Record<string, unknown>) => post<TrainingJob>('/api/training/jobs', body),
    jobs: () => get<TrainingJob[]>('/api/training/jobs'),
    job: (id: string) => get<TrainingJob>(`/api/training/jobs/${encodeURIComponent(id)}`),
    cancel: (id: string) => post<TrainingJob>(`/api/training/jobs/${encodeURIComponent(id)}/cancel`),
  },
  models: {
    list: () => get<ModelSummary[]>('/api/models'),
    get: (id: string) => get<ModelDetail>(`/api/models/${encodeURIComponent(id)}`),
    select: (id: string) => post<ModelDetail>(`/api/models/${encodeURIComponent(id)}/select`),
    trust: (id: string) => post<ModelDetail>(`/api/models/${encodeURIComponent(id)}/trust`, { confirm: true }),
    rename: (id: string, name: string) => patch<ModelDetail>(`/api/models/${encodeURIComponent(id)}`, { name }),
    remove: (id: string) => del<{ removed: string[]; kept: string[] }>(`/api/models/${encodeURIComponent(id)}${qs({ confirm: true })}`),
  },
  recognition: {
    state: () => get<RecognitionState>('/api/recognition'),
    start: (body: Record<string, unknown>) => post<RecognitionState>('/api/recognition/start', body),
    stop: () => post<RecognitionState>('/api/recognition/stop'),
  },
  mappings: {
    profiles: () => get<MappingProfile[]>('/api/mappings/profiles'),
    createProfile: (name: string, copyFrom?: string | null) => post<MappingProfile>('/api/mappings/profiles', { name, copy_from: copyFrom ?? null }),
    updateProfile: (id: string, body: { name?: string; description?: string }) => patch<MappingProfile>(`/api/mappings/profiles/${encodeURIComponent(id)}`, body),
    deleteProfile: (id: string) => del<void>(`/api/mappings/profiles/${encodeURIComponent(id)}`),
    setActive: (id: string | null) => put<{ active_profile_id: string | null }>('/api/mappings/active', { profile_id: id }),
    upsert: (profileId: string, labelId: string, action: GestureAction, enabled: boolean) => put<MappingProfile>(`/api/mappings/profiles/${encodeURIComponent(profileId)}/labels/${encodeURIComponent(labelId)}`, { action, enabled }),
    remove: (profileId: string, labelId: string) => del<MappingProfile>(`/api/mappings/profiles/${encodeURIComponent(profileId)}/labels/${encodeURIComponent(labelId)}`),
    simulate: (body: { label_id?: string | null; action?: GestureAction | null }) => post<{ mapped: boolean; description: string; executed: boolean; simulated: boolean }>('/api/mappings/simulate', body),
    allowlist: () => get<Allowlist>('/api/mappings/allowlist'),
  },
  advanced: {
    capabilities: () => get<Record<string, Capability>>('/api/advanced/capabilities'),
    sync: () => get<SyncState>('/api/advanced/sync'),
    measureSync: (sensorIds: string[], durationS: number, simulatedTaps = 0) => post<SyncState>('/api/advanced/sync/measure', { sensor_ids: sensorIds, duration_s: durationS, simulated_taps: simulatedTaps }),
    syncGate: (a: string, b: string) => get<{ combined_inference_allowed: boolean; reason: string; simulated: boolean; threshold_ms: number }>(`/api/advanced/sync/gate${qs({ a, b })}`),
    cursor: () => get<CursorState>('/api/advanced/cursor'),
    calibrateCursor: (sensorId: string, seconds = 2) => post<CursorState & { suggested_dead_zone_dps: number }>('/api/advanced/cursor/calibrate', { sensor_id: sensorId, seconds }),
    startCursor: (sensorId: string) => post<CursorState>('/api/advanced/cursor/start', { sensor_id: sensorId }),
    stopCursor: () => post<CursorState>('/api/advanced/cursor/stop'),
    sound: () => get<SoundState>('/api/advanced/sound'),
    startDemoMic: () => post<SoundState>('/api/advanced/sound/demo/start'),
    stopDemoMic: () => post<SoundState>('/api/advanced/sound/demo/stop'),
    clap: () => post<SoundState>('/api/advanced/sound/demo/clap'),
    classifyAirwriting: (body: { model_id: string; recording_id?: string; sensor_id?: string; seconds?: number }) => post<{ label: string; distance: number; ranking: { label: string; distance: number }[] }>('/api/advanced/airwriting/classify', body),
    performance: () => get<Record<string, unknown>>('/api/advanced/performance'),
  },
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const reasons = error.reasons
    if (reasons.length) return `${error.message}: ${reasons.join(' ')}`
    if (error.code === 'validation_error' && Array.isArray(error.details)) {
      const items = (error.details as { loc?: string[]; msg?: string }[]).slice(0, 3).map((d) => `${(d.loc ?? []).filter((part) => part !== 'body').join('.')}: ${d.msg ?? ''}`)
      return `${error.message} (${items.join('; ')})`
    }
    return error.message
  }
  if (error instanceof Error) return error.message
  return String(error)
}
