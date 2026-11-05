export type Workspace = 'real' | 'demo'
export type Hand = 'left' | 'right' | 'unassigned'
export type SensorStatus = 'connecting' | 'waiting_for_data' | 'streaming' | 'stalled' | 'disconnected' | 'error'
export type ValidationState = 'valid' | 'flagged' | 'invalid'
export type Channel = 'ax' | 'ay' | 'az' | 'gx' | 'gy' | 'gz' | 'amag' | 'gmag'

export interface Modes {
  monitoring: boolean
  recording: boolean
  recognition: boolean
  pc_control: boolean
  demo: boolean
}

export interface SystemStatus {
  app: string
  version: string
  workspace: Workspace
  primary_mode: string
  modes: Modes
  estop_latched: boolean
  training_active: boolean
  sensors_streaming: number
  clients: number
  ui_frames_dropped: number
  ui_samples_dropped: number
  uptime_s: number
  time: number
  data_dir: string
  data_dir_is_default: boolean
}

export interface SensorError {
  code: string
  message: string
  hint?: string
}

export interface SensorState {
  sensor_id: string
  port: string
  baud: number
  hand: Hand
  workspace: Workspace
  simulated: boolean
  status: SensorStatus
  error: SensorError | null
  connected_at: number | null
  header_alias: string | null
  firmware_hint: string | null
  column_order_assumed: boolean
  last_diagnostic: string | null
  device_error: string | null
  rates: { device_hz: number | null; arrival_hz: number | null; window_samples: number }
  counters: {
    lines_total?: number
    bytes_total?: number
    samples_parsed?: number
    headers?: number
    diagnostics?: number
    device_errors?: number
    malformed_total?: number
    malformed?: Record<string, number>
    partial_lines_dropped?: number
    line_overflows?: number
    rejected_examples?: { reason: string; text: string }[]
  }
  timing: {
    decided?: number
    good?: number
    duplicates?: number
    glitches?: number
    backward_steps?: number
    wraps?: number
    resets?: number
    gaps?: number
    estimated_missing?: number
    gap_total_s?: number
    epochs?: number
    median_interval_us?: number
    median_interval_hz?: number | null
  }
  clock: { epoch: number | null; first_device_t_us: number | null; last_device_t_raw: number | null; last_valid_sample_age_s: number | null }
  totals: { samples: number; valid_samples: number; stalls: number; disconnects: number; reconnect_attempts: number }
  demo: { current_gesture: string | null; auto: boolean | null; rate_hz: number | null } | null
}

export interface PortInfo {
  device: string
  description: string
  hwid: string
  vid: string | null
  pid: string | null
  serial_number: string | null
  manufacturer: string | null
  owned_by: string | null
}

export interface ActionOutcome {
  at: number
  label: string
  action: Record<string, unknown> | null
  description: string
  detection_id: string | null
  source: string
  outcome: 'executed' | 'simulated' | 'blocked' | 'error' | 'preview'
  reason: string
  workspace: Workspace
}

export interface ControlState {
  pc_control_enabled: boolean
  armed: boolean
  armed_at: number | null
  workspace: Workspace
  simulated_actions: boolean
  estop_latched: boolean
  estop_reason: string | null
  estop_at: number | null
  control_session_id: string | null
  last_disarm_reason: string | null
  generation: number
  pending_actions: number
  counters: Record<string, number>
  global_hotkey: { spec: string; status: string; supported: boolean }
  history: ActionOutcome[]
}

export interface AppSettings {
  theme: 'light' | 'dark' | 'system'
  demo_mode: boolean
  selected_sensor_id: string | null
  selected_model_id: string | null
  active_profile_id: string | null
  acquisition: { default_baud: number; auto_reconnect: boolean; stall_timeout_s: number }
  recording: { trial_duration_s: number; countdown_s: number; trials_per_set: number; pause_between_s: number }
  display: { window_s: number; accel_unit: 'g' | 'm/s2'; gyro_unit: 'deg/s' | 'rad/s' }
  inference: { hop_s: number; threshold: number; smoothing_k: number; debounce_n: number; cooldown_s: number; require_idle_rearm: boolean }
  control: {
    pc_control_enabled: boolean
    heartbeat_timeout_s: number
    global_estop_hotkey: string
    global_hotkey_enabled: boolean
    auto_disarm_idle_minutes: number
    sound_activation_required: boolean
  }
  cursor: {
    x_axis: 'gx' | 'gy' | 'gz'
    y_axis: 'gx' | 'gy' | 'gz'
    invert_x: boolean
    invert_y: boolean
    gain_px_per_deg: number
    dead_zone_dps: number
    max_speed_px_s: number
    bias_dps: Record<string, number>
    noise_dps: Record<string, number>
    calibrated_sensor_id: string | null
    calibrated_at: number | null
  }
  sound: { threshold: number; active_window_s: number; refractory_s: number }
}

export interface ActivityEntry {
  id: number
  ts: number
  level: 'debug' | 'info' | 'warning' | 'error'
  category: string
  message: string
  data: Record<string, unknown>
}

export interface Issue {
  code: string
  severity: 'error' | 'repair_required' | 'info'
  message: string
  count: number | null
}

export interface RecorderRunState {
  active: boolean
  mode: 'trials' | 'continuous' | null
  phase: string
  label_id: string | null
  sensor_ids: string[]
  trial: number
  trials: number
  countdown_remaining_s: number | null
  elapsed_s: number | null
  duration_s: number | null
  message: string
  session_id: string | null
  capture_id: string | null
}

export interface StagedTrial {
  staging_id: string
  recording_id: string
  kind: 'trial' | 'continuous'
  source: string
  label_id: string | null
  sensor_id: string
  session_id: string | null
  capture_id: string | null
  start_time: string
  duration_s: number
  sample_count: number
  fs_median_hz: number | null
  validation_state: ValidationState
  issues: Issue[]
  notes: string
  workspace: Workspace
}

export interface RecorderSnapshot {
  state: RecorderRunState
  staging: StagedTrial[]
}

export interface Recording {
  recording_id: string
  workspace: Workspace
  kind: 'trial' | 'continuous'
  source: 'live' | 'import' | 'legacy_cli' | 'demo'
  label_id: string | null
  label_name: string | null
  sensor_id: string | null
  sensor_hand: Hand
  session_id: string | null
  capture_id: string | null
  start_time: string | null
  device_t0_us: number | null
  duration_s: number
  sample_count: number
  fs_median_hz: number | null
  fs_mean_hz: number | null
  file: { base: string; path: string; absolute: string; size_bytes: number }
  sha256: string
  header_alias: string
  time_unit: string
  units: { accel: string; gyro: string; time: string }
  firmware_header: string | null
  validation_state: ValidationState
  issues: Issue[]
  measured_invalid: number | null
  estimated_dropped: number | null
  notes: string
  provenance: Record<string, unknown>
  source_changed: boolean
  app_owned: boolean
  created_at: string
  segment_count?: number
  derivative_count?: number
}

export interface ValidationReport {
  version: string
  state: ValidationState
  issues: Issue[]
  columns: { time: string; time_unit: string; units: Record<string, string>; extra: string[] }
  rows: { total: number; valid_format: number; invalid_format: number; by_reason: Record<string, number>; examples: { line: number; reason: string; text: string }[] }
  timestamps: Record<string, number | number[] | null>
  measured_invalid: Record<string, number>
  estimated_dropped: { samples: number; gaps: number; gap_total_s: number; largest_gap_ms: number | null; note: string }
  epochs: { epoch: number; first_row: number; last_row: number; good: number; span_us: number }[]
  rates: { fs_median_hz: number | null; fs_mean_hz: number | null }
  duration_s: number
  good_samples: number
  min_samples: number
  value_ranges: Record<string, { min: number; max: number }>
  value_resolution: Record<string, number | null>
}

export interface Segment {
  segment_id: string
  recording_id: string
  label_id: string
  label_name: string | null
  start_s: number
  end_s: number
  duration_s: number
  notes: string
  created_at: string
}

export interface Derivative {
  derivative_id: string
  recording_id: string
  recipe_name: string
  recipe: Record<string, unknown>
  file_path: string
  sha256: string
  sample_count: number
  fs_hz: number | null
  uniform: boolean
  step_counts: Record<string, unknown>[]
  created_at: string
}

export interface RecordingDetail extends Recording {
  validation: ValidationReport
  segments: Segment[]
  derivatives: Derivative[]
  datasets: { dataset_id: string; name: string }[]
  file_exists: boolean
}

export interface SignalPreview {
  points: number
  total_points: number
  decimated: boolean
  t_s: number[]
  channels: Record<Channel, number[]>
  duration_s: number
  fs_hz: number | null
  uniform: boolean
  markers: { t_s: number | null; kind: string; row: number }[]
  segments?: Segment[]
  units: { accel: string; gyro: string }
}

export interface RepairRecipe {
  name: string
  version: string
  description: string
  steps: Record<string, unknown>[]
}

export interface Label {
  label_id: string
  display_name: string
  enabled: boolean
  builtin: boolean
  is_idle: boolean
  description: string
  recordings: number
  segments: number
  created_at: string
}

export interface Session {
  session_id: string
  name: string
  notes: string
  source: string
  workspace: Workspace
  recordings: number
  created_at: string
}

export interface KnownSource {
  key: string
  path: string
  absolute: string
  exists: boolean
  size_bytes: number | null
  sha256: string | null
  label_hint: string
  kind: string
  description: string
  imported_recording_id: string | null
}

export interface LabelDistribution {
  members: number
  trials: number
  segments: number
  duration_s: number
  recordings: number
  sessions: number
  sensors: string[]
}

export interface DatasetMember {
  member_id: number
  recording_id: string
  segment_id: string | null
  derivative_id: string | null
  label_id: string | null
  label_name: string | null
  kind: string
  source: string
  sensor_id: string | null
  session_id: string | null
  duration_s: number
  segment: { start_s: number; end_s: number } | null
  fs_median_hz: number | null
  validation_state: ValidationState
  needs_repair: boolean
  usable: boolean
}

export interface Readiness {
  ready: boolean
  problems: { code: string; message: string; count?: number }[]
  warnings: { code: string; message: string }[]
}

export interface DatasetSummary {
  dataset_id: string
  name: string
  description: string
  members: number
  created_at: string
  workspace: Workspace
  distribution: Record<string, LabelDistribution>
}

export interface DatasetDetail {
  dataset_id: string
  name: string
  description: string
  created_at: string
  workspace: Workspace
  members: DatasetMember[]
  by_label: Record<string, LabelDistribution>
  rate_check: { compatible: boolean; min_hz: number | null; max_hz: number | null; tolerance: number }
  member_count: number
  readiness: Readiness
}

export interface SpectrumResult {
  source: string
  channel: Channel
  unit: string
  resampled: boolean
  segments_available: number
  samples_used: number
  note: string
  fs_hz: number
  window: number
  hop: number
  window_s: number
  bin_spacing_hz: number
  hop_s: number
  recipe?: string
  fft: { start_index: number; start_s: number; frequency_hz: number[]; magnitude: number[]; dominant_hz: number | null }
  stft: { frequency_hz: number[]; time_s: number[]; db: number[][] }
}

export interface FeatureInfo {
  version: string
  preprocessing: string
  default_window_s: number
  min_samples: number
  feature_count: number
  feature_names: string[]
  description: string
}

export interface Evaluation {
  status: 'evaluated' | 'insufficient_grouped_data' | 'insufficient_classes' | 'not_recorded' | string
  message?: string
  labels?: string[]
  groups_per_label?: Record<string, number>
  groups_total?: number
  windows?: number
  classes_lacking_groups?: string[]
  method?: string
  n_splits?: number
  folds?: { fold: number; train_windows: number; test_windows: number; test_groups: string[]; missing_train_labels: string[]; accuracy: number }[]
  accuracy?: number
  macro?: { precision: number; recall: number; f1: number }
  per_class?: Record<string, { precision: number; recall: number; f1: number; support: number }>
  confusion_matrix?: { labels: string[]; matrix: number[][] }
  tested?: number
}

export interface TrainingJob {
  job_id: string
  workspace: Workspace
  dataset_id: string
  config: Record<string, unknown>
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: string
  progress: number
  message: string
  result: { evaluation?: Evaluation; training_data?: Record<string, unknown>; traceback?: string }
  model_id: string | null
  created_at: string
  finished_at: string | null
}

export interface Compatibility {
  compatible: boolean
  reasons: string[]
  warnings: string[]
}

export interface ModelSummary {
  model_id: string
  name: string
  source: 'app' | 'legacy_cli'
  workspace: Workspace
  feature_version: string
  trusted: boolean
  created_at: string
  labels: string[] | null
  window_s: number | null
  file: { path: string; absolute: string; sha256: string }
  evaluation_summary: { status: string | null; accuracy: number | null; macro_f1: number | null; n_splits: number | null; message: string | null }
  training_windows: number | null
  dataset: { dataset_id: string; name: string } | null
  rate_requirements: Record<string, number | string | null> | null
  selected: boolean
  compatibility: Compatibility
  note: string | null
}

export interface ModelDetail extends ModelSummary {
  manifest: Record<string, unknown> & { evaluation?: Evaluation }
}

export interface Prediction {
  at: number
  label: string
  score: number
  raw_score: number
  above_threshold: boolean
  probabilities: Record<string, number>
  latency_ms: number
  processing_ms: number
  window_s: number
  hop_s: number
  device_t_us: number
  rearmed: boolean
  streak: number
  suppressed: string | null
  sensor_id: string
  simulated: boolean
}

export interface Detection {
  detection_id: string
  label: string
  score: number
  at: number
  mapped_action: string | null
  outcome: string
  simulated: boolean
  sensor_id: string
}

export interface RecognitionState {
  running: boolean
  model: { model_id: string; name: string; feature_version: string; window_s: number; labels: string[]; idle_labels: string[]; source: string; rate_requirements: Record<string, number | string | null> } | null
  sensor_id: string | null
  config: Record<string, number | boolean>
  last_prediction: Prediction | null
  detections: Detection[]
  counters: Record<string, number>
  message: string
  started_at: number | null
}

export interface MappingEntry {
  mapping_id: number
  label_id: string
  label_name: string | null
  label_exists: boolean
  action: GestureAction
  description: string
  enabled: boolean
}

export interface MappingProfile {
  profile_id: string
  name: string
  description: string
  read_only: boolean
  active: boolean
  created_at: string
  mappings: MappingEntry[]
}

export type GestureAction =
  | { type: 'key'; key: string }
  | { type: 'hotkey'; modifiers: string[]; key: string }
  | { type: 'click'; button: 'left' | 'right' | 'middle' }
  | { type: 'double_click'; button: 'left' }
  | { type: 'scroll'; notches: number }

export interface Allowlist {
  keys: string[]
  modifiers: string[]
  blocked_combinations: string[]
  types: string[]
  cursor_only_types: string[]
  never_allowed: string[]
}

export interface Capability {
  available: boolean
  reason?: string
  note?: string
  verified_on_hardware?: boolean
  experimental?: boolean
  simulated_only?: boolean
}

export interface SyncMeasurement {
  measurement_id: string
  sensor_ids: string[]
  method: string
  events_used: number
  mean_abs_error_ms: number | null
  max_abs_error_ms: number | null
  details: { simulated?: boolean; note?: string; errors_ms?: number[]; events?: Record<string, number> } & Record<string, unknown>
  created_at: string
  workspace: Workspace
}

export interface SyncState {
  measuring: boolean
  phase: string
  message: string
  sensor_ids: string[]
  alignments: Record<string, { ready: boolean; points: number; offset_us?: number; drift_ppm?: number; envelope_residual_us?: number }>
  measurements: SyncMeasurement[]
}

export interface CursorState {
  active: boolean
  sensor_id: string | null
  moves: number
  last_velocity_px_s: [number, number]
  message: string
  calibrated: boolean
  calibrated_sensor_id: string | null
  calibrated_at: number | null
  settings: AppSettings['cursor']
  verified_on_hardware: boolean
}

export interface SoundState {
  available: boolean
  reason: string
  simulated: boolean
  source_running: boolean
  state: 'idle' | 'active' | 'unavailable'
  level: number | null
  active_remaining_s: number
  events: { at: number; level: number }[]
  levels: { t: number; level: number }[]
  settings: AppSettings['sound']
  required_for_actions: boolean
}

export interface TrainingSnapshot {
  active_job: TrainingJob | null
  recent: TrainingJob[]
}

export interface Snapshot {
  status: SystemStatus
  sensors: SensorState[]
  control: ControlState
  settings: AppSettings
  recent_log: ActivityEntry[]
  recorder?: RecorderSnapshot
  training?: TrainingSnapshot
  recognition?: RecognitionState
  sync?: SyncState
  cursor?: CursorState
  sound?: SoundState
}

export interface WsEnvelope<T = unknown> {
  v: number
  type: string
  topic: string
  seq: number
  ts: number
  data: T
}

export interface SamplesBatch {
  sensor_id: string
  simulated: boolean
  epoch: number
  t_us: number[]
  ax: number[]
  ay: number[]
  az: number[]
  gx: number[]
  gy: number[]
  gz: number[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}
