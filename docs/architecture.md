# Architecture

Gesture-to-PC is one local backend process plus a browser frontend. The CLI prototype in `src/` is unchanged and still works on its own.

```
XIAO MG24 Sense ──USB serial──► StreamReader thread (one per COM port)
                                   │ parse line → clock classifier → Sample
                                   ▼
                                SampleBus ──► Recorder sink (lossless, writes CSV)
                                   │      ──► Sync tracker (two-sensor alignment)
                                   ├──► RingBuffer per sensor (30 000 samples)
                                   │        └─► Recognition thread, live spectrum, buffer export
                                   └──► Hub.push_samples ──► WebSocket (batched every 50 ms, droppable)

Browser (React) ◄── REST /api/* and WebSocket /ws ──► FastAPI on 127.0.0.1:8000
Training job ──► separate process (multiprocessing, spawn) ──progress queue──► monitor thread
Detections ──► ControlService ──► executor thread ──► central gate ──► PyAutoGUI or simulated backend
```

## Backend (`backend/app`)

| Package | Responsibility |
|---|---|
| `main.py`, `container.py`, `wiring.py` | App factory, lifespan, dependency container, cross-service wiring |
| `settings/` | Root-relative paths (`paths.py`), launch config (`config.py`), persisted settings with validation (`service.py`) |
| `database/` | SQLite engine and pragmas, ORM models, schema version |
| `api/` | Routes, access guard (host, origin, session token), structured errors |
| `sensors/` | Port discovery, line protocol, serial stream reader, demo device, sample bus, ring buffers, sensor manager, two-sensor sync |
| `processing/` | CSV import, timestamp classifier, validation, repair recipes, spectra, timelines, sound-activation state machine |
| `recordings/` | Recorder, immutable storage, importer, library, labels, sessions, datasets |
| `ml/` | Feature registry, window builder, grouped evaluation, training worker, artifacts and trust, live inference, air-writing |
| `control/` | Action allowlist, mappings and profiles, gate, executors, Win32 hotkey, cursor mode, control service |
| `realtime/` | WebSocket hub and activity log |

### Threads and processes

| Thread or process | Work |
|---|---|
| uvicorn event loop | REST, WebSocket, hub flush loop (every 50 ms), status loop (every 1 s) |
| `stream-<sensor>` | Reads one COM port (or the demo device), assembles lines, parses and classifies timestamps, publishes samples |
| `sensor-health` | Rates, stall detection, optional auto-reconnect |
| `recognition` | Every hop: window → features → `predict_proba` → smoothing, threshold, debounce, cooldown, idle re-arm |
| `control-executor` | Runs queued actions through the gate immediately before each OS call |
| `control-monitor` | Heartbeat timeout and idle-timeout auto-disarm |
| `estop-hotkey` | Win32 `RegisterHotKey` message loop, only while armed |
| `cursor`, `demo-mic` | Advanced features (cursor mode; simulated microphone in Demo Mode) |
| training process | `multiprocessing` with the Windows `spawn` method, so model fitting never blocks acquisition. Progress returns over a queue |

Measured on the development PC with a simulated 100 Hz sensor: the stream stayed at 100.0 samples/s during a training job, and a continuous recording made during training had no gaps (see [verification-log.md](verification-log.md)).

### One owner per COM port

`SensorManager` opens each port once. A second connect to the same port is refused. If Windows denies access, the error explains that another program (Arduino Serial Monitor or a CLI script) probably holds it.

### Display versus data

Recording and inference read every sample. Only the browser display path can drop data: if a tab falls behind, the oldest queued sample frames for that tab are dropped and counted (`ui_frames_dropped`). Recordings are never affected.

## Demo Mode isolation

Demo Mode is a separate workspace, not just a flag on the UI:

- Only simulated sensors (`DEMO-<n>`) can connect. They generate firmware-format CSV lines that go through the same parser and clock checks as real hardware.
- Every action goes to the simulated executor. The real PyAutoGUI backend is never constructed in Demo Mode.
- Recordings, sessions, datasets and models carry `workspace = "demo"`, and their files live under `data/raw/demo/`, `data/processed/demo/`, `data/exports/demo/` and `models/demo/`. Queries filter by workspace, so real and demo data never mix.
- Switching modes requires confirmation, is refused while recording or training, disconnects sensors, stops recognition and disarms PC control.
- The UI shows a Demo banner and marks simulated values.

## Security model

- The server binds to `127.0.0.1` only. `TrustedHostMiddleware` accepts `127.0.0.1` and `localhost`.
- Allowed origins are `http://127.0.0.1:<port>` and `http://localhost:<port>` for the backend port and the Vite dev port (5173). Requests with any other `Origin`, and API requests marked `Sec-Fetch-Site: cross-site`, are rejected with 403. CORS uses the same allowlist.
- Each launch creates a random session token. `GET /api/session` returns it. Every state-changing REST call needs it in `X-Session-Token`, and the WebSocket needs it as `?token=`. The server log redacts it.
- File paths from the browser are never accepted. Imports use known-source keys or uploads.
- See [control-safety.md](control-safety.md) for how keyboard and mouse actions are gated.

## Frontend (`frontend/src`)

| Folder | Contents |
|---|---|
| `pages/` | The 10 pages: Dashboard, Sensor Connections, Live Sensor Data, Gesture Recorder, Dataset Manager, Model Training, Live Recognition, Command Mapping, Sound Activation, Settings |
| `components/` | Layout (sidebar, top bar, Emergency Stop), charts (uPlot live/static signals, Plotly FFT/STFT), dataset and control widgets, shadcn/ui primitives |
| `hooks/` | App state from the WebSocket snapshot and topics, live sample ring buffer, async helpers, theme |
| `services/` | `api.ts` (typed REST client, session token, structured errors) and `ws.ts` (reconnecting WebSocket client with reference-counted subscriptions) |
| `types/` | TypeScript mirrors of the backend schemas |

Stack: React 19, TypeScript 7, Vite 8, Tailwind CSS 4, shadcn/ui (Radix), Lucide icons, React Router 7, uPlot, and a lazily loaded Plotly cartesian bundle.
