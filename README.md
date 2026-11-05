# XIAO MG24 Sense — USB Gesture Controller Starter

This is a **starting prototype** for the CSE 157 hand-gesture/sound-activated computer controller. It implements **one wired XIAO MG24 Sense** reading a six-axis IMU, collecting training examples, training a random-forest classifier, and using recognized gestures as desktop keyboard commands. It does not yet implement microphone activation, BLE, 2-sensor fusion, cursor tracking, or finger-key typing.

## Gesture-to-PC web app

**Gesture-to-PC** is a local web app built on top of this prototype. It covers the whole workflow in the browser: connect sensors → live data → record trials → manage datasets → train → live recognition → map gestures to keyboard/mouse commands → PC control, with an always-visible Emergency Stop. It runs only on this PC (`127.0.0.1`), and the command-line tools below keep working unchanged.

```powershell
cd "C:\Users\taile\OneDrive\CSE 157\Project\XIAO_Gesture_Controller"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
cd frontend; npm install; npm run build; cd ..
.\scripts\start.ps1 -Open          # http://127.0.0.1:8000
```

- **No board?** Turn on **Demo Mode** in Settings: simulated sensors, simulated actions and a separate demo workspace, all clearly labelled.
- **PC control is off by default.** It must be allowed in Settings and then armed explicitly; Emergency Stop works from the button, Shift+Esc, and Ctrl+Alt+Backspace while armed.
- **One program per COM port:** close the CLI scripts and Arduino Serial Monitor before connecting a board in the app.
- **Status:** the software is complete and tested (backend, frontend unit and end-to-end tests, Demo Mode), but it has **not yet been verified with a connected board**. Sound activation with real hardware and Bluetooth LE need firmware that does not exist yet.

| Document | Contents |
|---|---|
| [docs/setup-windows.md](docs/setup-windows.md) | Install, run, development mode, tests |
| [docs/architecture.md](docs/architecture.md) | Components, threads, Demo Mode isolation, security |
| [docs/hardware.md](docs/hardware.md) | Firmware facts, using boards, hardware checklist |
| [docs/control-safety.md](docs/control-safety.md) | Arming, gate, allowlist, Emergency Stop, auto-disarm |
| [docs/ml-pipeline.md](docs/ml-pipeline.md) | Features, windows, grouped evaluation, models, recognition |
| [docs/validation-repair.md](docs/validation-repair.md) | Timestamp checks, validation reports, repair recipes |
| [docs/storage.md](docs/storage.md) | Files, metadata, database, imports, deleting |
| [docs/api.md](docs/api.md) · [docs/websocket-protocol.md](docs/websocket-protocol.md) | REST routes and WebSocket messages |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |
| [docs/verification-log.md](docs/verification-log.md) · [docs/milestone-reports.md](docs/milestone-reports.md) | What was tested, measured and still unverified |

The rest of this README documents the original command-line prototype.

## Hardware

- Seeed Studio XIAO MG24 **Sense** (not the non-Sense variant)
- USB-C **data** cable to Windows computer
- Fabric strap/tape to secure the board consistently to the back of one hand or wrist

## 1. Arduino IDE setup

1. Install Arduino IDE 2.x.
2. `File > Preferences > Additional Boards Manager URLs` add:
   `https://siliconlabs.github.io/arduino/package_arduinosilabs_index.json`
3. Restart Arduino IDE, open Boards Manager, install the Silicon Labs Arduino board package for **XIAO MG24** and select the **XIAO MG24** board.
4. Install **Seeed Arduino LSM6DS3** (Seeed Studio). If the library manager does not find it, download the repository ZIP from `https://github.com/Seeed-Studio/Seeed_Arduino_LSM6DS3` and choose `Sketch > Include Library > Add .ZIP Library`.
5. Open `firmware/gesture_stream/gesture_stream.ino` in Arduino IDE.
6. Connect the board, select its COM port (e.g. COM5), and click Upload.
7. Open Arduino Serial Monitor, set **115200 baud**, and look for `t_us,ax,ay,az,gx,gy,gz` followed by numeric rows. Gently rotate the board; the values must change. **Close Serial Monitor** before using Python.

The IMU is set internally to 104 Hz; the Arduino sketch polls it every 10 ms (nominally ~100 serial rows per second). The printed serial rows are not a guarantee of precisely 104 samples/sec.

## 2. Windows terminal / VS Code setup

Open this folder in VS Code. In PowerShell or Command Prompt at the folder root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

All commands below work without activating the virtual environment (replace `COM5` with **your** COM port):

```powershell
.\.venv\Scripts\python.exe src/check_stream.py --port COM5
```

Expected: numeric samples and an observed rate around 100 rows/sec.

If you're not sure which port to use:

```powershell
.\.venv\Scripts\python.exe -m serial.tools.list_ports
```

## 3. Record labeled examples

Wear/hold the IMU securely in the same position for every trial. Perform the motion as soon as `GO!` appears, then finish within about 0.9 seconds. Record stillness (`idle`) as well as three gestures.

```powershell
.\.venv\Scripts\python.exe src/collect.py --port COM5 --trials 25
```

This creates `data/idle_0001.csv`, `data/swipe_left_0001.csv`, `data/swipe_right_0001.csv`, `data/flick_up_0001.csv`, etc. Each file is **one trial**, with columns `t_us,ax,ay,az,gx,gy,gz`. **Collect at least 25 clean windows per gesture** to start; ideally add more across multiple sessions. The Python program waits for you to press Enter for every recording. Make the gesture immediately after the `GO!` cue; collect `idle` using the same starting pose without moving.

**Naming:** Left/right/up gestures are whatever physical motions you demonstrate repeatedly. They are not built into the model.

## 4. Train model

```powershell
.\.venv\Scripts\python.exe src/train.py
```

Reports a preliminary class precision/recall/F1 and writes `models/gestures.joblib`. Evaluation here randomly holds out 20% of recorded windows, so results may be optimistic compared to a different wearing session. Re-train after adding more CSV examples.

## 5. Preview live recognition (NO keyboard keys yet)

```powershell
.\.venv\Scripts\python.exe src/control.py --port COM5
```

Prediction examples:

- `idle` — no action and rearms detection
- `swipe_left` — would press Left Arrow
- `swipe_right` — would press Right Arrow
- `flick_up` — would press Space

Test that idle is recognized while not moving; if false actions appear, gather more representative idle/gesture data and retrain. Raise `--threshold` if necessary (e.g. `--threshold 0.92`). Random forest probabilities are not inherently calibrated certainty scores.

## 6. Enable real keyboard control

Open PowerPoint (slide show), a video player, or another app that responds to arrow/space keys. Click its window so it has focus, and run:

```powershell
.\.venv\Scripts\python.exe src/control.py --port COM5 --actions
```

The running terminal only displays predictions and will send the key to **whichever window is focused**. In presentation mode, arrows may advance/return slides. Space typically pauses/plays a video or advances a slide, depending on the app. Stop with `Ctrl+C`.

## Troubleshooting

- **Access denied / Port busy:** close Arduino Serial Monitor, Serial Plotter, and other Python scripts. Only one process can access the COM port at a time.
- **No serial data:** verify correct port, USB *data* cable, 115200 baud, Sense version, sketch upload, and the Seeed LSM6DS3 library.
- **`ModuleNotFoundError`:** use `.venv` Python interpreter above and reinstall requirements.
- **Weak recognition or accidental triggers:** strap the sensor consistently, increase samples per class, add more `idle` data, perform gestures clearly, and test model on data from a separate collection session.
- **No key effect:** ensure `--actions` is supplied and the target app has keyboard focus.
- **`PD5` compiler error:** make sure you chose XIAO MG24 in Arduino boards, not a different Seeed board.
- **Train/test:** a random window split is useful for first iteration, not a rigorous independent assessment. Collect a new recording session for final accuracy claims.

## Next engineering milestones

1. Refine gesture detection with movement-onset segmentation and real held-out sessions (otherwise a sliding 0.9s window can miss fast motions).
2. Add **mouse control** using gyroscope/tilt-to-cursor mapping with calibration/dead zones; do not naively double-integrate acceleration for long-term screen position because drift accumulates.
3. Add **microphone wake**: detect an acoustic event and temporarily enable gesture actions. This is distinct from speech recognition.
4. Move USB transport to Bluetooth Low Energy (BLE). The host receiver will need a matching BLE service/protocol; a wireless board needs a suitable battery and safe charging setup.
5. Add a second sensor and synchronize both data streams before fusing signals. Two wrist IMUs by themselves are generally insufficient to identify each finger/key in ordinary typing; that goal likely needs extra finger-mounted sensors or another modality.

## Verified reference docs

- [Seeed XIAO MG24 getting started](https://wiki.seeedstudio.com/xiao_mg24_getting_started/)
- [Seeed XIAO MG24 Sense IMU](https://wiki.seeedstudio.com/xiao_mg24_sense_built_in_sensor/)
- [Seeed Arduino LSM6DS3](https://github.com/Seeed-Studio/Seeed_Arduino_LSM6DS3)
- [PySerial](https://pyserial.readthedocs.io/en/latest/shortintro.html)
