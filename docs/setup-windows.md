# Setup on Windows 11

Gesture-to-PC runs entirely on this PC. One Python process (`backend\run.py`) serves the REST API, the WebSocket and the built React frontend on `http://127.0.0.1:8000`. It never listens on other network interfaces.

## Requirements

| Tool | Version used during development | Used for |
|---|---|---|
| Windows 11 | 10.0.26300 | |
| Python | 3.14.3, in the project's existing `.venv` | Backend. The `.venv` was reused; packages were only added, never upgraded or removed |
| Node.js / npm | 24.13.1 / 11.8.0 | Building and testing the frontend only |
| Microsoft Edge | ships with Windows | Playwright end-to-end tests (no browser download) |
| Arduino IDE 2.x | | Flashing `firmware/gesture_stream` (see the main README) |

## Install

From PowerShell:

```powershell
cd "C:\Users\taile\OneDrive\CSE 157\Project\XIAO_Gesture_Controller (Interface)"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
cd frontend
npm install
npm run build
cd ..
```

- `requirements.txt` keeps the five original CLI lines and appends the backend packages (FastAPI, uvicorn, SQLAlchemy, pandas, pydantic, python-multipart).
- `requirements-dev.txt` adds pytest and httpx.
- `npm run build` type-checks and writes `frontend\dist`, which the backend serves.

## Run

```powershell
.\scripts\start.ps1           # builds the frontend if frontend\dist is missing, then serves http://127.0.0.1:8000
.\scripts\start.ps1 -Open     # also opens the default browser
.\scripts\start.ps1 -Build    # rebuilds the frontend first
.\scripts\start.ps1 -Port 8001
```

The script is a thin wrapper around `.\.venv\Scripts\python.exe backend\run.py [--port N] [--open] [--no-frontend]`.

Stop with Ctrl+C. Shutting the backend down disarms PC control and releases every COM port.

### Development mode (hot reload)

```powershell
.\scripts\dev.ps1
```

This starts the backend API on port 8000 without the static frontend, and the Vite dev server on `http://127.0.0.1:5173`, which proxies `/api` and `/ws` to the backend. Ctrl+C stops both.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest     # backend unit, API and WebSocket tests
cd frontend
npm run test        # Vitest unit tests
npm run typecheck   # TypeScript for the app, unit tests and end-to-end tests
npm run lint        # oxlint
npm run e2e         # builds the frontend, then runs Playwright on Edge
```

- `pytest` never runs `src\train.py` and never touches the real `data\` or `models\` folders. Tests marked `reference` read the three `imu_capture\recordings` files and are skipped if they are missing.
- `npm run e2e` starts its own backends: the local app on port 8765 and the online demo (`--hosted`, bound to 127.0.0.1) on port 8766, with data, models and sandboxes in `%TEMP%\gesture-to-pc-e2e\run-<timestamp>\`. It never touches `data\` or `models\`, and those temp folders can be deleted at any time. `npx playwright test --project=local` or `--project=hosted` runs one of them.
- The end-to-end tests use Demo Mode only. They never arm real PC control.

## Online demo

`backend\run.py --hosted` runs the public, Demo-Mode-only website instead of the local app. [hosting.md](hosting.md) explains how it works, its limits, how to run it locally (with or without Docker), and how to deploy it to Render.

## Notes

- **OneDrive:** the project is inside OneDrive. If `npm install` fails with EPERM or EBUSY, pause OneDrive syncing and retry. The database uses SQLite's rollback journal (not WAL) so fewer files change while the app runs.
- **COM ports:** only one program can open a COM port. Close Arduino Serial Monitor/Plotter and the CLI scripts (`check_stream.py`, `collect.py`, `control.py`) before connecting a board in the app, and vice versa.
- **Storage:** see [storage.md](storage.md). Runtime files (`data\app.db`, recordings, exports, models, logs, `settings.local.json`) are git-ignored.
