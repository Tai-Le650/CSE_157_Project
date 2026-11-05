# Verification log

What has been checked, how, and what is still unverified. Results with simulated data are labelled as such; they show the software works, not how well real gestures will be recognised.

**Environment:** Windows 11 Home 10.0.26300, Python 3.14.3 (`.venv`), Node 24.13.1, Microsoft Edge (Playwright channel `msedge`). No XIAO board was connected and no COM port was present during development (2026-11-04 and 2026-11-05).

## Hardware: not verified yet

| Check | Status |
|---|---|
| COM discovery, connect, streaming, measured rate | **Not verified** (no board connected) |
| Header detection at boot vs. headerless start | **Not verified** |
| Unplug → disconnected → PC control disarms | **Not verified** with hardware (covered with a simulated serial port in tests) |
| Port ownership vs. Arduino Serial Monitor | **Not verified** |
| Real recording, validation, save, reload | **Not verified** |
| Training and recognition on real gestures | **Not verified** |
| Real keyboard/mouse actions while armed | **Not verified** |
| Emergency Stop: Ctrl+Alt+Backspace system-wide hotkey, PyAutoGUI corner fail-safe | **Not verified** with real input |
| Two boards: dual recording, tap alignment | **Not verified** |
| Cursor mode, air-writing | **Not verified** |
| 32-bit `micros()` wrap after ~71.6 min | Fixture-tested only |

The step-by-step checklist is in [hardware.md](hardware.md#hardware-verification-still-to-do). Record results here as they are done.

## Automated checks (all passing on 2026-11-05)

| Suite | Command | Result |
|---|---|---|
| Backend | `.\.venv\Scripts\python.exe -m pytest` | **102 passed** (about 66 s) |
| Frontend unit | `npm run test` | **31 passed** in 6 files |
| Type-check | `npm run typecheck` | clean (app, unit tests, end-to-end tests) |
| Lint | `npm run lint` | 0 errors, 86 warnings (React hook style rules; the 5 `jsx-key` warnings are false positives for values inside keyed rows) |
| End-to-end | `npm run e2e` | **15 passed** on Edge (about 1.5 min) |

### Backend tests by file

| File | Tests | Covers |
|---|---|---|
| `test_security.py` | 10 | Host, Origin and token checks on REST and WebSocket; token redaction in server logs |
| `test_settings.py` | 5 | Safe defaults, persistence across restarts, invalid values rejected, Demo Mode only through its confirmed endpoint, data-folder change needs a restart |
| `test_protocol.py` | 7 | Header aliases, sample lines, diagnostics, malformed lines; line assembler (partial first line, header as first line, overflow resync) |
| `test_timestamps.py` | 8 | Glitch, duplicate, out-of-order, wrap, reset, gap estimates |
| `test_serial_stream.py` | 7 | pyserial `loop://` streaming with counts and rates, one owner per port, port in use or missing, unplug and reconnect, stall and recovery, sensor identity changes, buffer export |
| `test_demo_stream.py` | 5 | Simulated sensors only in Demo Mode, real ports blocked in Demo Mode, labelled demo samples over the WebSocket, perform and disconnect, mode switch disconnects sensors |
| `test_csv_validation.py` | 8 | `t_us`/`time_us` aliases, `time` needs a unit, missing columns, invalid values counted by reason, glitches counted as invalid (not dropped), wraps/resets/duplicates/gaps, too few samples, the real `imu_capture` recordings |
| `test_repair_spectral.py` | 7 | Repair recipes (no sort), legacy-analyze parity, FFT/STFT parity with `imu_capture/plots` |
| `test_recorder.py` | 4 | Trials captured, staged and saved; stopping discards an unfinished trial; continuous recording with segments; needs a streaming sensor and an enabled label |
| `test_imports_datasets.py` | 8 | Known-source import with provenance, upload needs a time unit, legacy rescan in place, imports blocked in Demo Mode, dataset readiness/repair/export, flagged spectrum needs a recipe, delete modes, labels never merged implicitly |
| `test_ml.py` | 7 | summary-60-v1 golden vector and CLI parity, stats-spectral-v1, no group leakage, "insufficient grouped data", legacy trust and hash, end-to-end demo record → train → recognize → control |
| `test_control.py` | 13 | Gate conditions, allowlist, disarmed never executes, cooldown, repeat, Emergency Stop clears the queue, idle never acts, session and hardware loss disarm, stale requests, Demo never builds the real backend, control state re-published after setting and mode changes |
| `test_advanced.py` | 9 | Capabilities report honestly, cursor velocity and calibration, two-sensor sync measurement, dual-sensor capture, sound state machine and its real/Demo gate, DTW air-writing, performance endpoint |
| `test_cli_preserved.py` | 4 | `collect.py`, `control.py`, `check_stream.py --help` still exit 0; the backend never imports the CLI scripts |

### End-to-end tests (Playwright, Edge)

`01-pages.spec.ts` (real mode, fresh workspace): all 10 pages load without errors; the sidebar reaches every page; Sound Activation explains why it is unavailable; PC control is off by default and arming is refused with reasons; foreign origins (403) and missing tokens (401) are rejected.

`02-demo-workflow.spec.ts` (Demo Mode): enable Demo Mode → allow PC control → connect a simulated sensor → live chart → record and save 2 trials in the recorder UI → add 24 more trials in two sessions → build a dataset in the Dataset Manager → train (grouped evaluation reported) → start Live Recognition and detect a simulated swipe → enable a mapping → arm (simulated) → a simulated action is logged, nothing real executed → Emergency Stop latches and disarms → Reset.

## Manual browser checks (Chrome, Demo and real mode)

Every page was opened and exercised in the browser, in both modes. Problems found this way and fixed:

- Mouse-wheel zoom on charts captured page scrolling (now Shift/Ctrl + wheel).
- Live spectrum request was rejected (422) because of an extra field.
- Recording preview crashed on a missing `markers` field.
- Demo gestures happened too early in trials, so they were missed (added a realistic reaction delay; widened shift augmentation).
- Recognition counters on the page were stale.
- Settings showed "restart required" when nothing would change.
- Dark-mode chart colours were stale after switching theme.
- (2026-11-05, found by the end-to-end test) The PC-control panel and arm dialog kept showing the state from page load after Demo Mode or "Allow PC control" changed, for example "Arm real PC control" while in Demo Mode. The backend always simulated correctly, but the labels were wrong. The backend now re-publishes the control state after every settings change, with a regression test.
- (2026-11-05) The session token appeared in the server's console log (WebSocket URLs). It is now redacted, with a test.

## Measurements (Demo Mode, simulated 100 Hz sensor, this PC)

| Measurement | Result |
|---|---|
| Stream rate, idle | 99.98 samples/s (device rate 99.999 Hz) |
| Stream rate during a training job (32 recordings, 8.3 s) | 100.03 samples/s |
| Continuous recording made during the training job | 1 030 samples, validation *valid*, no gaps, no issues |
| WebSocket | 0 frames dropped, 0 samples dropped |
| Backend CPU, idle streaming | 3.9 % of one core, 6 threads |
| Grouped evaluation, 32 simulated recordings (4 per label per session, 2 sessions), stats-spectral-v1 | Run 1: accuracy 96.0 %, macro F1 0.96. Run 2: accuracy 76.0 %, macro F1 0.78. With only 2 sessions per class the estimate is very noisy |
| Live recognition, processing per window | about 12 ms (83 ms before live prediction was made single-threaded on 2026-11-05) |
| Live recognition latency (newest sample → prediction) | mean 48 ms, p95 60 ms (before the change: 94 / 114 ms) |
| Backend CPU during recognition | 18 % of one core, 7 threads (before: 64 %, 12 threads) |
| Scripted detections (12 simulated gestures, 3 s apart) | Run 2 model: 10 correct, 2 missed, 0 wrong. Run 1 model: 11 correct, 1 missed, 0 wrong |

Motion-to-action latency also includes the window length (1.0 s) and is not measured.

## Reference data (real recordings, read-only)

The three `imu_capture/recordings` files, analysed with the app's classifier (not modified, not imported):

| File | Rows | Timestamp glitches | Gaps (estimated missing) | Median / mean rate | Good rows |
|---|---|---|---|---|---|
| `swipe_left.csv` | 1231 | 3 | 13 (13) | 104.01 / 102.67 Hz | 1228 |
| `swipe_right.csv` | 1232 | 2 | 11 (11) | 104.01 / 102.92 Hz | 1230 |
| `wrist_rotation.csv` | 1262 | 1 | 14 (14) | 104.01 / 102.78 Hz | 1261 |

`analyze_gesture.py` kept only 575 of the 1231 `swipe_left` rows because it treats a glitch as a discontinuity. With the `legacy-analyze-v1` recipe the app reproduces that behaviour, and its FFT/STFT match `imu_capture/plots/swipe_left/gx/` (automated test).

## Scripts

- `scripts\start.ps1`: started on port 8767 with temporary data folders; `/api/health`, the app page and a deep link (`/recorder`) were served.
- `scripts\dev.ps1`: the Vite page on 5173 loaded and `/api` requests reached the backend through the proxy. Stopping the script stopped both servers (checked: ports 8000 and 5173 free). Ctrl+C in an interactive console was not tested.
