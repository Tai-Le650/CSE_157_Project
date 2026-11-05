# Online demo (hosting)

Gesture-to-PC can run as a public website, but only as a **Demo Mode** copy. The real app needs the PC that the XIAO board is plugged into: the backend reads the board over USB and presses keys and moves the mouse on that same PC. A server on the internet can do neither for a visitor, so the online version simulates sensors and actions. Real boards and real PC control stay in the local app, which hosted mode does not change.

| | Local app (`run.py`) | Online demo (`run.py --hosted`) |
|---|---|---|
| Who can open it | Only this PC (`127.0.0.1`) | Anyone with the link |
| Sensors | Real XIAO boards and simulated sensors | Simulated sensors only (Demo Mode is locked on) |
| Keyboard and mouse actions | Real (after arming) or simulated | Always simulated |
| Data | Kept in `data\` and `models\` | Private temporary sandbox per visitor, deleted when idle |
| Imports, data folder, trusting legacy CLI models | Available | Refused with 403 `not_available_online` |

## How the online demo works

`backend\run.py --hosted` starts a different app factory (`backend/app/hosting/app.py`). It does not create one shared backend state. Instead, `SandboxRegistry` (`backend/app/hosting/sandboxes.py`) gives every browser its own **sandbox**: a complete `AppContainer` with its own SQLite database, recordings, datasets and models in a temporary folder, with Demo Mode switched on.

- **Finding the sandbox.** `GET /api/session` returns the sandbox token. The frontend keeps it in `localStorage` and sends it as `X-Session-Token` on every request (GET included) and as `?token=` on the WebSocket. Sending a live token to `/api/session` resumes that sandbox, so refreshing the page or opening another tab keeps the same data. An unknown or expired token creates a new sandbox.
- **Expiry.** A sandbox is closed and its folder deleted after `GESTURE_TO_PC_SANDBOX_IDLE_MINUTES` without an open tab, or after `GESTURE_TO_PC_SANDBOX_MAX_MINUTES` in any case. Open tabs then get a fresh sandbox and a short "Your demo sandbox expired" notice, and the page reloads.
- **Same-origin only.** Requests with an `Origin` header must come from the site itself (the origin has to match the request's `Host`), so no host list needs configuring. The `Sec-Fetch-Site: cross-site` check stays. Docs pages (`/docs`, `/openapi.json`) are switched off.
- **No access to the server.** PyAutoGUI is not installed in the image, OS control and the global hotkey are disabled in the config, `/api/ports` returns an empty list, and Demo Mode cannot be turned off. Visitors cannot upload files or load model files the sandbox did not train itself.
- **Restarts lose sandboxes.** Sandboxes live in memory and in a temporary folder, so a server restart or redeploy starts everyone fresh. This is why the server must run as exactly **one** instance.

## Limits

The free Render plan is 512 MB of RAM and 0.1 CPU (a tenth of one core). Memory is not the problem: the busiest measured run peaked at about 370 MB (see [Measured on the free plan's limits](#measured-on-the-free-plans-limits)). CPU is. Each streaming simulated sensor uses about a third of the free CPU, and a 300-tree forest at the local recognition settings could not keep up. So the online demo:

- streams at most two simulated sensors at once **for all visitors together**
- pauses a visitor's sensors one minute after their last tab closes (they can reconnect on Sensor Connections)
- trains one model at a time with small forests
- starts every sandbox with recognition settings that work with a slower hop

The local app's stricter detection settings (threshold 0.85, smoothing 3, debounce 2, hop 0.1 s) exist to stop accidental real keypresses. Online, every action is simulated, so a lower threshold is safe there.

Each limit can be changed with an environment variable (values outside the allowed range are clamped):

| Variable | Default | What it limits |
|---|---|---|
| `GESTURE_TO_PC_MAX_SANDBOXES` | 3 | Sandboxes at once; more visitors get 503 `demo_full` |
| `GESTURE_TO_PC_MAX_SANDBOXES_PER_IP` | 2 | Sandboxes per client address; more get 429 `too_many_sandboxes` |
| `GESTURE_TO_PC_SANDBOX_IDLE_MINUTES` | 10 | Minutes without an open tab before a sandbox is deleted |
| `GESTURE_TO_PC_SANDBOX_MAX_MINUTES` | 60 | Maximum sandbox age, even with a tab open |
| `GESTURE_TO_PC_MAX_STREAMING_SENSORS` | 2 | Simulated sensors streaming at once across all sandboxes; more get 409 `server_busy_sensors` |
| `GESTURE_TO_PC_MAX_SENSORS` | 2 | Simulated sensors streaming at once per sandbox |
| `GESTURE_TO_PC_MAX_DEMO_RATE_HZ` | 120 | Simulated sample rate |
| `GESTURE_TO_PC_MAX_TREES` | 30 | Random-forest size (the local default is 300) |
| `GESTURE_TO_PC_MAX_FOLDS` | 3 | Cross-validation folds (the local default is 5) |
| `GESTURE_TO_PC_MIN_HOP_S` | 0.25 | Seconds between recognition windows; also each new sandbox's default hop (the local default is 0.1) |
| `GESTURE_TO_PC_DEFAULT_THRESHOLD` | 0.7 | Each new sandbox's detection threshold (local default 0.85) |
| `GESTURE_TO_PC_DEFAULT_SMOOTHING_K` | 1 | Each new sandbox's smoothing window count (local default 3) |
| `GESTURE_TO_PC_DEFAULT_DEBOUNCE_N` | 1 | Each new sandbox's debounce window count (local default 2) |
| `GESTURE_TO_PC_PROJECT_URL` | unset | Link shown in the online-demo banner |

Visitors can still change the recognition settings on the Live Recognition page; the hop cannot go below the minimum.

The per-address limit is best effort: it reads the client address from the `X-Forwarded-For` header set by Render's proxy, which a determined client can fake. The overall `GESTURE_TO_PC_MAX_SANDBOXES` cap is what protects the server's memory.

Training always uses one CPU core online, and a second visitor who starts training while another job runs gets 409 `server_busy`. Other settings: `PORT` (default 10000) sets the port, `GESTURE_TO_PC_BIND_HOST` (default `0.0.0.0`) the listening address, and `GESTURE_TO_PC_SANDBOX_DIR` the sandbox folder (default: the system temp folder). On start-up the server only deletes folders named `sbx-` plus 16 hex digits inside that folder.

## Deploying to Render (free plan)

The repository contains everything Render needs: `Dockerfile` (builds the React frontend, then a Python 3.14 image with `requirements-hosted.txt`), `.dockerignore`, and `render.yaml` (a Render Blueprint for one free web service in Oregon with health check `/api/health`).

First deploy:

1. Commit and push to `main` on GitHub.
2. On [render.com](https://render.com), sign up with GitHub (no card needed) and allow Render to read the repository.
3. Choose **New → Blueprint**, pick the repository, and click **Apply**. Render reads `render.yaml` and builds the Docker image (a few minutes the first time).
4. The site is live at `https://<service-name>.onrender.com`. Render shows the exact address on the service page.

After that, every push to `main` rebuilds and redeploys automatically (`autoDeployTrigger: commit`). Logs are on the service's **Logs** tab: sandbox creation and cleanup, warnings and errors appear there.

How the free plan behaves:

- The service sleeps after 15 minutes without traffic. The next visitor waits about a minute while it wakes up, and the page says so. An open tab keeps it awake, because WebSocket messages count as traffic.
- Each workspace gets 750 free instance hours a month, enough for one service running all month.
- The disk is wiped on every restart, which is fine because sandboxes are temporary.

If the free plan is too slow, change `plan: free` to `plan: starter` in `render.yaml` ($7/month, 0.5 CPU, still 512 MB). No code changes are needed.

## Running the online demo locally

Without Docker (from the project root):

```powershell
$env:GESTURE_TO_PC_BIND_HOST = '127.0.0.1'
.\.venv\Scripts\python.exe backend\run.py --hosted --port 8766
```

Open `http://127.0.0.1:8766`. Setting `GESTURE_TO_PC_BIND_HOST` keeps it on this PC and avoids a Windows Firewall prompt. A second browser profile or a private window acts as a second visitor.

With Docker, limited to the same memory and CPU as Render's free plan:

```powershell
docker build -t gesture-to-pc .
docker run --rm -p 10000:10000 --cpus 0.1 --memory 512m --memory-swap 512m gesture-to-pc
docker stats
```

Open `http://localhost:10000` and run the Demo workflow (connect a simulated sensor, record, build a dataset, train, recognize, map and arm with simulated actions) while `docker stats` shows the memory use.

Tests: `tests/backend/test_hosted.py` covers sandboxes, limits and blocked features, and `npm run e2e` runs `frontend/e2e/03-hosted.spec.ts` against a second backend started with `--hosted`.

## Measured on the free plan's limits

Measured on 2026-11-05 with the Docker image limited exactly like Render's free plan (`--cpus 0.1 --memory 512m --memory-swap 512m`) on the development PC. Render's real hardware may be faster or slower.

**Final settings (the defaults above), two visitors at once:** both had a simulated sensor streaming and a live chart open while one recorded, trained and ran recognition.

| Measurement | Result |
|---|---|
| Server start until `/api/health` answers | 16–49 s across runs (Render adds its own wake-up time) |
| Creating a sandbox | under 1 s |
| Recording 24 trials (8 sets of 3) | 52 s |
| Training (300 trees requested, capped to 30, 3 folds) | 31 s, grouped accuracy 0.91 |
| Live recognition (hop 0.25 s, threshold 0.7, smoothing 1, debounce 1) | 8 of 8 simulated swipes detected, no false detections, latency mean 34 ms, p95 45 ms |
| Live chart updates, both visitors, during recording, training and recognition | median every 100 ms (10 per second), slowest 399 ms |
| Peak memory | 168 MB with two sensors streaming, 304 MB during training, 321 MB during recognition (limit 512 MB) |
| Third simulated sensor on the site / third sandbox from one address | refused with 409 `server_busy_sensors` / 429 `too_many_sandboxes` |

**What did not work with the local settings:**

- With 100-tree forests and two live charts, recognition took about 0.9 s per window and caught none of 4 swipes.
- With one visitor and 100 trees at a 0.25 s hop, recognition still fell behind (2.8 of 4 windows per second).
- At a 0.25 s hop, the local smoothing 3 and debounce 2 caught at most 1 of 6 swipes, because a half-second swipe only fills one or two windows.
- With the 30-tree model, smoothing 1 and debounce 1: threshold 0.85 caught 3 to 5 of 6–8 swipes, 0.7 caught 8 of 8, and 0.6 started confusing swipe directions.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| "Connecting to the online demo…" for about a minute | The free service was asleep | Wait; it wakes up on the first visit |
| "The online demo is full right now" | `GESTURE_TO_PC_MAX_SANDBOXES` sandboxes are in use | Try again later, or raise the limit on a bigger plan |
| "Your network already has the most demo sandboxes allowed" | Too many sandboxes from one address (separate browsers or private windows) | Close other Gesture-to-PC browsers or windows; tabs in one browser share a sandbox |
| "Your demo sandbox expired…" and a reload | The sandbox reached its idle or maximum age, or the server restarted | Nothing; a fresh sandbox starts |
| Training answers "Another visitor is training a model right now" | One training job at a time across the site | Try again in a minute |
| Connecting a simulated sensor answers "The free demo server is already running … simulated sensor(s)" | `GESTURE_TO_PC_MAX_STREAMING_SENSORS` sensors are streaming for other visitors | Try again in a few minutes; sensors of visitors who left are paused after a minute |
| My simulated sensor shows as disconnected after I came back | No tab was open for a minute, so its sensor was paused to save CPU | Reconnect it on Sensor Connections; your recordings and models are still there |
| The service is restarted with an out-of-memory error in the Render logs | Peak memory went over 512 MB | Lower `GESTURE_TO_PC_MAX_SANDBOXES` or `GESTURE_TO_PC_MAX_TREES`, or move to a plan with more memory |
