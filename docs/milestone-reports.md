# Milestone reports

All six milestones were built in one pass (2026-11-04 to 2026-11-05), as agreed. Every automated check below was last run on 2026-11-05 against the final code. Nothing has been committed: the repository was created locally with `git init` (no remote), and committing is left to you.

**Hardware status for every milestone:** no XIAO board was connected during development, so nothing was verified on hardware. Everything marked "works" was checked with tests, simulated serial ports, or Demo Mode. See [verification-log.md](verification-log.md).

Common commands:

```powershell
cd "C:\Users\taile\OneDrive\CSE 157\Project\XIAO_Gesture_Controller"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
cd frontend; npm install; npm run build; cd ..
.\scripts\start.ps1 -Open                       # http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m pytest
cd frontend; npm run test; npm run typecheck; npm run e2e
```

---

## M1 — Web foundation

**Files**
- Repository: `.gitignore`, local `git init`, `pyproject.toml` (pytest config), `requirements.txt` (backend packages appended to the 5 original lines), `requirements-dev.txt`, `data/{raw,processed,exports}/.gitkeep`.
- `README.md`: CSE 175 corrected to CSE 157; web-app section added; CLI instructions kept.
- Backend: `backend/run.py`, `backend/app/{main,container,wiring}.py`, `settings/`, `database/`, `api/{security,errors,deps,routes_system,routes_settings,routes_ws}.py`, `realtime/{hub,activity_log}.py`, `control/` state machine and Emergency Stop latch, `sensors/demo_device.py`.
- Frontend: Vite + React + TypeScript scaffold, Tailwind 4, shadcn/ui components, app shell (sidebar, top bar with mode chips and Emergency Stop), 10 routes, Dashboard, theme, `services/api.ts`, `services/ws.ts`.
- Tests: `test_security.py`, `test_settings.py`, `test_demo_stream.py`.

**Works:** backend on 127.0.0.1 with host, origin and per-launch token checks on REST and WebSocket; structured errors; persisted settings; activity log; WebSocket hub with topics, snapshot on connect and display-only dropping; Demo Mode as an isolated workspace with clearly labelled simulated sensors; Emergency Stop latch from the first milestone.

**Limits:** none specific beyond the hardware status.

**Checks:** security, settings and demo-stream tests pass.

**Manual:** opened every page in real and Demo Mode; confirmed the Demo banner and labels; Emergency Stop button latches and resets.

## M2 — USB integration

**Files:** `sensors/{ports,protocol,stream,bus,buffers,manager}.py`, `processing/timestamps.py`, `api/routes_sensors.py`; pages `SensorsPage.tsx`, `LiveDataPage.tsx`; charts `UPlotChart.tsx`, `LiveSignalChart.tsx`, `uplotHelpers.ts`; `hooks/useLiveSamples.ts`; tests `test_protocol.py`, `test_timestamps.py`, `test_serial_stream.py`.

**Works:** COM discovery; connect, disconnect, reconnect, remove; one owner per port with a clear "port in use" error; line assembler and parser (header aliases, headerless lines, diagnostics); per-sensor clock classifier (glitch, duplicate, out-of-order, wrap, reset, gaps); counters, measured device and arrival rates; stall detection, optional auto-reconnect, hardware-loss events; live charts with axis/magnitude selection, time window, pause, zoom (Shift/Ctrl + wheel) and pan, unit switching; buffer export.

**Limits:** the 32-bit `micros()` wrap is fixture-tested only. The firmware has no sequence numbers, so dropped samples are estimates.

**Checks:** protocol, timestamp and serial-stream tests pass (pyserial `loop://` and simulated unplug).

**Manual:** Sensor Connections in real mode with no ports shows the empty state and guidance; simulated sensor streams in Demo Mode; Live Sensor Data charts and counters update.

**Hardware unverified:** discovery, streaming, measured rate, unplug, port ownership.

## M3 — Recording and analysis

**Files:** `recordings/{recorder,storage,importer,library,labels,sessions,datasets}.py`, `processing/{csv_io,validation,repair,spectral,timeline}.py`, `api/routes_recordings.py`, `api/routes_datasets.py`; pages `RecorderPage.tsx`, `DatasetsPage.tsx`; components `datasets/*`, `StaticSignalChart.tsx`, `SpectrumPanel.tsx`, `PlotlyChart.tsx`; tests `test_csv_validation.py`, `test_repair_spectral.py`, `test_recorder.py`, `test_imports_datasets.py`; fixtures in `tests/fixtures/`.

**Works:** countdown trials (labels, sensors, duration, repeats, pause, sessions, notes), staging with preview, save (immutable, SHA-256, dated folders), discard with confirmation, legacy CSV export; continuous recordings with labelled segments; imports (three known `imu_capture` files on request, uploads, legacy CLI trials in place) with provenance; validation reports; explicit repair recipes and derivatives; datasets with class distribution, readiness, repair-flagged and ZIP export; label management (rename and merge are explicit and logged); metadata versus disk delete; FFT/STFT for recordings, derivatives and the live buffer.

**Limits:** flagged recordings can be used only through a derivative.

**Checks:** all four test files pass, including FFT/STFT parity with `imu_capture/plots` and read-only measurements of the three real recordings.

**Manual:** recorded, previewed, saved and discarded demo trials; dataset filter, preview, spectrum and export.

**Hardware unverified:** real recordings.

## M4 — Machine learning

**Files:** `ml/features/{registry,summary60_v1,stats_spectral_v1}.py`, `ml/{dataset_builder,evaluation,training,worker,artifacts,inference}.py`, `api/routes_ml.py`; pages `TrainingPage.tsx`, `RecognitionPage.tsx`; test `test_ml.py`.

**Works:** `summary-60-v1` delegated to `src/imu_utils.py` and pinned by a golden vector; `stats-spectral-v1`; peak-centred windows with shift augmentation; session-grouped `StratifiedGroupKFold` with "insufficient grouped data" instead of misleading metrics; background training process with progress and cancel; artifacts with manifests and SHA-256 trust; legacy `gestures.joblib` trust flow; compatibility checks; live recognition with smoothing, threshold, debounce, cooldown and idle re-arm.

**Limits:** quality on real gestures is unknown. Simulated runs: grouped accuracy 96.0 % and 76.0 % in two runs (2 sessions per class is too few for a stable estimate); scripted detection 11/12 and 10/12 with 0 wrong.

**Checks:** `test_ml.py` passes, including a full demo record → train → recognize → control test. End-to-end test trains and recognises through the UI.

**Manual:** trained on 32 simulated recordings; Live Recognition shows predictions and detections.

**Hardware unverified:** training and recognition on real gestures.

## M5 — Computer control

**Files:** `control/{actions,mappings,gate,executor,hotkey,service}.py`, routes in `api/routes_control.py` and `api/routes_ml.py`; page `MappingsPage.tsx`; components `control/ActionEditor.tsx`, `control/ArmDialog.tsx`, `layout/EmergencyStop.tsx`; test `test_control.py`.

**Works:** allowlisted actions only; profiles (suggested Browser navigation with every entry disabled, read-only Legacy CLI copy); simulation test per mapping; arming with confirmation and listed prerequisites; central gate checked before every OS call; Emergency Stop by button, WebSocket, REST, Shift+Esc, Win32 global hotkey while armed, and the PyAutoGUI fail-safe; every auto-disarm trigger; simulated executor in Demo Mode.

**Limits:** PyAutoGUI cannot control apps running as administrator (UIPI).

**Checks:** `test_control.py` (13 tests, including a regression test for the stale control state found on 2026-11-05) and the end-to-end arm → simulated action → Emergency Stop flow pass.

**Manual:** armed in Demo Mode, saw simulated actions, Emergency Stop latched and Reset.

**Hardware unverified:** real key and mouse output, the system-wide hotkey and the corner fail-safe with real input.

## M6 — Advanced features

**Files:** `sensors/sync.py`, `control/cursor.py`, `processing/activation.py`, `ml/airwriting.py`, `api/routes_advanced.py`; `SoundPage.tsx`; cursor, sync and air-writing panels; test `test_advanced.py`.

**Works (software):** dual-sensor recording with a shared capture ID and separate clocks; host-clock alignment and tap measurement; a sync gate (combined inference stays locked); calibrated cursor mode through the PC-control gate; sound-activation state machine with a labelled simulated microphone in Demo Mode; experimental DTW air-writing; performance endpoint.

**Unavailable (needs firmware):** sound activation with real hardware (no microphone stream in the firmware), Bluetooth LE (no GATT service). Combined two-sensor inference is not implemented.

**Performance (simulated sensor, this PC):** 100 Hz stream unaffected by training; no WebSocket drops; recognition 12 ms per window, 48 ms mean latency, 18 % CPU after making live prediction single-threaded.

**Checks:** `test_advanced.py` passes.

**Hardware unverified:** two-board recording and alignment, cursor mode, air-writing.

## Test and delivery additions (2026-11-05)

- Frontend unit tests (Vitest + Testing Library): format, units, live sample ring and backfill, API client and errors, WebSocket client, Emergency Stop.
- Playwright end-to-end tests on Edge with an isolated temporary backend.
- Fixes found by these: stale control state after settings changes, session token in the server log, unused `cn` package removed, form labels linked to their fields, training evaluation now honours the core count, live prediction single-threaded.
- Documentation in `docs/`, launch scripts in `scripts/`.
