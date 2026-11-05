# REST API

The backend serves a typed REST API under `/api`. The interactive OpenAPI documentation, with every request and response schema, is at `http://127.0.0.1:8000/docs` while the backend runs. This page lists the routes and the conventions they share. The WebSocket is described in [websocket-protocol.md](websocket-protocol.md).

## Conventions

- **Local only.** The server binds to `127.0.0.1`. Requests must use host `127.0.0.1` or `localhost`. A request with an `Origin` header outside the allowlist gets 403 `origin_rejected`, and an API request marked `Sec-Fetch-Site: cross-site` gets 403 `cross_site_rejected`.
- **Session token.** `GET /api/session` returns a token created at launch. Every `POST`, `PUT`, `PATCH` and `DELETE` (except `/api/session` and `/api/health`) must send it as `X-Session-Token`. A missing or wrong token gets 401 `invalid_session_token`. The frontend fetches a new token and retries once.
- **Errors** always have the same shape:

  ```json
  { "error": { "code": "arm_blocked", "message": "PC control cannot be armed", "details": { "reasons": ["..."] } } }
  ```

  Request validation failures return 422 with `code: "validation_error"` and the field errors in `details`. Conflicts with the current state (busy port, wrong mode, not ready) return 409.
- **Confirmation flags.** Destructive or risky calls require an explicit `confirm: true` (or `?confirm=true`): switching Demo Mode, arming, discarding staged trials, deleting recordings or models, renaming or merging labels, trusting a legacy model, and applying repairs to a whole dataset.
- **Workspaces.** Lists (recordings, sessions, datasets, models) only return items from the current mode (real or Demo).
- **No file paths from the browser.** Imports use known-source keys (`GET /api/imports/known`) or uploads. Stored paths are always relative to a fixed base folder and checked so they cannot escape it.
- **Units.** Stored samples keep the source units: acceleration in g, angular rate in deg/s, device time in microseconds.
- **Online demo (`run.py --hosted`).** Every visitor gets a private sandbox (see [hosting.md](hosting.md)), with these differences:
  - `GET /api/session` resumes the sandbox named by an `X-Session-Token` header, or creates a new one. The response adds `hosted: true` and `limits`; locally it returns `hosted: false` and `limits: null`.
  - Every request that reads or changes sandbox data needs the token, GET included. Only `/api/session`, `/api/health` and a few fixed lists, such as the action allowlist, work without it. An unknown or expired token gets 401 `invalid_session_token`.
  - An `Origin` header must match the request's own host.
  - New error codes:

    | Status | Code | When |
    |---|---|---|
    | 503 | `demo_full` | Every sandbox slot is taken |
    | 429 | `too_many_sandboxes` | Too many sandboxes from one client address |
    | 403 | `not_available_online` | Turning Demo Mode off, changing the data folder, trusting a legacy model |
    | 409 | `server_busy` | Another visitor's training job is running |
    | 409 | `server_busy_sensors` | The site-wide limit of streaming simulated sensors is reached |
    | 409 | `sensor_limit_online` | Too many simulated sensors in this sandbox |
    | 422 | `rate_limit_online` | Simulated rate above the online limit |

  - Training requests are capped (trees, folds, one CPU core), and the recognition hop has a minimum.
  - New sandboxes start with recognition settings sized for the server (`GET /api/settings` shows them).
  - `/api/ports` returns an empty list.
  - `/docs` is switched off.

## Routes

### System

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/session` | Per-launch session token for this browser (in the online demo: resume or create this visitor's sandbox) |
| GET | `/api/status` | Current modes and system status |
| GET | `/api/snapshot` | Full state snapshot (same as the WebSocket hello message) |
| GET | `/api/activity` | Recent activity log entries |
| GET | `/api/ports` | Discover Windows COM ports |

### Settings

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Read persisted settings |
| PATCH | `/api/settings` | Update settings (partial) |
| POST | `/api/settings/demo-mode` | Switch between real and Demo Mode |
| GET | `/api/settings/storage` | Data directory and storage locations |
| PUT | `/api/settings/storage` | Change the data directory (takes effect after restart) |

### Sensors and Demo devices

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sensors` | Connected and recently connected sensors |
| POST | `/api/sensors` | Connect a sensor |
| GET | `/api/sensors/known` | Sensor identities remembered from previous connections |
| GET | `/api/sensors/{sensor_id}` | Sensor health, counters and clock information |
| PATCH | `/api/sensors/{sensor_id}` | Change a sensor's ID (disconnected only) or Left/Right label |
| DELETE | `/api/sensors/{sensor_id}` | Disconnect and remove from the live list (remembered identity is kept) |
| POST | `/api/sensors/{sensor_id}/disconnect` | Disconnect and release the port |
| POST | `/api/sensors/{sensor_id}/reconnect` | Reconnect using the same port and settings |
| GET | `/api/sensors/{sensor_id}/buffer` | Export the live buffer (valid samples only) |
| POST | `/api/demo/sensors/{sensor_id}/perform` | Make a simulated sensor perform a synthetic gesture |
| POST | `/api/demo/sensors/{sensor_id}/auto` | Toggle random synthetic gestures on a simulated sensor |
| GET | `/api/demo/sensors/{sensor_id}/history` | Ground truth of gestures the simulator performed |

### PC control

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/control` | PC-control state: armed, Emergency Stop latch, counters, recent outcomes |
| GET | `/api/control/allowlist` | Action types and keys that may ever reach the OS |
| POST | `/api/control/arm` | Explicitly arm PC control |
| POST | `/api/control/disarm` | Disarm PC control |
| POST | `/api/control/emergency-stop` | Emergency Stop: disarm immediately, clear pending actions, latch until reset |
| POST | `/api/control/reset` | Reset the Emergency Stop latch (does not re-arm) |

### Recorder

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/recorder` | Recorder state and staged (unsaved) trials |
| POST | `/api/recorder/trials` | Start a set of countdown trials |
| POST | `/api/recorder/continuous` | Start a continuous (free-run) recording |
| POST | `/api/recorder/stop` | Stop the current recording |
| POST | `/api/recorder/session` | Start a new recording session (used for grouped evaluation) |
| GET | `/api/recorder/staging/{staging_id}/preview` | Preview a staged trial |
| PATCH | `/api/recorder/staging/{staging_id}` | Annotate or relabel a staged trial before saving |
| POST | `/api/recorder/staging/save` | Save staged trials into data/raw (immutable) |
| POST | `/api/recorder/staging/discard` | Permanently delete staged trials (requires confirm=true) |
| GET | `/api/recorder/staging/{staging_id}/export` | Download a staged trial as a legacy 7-column CSV |

### Recordings, segments and derivatives

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/recordings` | Search and filter recordings in the current mode |
| POST | `/api/recordings/recover` | Re-register app recordings whose metadata row is missing (from .meta.json files) |
| GET | `/api/recordings/recipes` | Available repair recipe presets |
| GET | `/api/recordings/{recording_id}` | Recording metadata, validation report, segments, derivatives and dataset membership |
| PATCH | `/api/recordings/{recording_id}` | Relabel, annotate, change kind or session |
| DELETE | `/api/recordings/{recording_id}` | Remove from the library (mode=metadata) or delete app-owned files (mode=disk) |
| GET | `/api/recordings/{recording_id}/preview` | Decimated signal preview with flagged-row markers and segments |
| GET | `/api/recordings/{recording_id}/file` | Download the original file exactly as stored |
| POST | `/api/recordings/{recording_id}/revalidate` | Recompute validation and check the file hash |
| POST | `/api/recordings/{recording_id}/segments` | Label a time range of a continuous recording |
| PATCH | `/api/recordings/segments/{segment_id}` | Edit a segment |
| DELETE | `/api/recordings/segments/{segment_id}` | Delete a segment |
| POST | `/api/recordings/{recording_id}/derivatives` | Create a repaired derivative with an explicit recipe |
| DELETE | `/api/recordings/derivatives/{derivative_id}` | Delete a derivative (its source recording is untouched) |

### Imports

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/imports/known` | Reference recordings that can be imported explicitly |
| POST | `/api/imports/known` | Import selected reference recordings (copied with SHA-256 provenance) |
| POST | `/api/imports/upload` | Import an uploaded CSV |
| POST | `/api/imports/legacy/rescan` | Register legacy CLI trials found directly under data/*.csv (in place) |

### Labels and sessions

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/labels` | Labels with usage counts |
| POST | `/api/labels` | Create a custom label |
| PATCH | `/api/labels/{label_id}` | Change a label's display name, description or enabled state |
| DELETE | `/api/labels/{label_id}` | Delete an unused custom label |
| POST | `/api/labels/{label_id}/rename` | Rename a custom label ID everywhere (explicit, logged) |
| POST | `/api/labels/merge` | Merge one label into another (explicit, logged; never automatic) |
| GET | `/api/labels/history/changes` | Label change log |
| GET | `/api/sessions` | Recording sessions in the current mode |
| POST | `/api/sessions` | Create a session |
| PATCH | `/api/sessions/{session_id}` | Rename or annotate a session |
| POST | `/api/sessions/assign` | Assign recordings to a session (or clear with session_id=null) |

### Datasets

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/datasets` | Datasets with class distribution |
| POST | `/api/datasets` | Create a dataset (metadata only; references recordings) |
| GET | `/api/datasets/{dataset_id}` | Dataset members, class distribution and training readiness |
| PATCH | `/api/datasets/{dataset_id}` | Rename or describe a dataset |
| DELETE | `/api/datasets/{dataset_id}` | Delete a dataset definition (recordings are untouched) |
| POST | `/api/datasets/{dataset_id}/members` | Add trials or labeled segments |
| POST | `/api/datasets/{dataset_id}/members/remove` | Remove members (recordings stay in the library) |
| PUT | `/api/datasets/{dataset_id}/members/{member_id}/derivative` | Choose which repaired derivative a member uses |
| POST | `/api/datasets/{dataset_id}/repair-flagged` | Explicitly apply a repair recipe to every flagged member |
| POST | `/api/datasets/{dataset_id}/export` | Export the dataset as a ZIP (raw files, derivatives, manifest) |

### Analysis

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analysis/spectrum` | FFT and STFT of a recording, derivative or the live buffer |

### Training and models

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/training/features` | Available versioned feature pipelines |
| GET | `/api/training/jobs` | Recent training jobs |
| POST | `/api/training/jobs` | Start a background training job |
| GET | `/api/training/jobs/{job_id}` | Training job status and results |
| POST | `/api/training/jobs/{job_id}/cancel` | Cancel a running job (terminates the worker process) |
| GET | `/api/models` | Models in the current mode, with compatibility checks |
| GET | `/api/models/{model_id}` | Model detail including the full manifest |
| PATCH | `/api/models/{model_id}` | Rename a model |
| DELETE | `/api/models/{model_id}` | Delete an app-trained model (legacy CLI files are only unregistered) |
| POST | `/api/models/{model_id}/select` | Select the model used by Live Recognition |
| POST | `/api/models/{model_id}/trust` | Trust a local legacy CLI model after confirmation (joblib can execute code) |

### Recognition

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/recognition` | Recognition state, last prediction and recent detections |
| POST | `/api/recognition/start` | Start continuous recognition |
| POST | `/api/recognition/stop` | Stop recognition (also disarms PC control) |

### Command mapping

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/mappings/profiles` | Mapping profiles and their mappings |
| POST | `/api/mappings/profiles` | Create a profile (optionally copying another; copied entries start disabled) |
| PATCH | `/api/mappings/profiles/{profile_id}` | Rename a profile |
| DELETE | `/api/mappings/profiles/{profile_id}` | Delete a profile |
| PUT | `/api/mappings/active` | Choose the active profile (disarms PC control if it changes) |
| PUT | `/api/mappings/profiles/{profile_id}/labels/{label_id}` | Create or update a mapping (allowlisted actions only) |
| DELETE | `/api/mappings/profiles/{profile_id}/labels/{label_id}` | Remove a mapping |
| POST | `/api/mappings/simulate` | Describe what a mapping would do without touching the OS |
| GET | `/api/mappings/allowlist` | Allowed action types and keys |

### Advanced features

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/advanced/capabilities` | What advanced features are available, verified or unavailable |
| GET | `/api/advanced/sync` | Clock alignment per sensor and recent synchronization measurements |
| POST | `/api/advanced/sync/measure` | Measure two-sensor alignment with simultaneous taps |
| GET | `/api/advanced/sync/gate` | Whether a recorded measurement would permit combined inference for a sensor pair |
| GET | `/api/advanced/cursor` | Cursor-mode state and calibration |
| POST | `/api/advanced/cursor/calibrate` | Measure gyro bias while the sensor is held still |
| POST | `/api/advanced/cursor/start` | Start cursor mode (PC control must be armed) |
| POST | `/api/advanced/cursor/stop` | Stop cursor mode |
| GET | `/api/advanced/sound` | Sound-activation availability and state |
| POST | `/api/advanced/sound/demo/start` | Start the simulated microphone (Demo Mode only) |
| POST | `/api/advanced/sound/demo/stop` | Stop the simulated microphone |
| POST | `/api/advanced/sound/demo/clap` | Inject a simulated activation sound |
| POST | `/api/advanced/airwriting/classify` | Classify a recording or the last seconds of live data with an air-writing model (experimental) |
| GET | `/api/advanced/performance` | Measured backend CPU use, threads, WebSocket drops and recognition latency |
| GET | `/api/advanced/sound/requirements` | Why sound activation is unavailable with the current firmware |

