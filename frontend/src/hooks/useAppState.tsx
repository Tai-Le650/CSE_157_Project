import { createContext, useContext, useEffect, useReducer, type ReactNode } from 'react'
import { wsClient, type ConnectionState } from '@/services/ws'
import type {
  ActionOutcome,
  ActivityEntry,
  AppSettings,
  ControlState,
  Detection,
  RecognitionState,
  RecorderSnapshot,
  SensorState,
  Snapshot,
  SystemStatus,
  TrainingJob,
  TrainingSnapshot,
  WsEnvelope,
} from '@/types/api'

export interface AppState {
  connection: ConnectionState
  clientId: string | null
  loaded: boolean
  status: SystemStatus | null
  sensors: SensorState[]
  control: ControlState | null
  settings: AppSettings | null
  log: ActivityEntry[]
  recorder: RecorderSnapshot | null
  training: TrainingSnapshot | null
  recognition: RecognitionState | null
  detections: Detection[]
}

type Action =
  | { kind: 'connection'; value: ConnectionState }
  | { kind: 'hello'; clientId: string; snapshot: Snapshot }
  | { kind: 'status'; value: SystemStatus }
  | { kind: 'control'; value: ControlState }
  | { kind: 'settings'; value: AppSettings }
  | { kind: 'sensors'; value: SensorState[] }
  | { kind: 'log'; value: ActivityEntry }
  | { kind: 'recorder'; value: RecorderSnapshot }
  | { kind: 'training'; value: TrainingJob }
  | { kind: 'recognition'; value: RecognitionState }
  | { kind: 'detection'; value: Detection }
  | { kind: 'action'; value: ActionOutcome }

const initial: AppState = {
  connection: 'connecting',
  clientId: null,
  loaded: false,
  status: null,
  sensors: [],
  control: null,
  settings: null,
  log: [],
  recorder: null,
  training: null,
  recognition: null,
  detections: [],
}

function reduce(state: AppState, action: Action): AppState {
  switch (action.kind) {
    case 'connection':
      return { ...state, connection: action.value, clientId: action.value === 'open' ? state.clientId : null }
    case 'hello': {
      const s = action.snapshot
      return {
        ...state,
        loaded: true,
        clientId: action.clientId,
        status: s.status,
        sensors: s.sensors,
        control: s.control,
        settings: s.settings,
        log: s.recent_log ?? [],
        recorder: s.recorder ?? null,
        training: s.training ?? null,
        recognition: s.recognition ?? null,
        detections: s.recognition?.detections ?? [],
      }
    }
    case 'status':
      return { ...state, status: action.value }
    case 'control':
      return { ...state, control: action.value }
    case 'settings':
      return { ...state, settings: action.value }
    case 'sensors':
      return { ...state, sensors: action.value }
    case 'log':
      return { ...state, log: [...state.log.slice(-199), action.value] }
    case 'recorder':
      return { ...state, recorder: action.value }
    case 'training': {
      const job = action.value
      const recent = [job, ...(state.training?.recent ?? []).filter((j) => j.job_id !== job.job_id)].slice(0, 10)
      const active = job.status === 'running' ? job : state.training?.active_job?.job_id === job.job_id ? null : state.training?.active_job ?? null
      return { ...state, training: { active_job: active, recent } }
    }
    case 'recognition':
      return { ...state, recognition: action.value }
    case 'detection':
      return { ...state, detections: [...state.detections.slice(-49), action.value] }
    case 'action': {
      if (!state.control) return state
      const history = [...state.control.history.slice(-49), action.value]
      return { ...state, control: { ...state.control, history } }
    }
    default:
      return state
  }
}

const StateContext = createContext<AppState>(initial)

const BASE_TOPICS = ['status', 'connections', 'log', 'recorder', 'training', 'predictions', 'detections', 'actions']

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, initial)

  useEffect(() => {
    const handlers: Record<string, (message: WsEnvelope) => void> = {
      status: (m) => {
        if (m.type === 'hello') {
          const data = m.data as { client_id: string; snapshot: Snapshot }
          dispatch({ kind: 'hello', clientId: data.client_id, snapshot: data.snapshot })
        } else if (m.type === 'status') dispatch({ kind: 'status', value: m.data as SystemStatus })
        else if (m.type === 'control') dispatch({ kind: 'control', value: m.data as ControlState })
        else if (m.type === 'settings') dispatch({ kind: 'settings', value: m.data as AppSettings })
      },
      connections: (m) => dispatch({ kind: 'sensors', value: (m.data as { sensors: SensorState[] }).sensors }),
      log: (m) => dispatch({ kind: 'log', value: m.data as ActivityEntry }),
      recorder: (m) => dispatch({ kind: 'recorder', value: m.data as RecorderSnapshot }),
      training: (m) => dispatch({ kind: 'training', value: m.data as TrainingJob }),
      predictions: (m) => {
        if (m.type === 'recognition') dispatch({ kind: 'recognition', value: m.data as RecognitionState })
      },
      detections: (m) => dispatch({ kind: 'detection', value: m.data as Detection }),
      actions: (m) => dispatch({ kind: 'action', value: m.data as ActionOutcome }),
    }
    const unsubscribers = BASE_TOPICS.map((topic) => wsClient.subscribe(topic, handlers[topic]))
    const unsubscribeState = wsClient.onState((value) => dispatch({ kind: 'connection', value }))
    wsClient.start()
    return () => {
      unsubscribers.forEach((fn) => fn())
      unsubscribeState()
    }
  }, [])

  return <StateContext.Provider value={state}>{children}</StateContext.Provider>
}

export function useAppState(): AppState {
  return useContext(StateContext)
}

export function useWorkspaceIsDemo(): boolean {
  const { status, settings } = useAppState()
  return status?.workspace === 'demo' || settings?.demo_mode === true
}

export function useStreamingSensors(): SensorState[] {
  return useAppState().sensors.filter((s) => s.status === 'streaming')
}
