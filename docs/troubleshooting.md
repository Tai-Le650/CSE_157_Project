# Troubleshooting

## Starting the app

| Symptom | Fix |
|---|---|
| `Python environment not found` from `scripts\start.ps1` | The project's `.venv` is missing. Create it and install the requirements as in [setup-windows.md](setup-windows.md) |
| `ModuleNotFoundError: fastapi` (or uvicorn, sqlalchemy…) | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt` |
| Port 8000 already in use | Another backend is running, or another program uses the port. Close it, or run `.\scripts\start.ps1 -Port 8001` |
| Browser shows `frontend_not_built` | `cd frontend; npm install; npm run build`, or run `.\scripts\start.ps1 -Build` |
| `npm install` fails with EPERM or EBUSY | OneDrive is syncing `node_modules`. Pause OneDrive and retry |
| PowerShell refuses to run the scripts | Allow local scripts for your user: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Top bar shows the backend as disconnected | The backend stopped or restarted. The page reconnects by itself when it is back; reload if it does not |

## Sensors

| Symptom | Fix |
|---|---|
| No COM ports listed | Use a USB-C **data** cable, try another port, check Device Manager → Ports. Click **Refresh** |
| "Access denied" or "port in use" | Another program owns the port: close Arduino Serial Monitor/Plotter and `check_stream.py`, `collect.py`, `control.py`. Only one program can own a COM port |
| Connected but no samples | Baud must be 115200. Make sure the gesture_stream sketch is flashed and the board is the **Sense** variant |
| "Column order assumed" | Normal: the header is printed only at boot. Press the board's reset button while connected to see it detected |
| `ERROR: IMU initialization failed` | The IMU did not start. Re-flash, check the board variant and the Seeed LSM6DS3 library |
| Rate far from 100 Hz | The firmware polls every 10 ms. A very different rate means a different sketch or a USB problem; check the gap and invalid counters |
| Sensor goes *stalled* | No valid samples for 1.5 s (Settings → Acquisition). Check the cable; reconnect |
| Many glitches or clock resets | Glitches are single corrupted timestamps and are excluded automatically. Resets mean the board restarted (power or cable) |

## Recording and datasets

| Symptom | Fix |
|---|---|
| Trial marked *flagged* | It needs a repair recipe before training (Dataset Manager → open the recording → **Repair** tab, or **Repair flagged members** on a dataset) |
| Trial marked *invalid* | Too few valid samples (under 30) or none. Record it again |
| Dataset not ready | The Datasets tab lists the problems, for example missing Idle examples or a label with no data |
| "Insufficient grouped data" after training | Each label needs at least 2 independent sessions. Start a new session in the recorder and record every label again |
| Imported `imu_capture` file cannot be trained on | It is a continuous recording. Label segments on its preview first |

## Recognition and control

| Symptom | Fix |
|---|---|
| Model listed as incompatible | The reason is shown: other mode, untrusted legacy file, scikit-learn version mismatch, no Idle class, or similar. Retrain, or trust a legacy model you created |
| Recognition does not start: rate incompatible | The sensor's measured rate is outside 0.85–1.15 × the training rates. Use the same firmware as for training |
| Many false detections | Record more Idle data in every session, raise the threshold, increase debounce or cooldown |
| Missed gestures | Lower the threshold slightly, perform gestures as in training, check the window length, record more sessions |
| Arming refused | The dialog lists every reason. Typical ones: PC control not allowed in Settings, recognition not running, no enabled mapping, Emergency Stop latched |
| Disarms by itself | See *Automatic disarm* in [control-safety.md](control-safety.md). The last reason is shown on the Command Mapping page |
| Keys do nothing in an app | That app may run as administrator; Windows blocks input from a normal process into elevated windows (UIPI). Also check that the target window has focus |
| Global hotkey status says *failed* | Another program registered the same combination. Choose another in Settings; the other stop methods still work |
| Mouse in a screen corner stops everything | That is PyAutoGUI's fail-safe. Reset the Emergency Stop after moving the mouse away |

## Logs and diagnostics

- Activity log: Dashboard → Activity log, or `data\logs\backend.log` (JSON lines).
- `GET /api/advanced/performance`: CPU, threads, WebSocket drops, recognition latency.
- `http://127.0.0.1:8000/docs`: interactive API documentation.
