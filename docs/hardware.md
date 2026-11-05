# Hardware

## Supported setup

- Seeed Studio **XIAO MG24 Sense** (the Sense variant, with the LSM6DS3TR-C IMU), one or two boards.
- USB-C **data** cable to the Windows PC. Each board appears as its own COM port.
- Firmware: `firmware/gesture_stream/gesture_stream.ino`, unchanged. Flash it as described in the main README.

## What the firmware sends

| Property | Value | Consequence in the app |
|---|---|---|
| Baud | 115200 | Default baud in the connect form and Settings |
| Header | `t_us,ax,ay,az,gx,gy,gz`, printed **once at boot** | The board does not always reset when the port opens, so the header is often missed. Headerless 7-field lines are accepted, and the sensor card says the column order is assumed |
| Timestamp | `micros()` (32-bit) | Wraps every 2³² µs ≈ 71.6 minutes. The classifier unwraps it (tested with fixtures only, not on hardware yet) |
| IMU output data rate | 104 Hz | |
| Polling | every 10 ms | About 100 rows/s on the serial port. The app reports the rate it measures from device timestamps, not 104 Hz |
| Ranges | ±16 g, ±2000 deg/s | |
| Decimals | 3 | |
| Startup failure | `ERROR: IMU initialization failed`, repeated every second | Shown as a device error on the sensor card |

The firmware has no sequence numbers, so dropped samples can only be estimated from timestamp gaps. The app reports measured invalid counts and estimated drops separately.

### Other sketches in the project folder (reference only)

- `imu_capture/imu_capture.ino`: header `time_us,…`, a 9615 µs schedule (about 104 Hz), ±4 g / ±500 deg/s, 4 decimals, and it skips catch-up samples. Its three recordings measure a median of 104.01 Hz, with 1–3 corrupted timestamps each (see [validation-repair.md](validation-repair.md)).
- Lab 5 data (`Project Proposal Report/Le_Tai_lab05/data`) measures 104.00 Hz for both 104 Hz and 416 Hz output data rates, because that sketch also polls on a fixed schedule.
- The app accepts files from both sketches, but a dataset mixing very different rates is flagged.

## Using a board in the app

1. Close Arduino Serial Monitor/Plotter and the CLI scripts. Only one program can own a COM port.
2. Sensor Connections → pick the COM port → baud 115200 → set a sensor ID (for example `R` or `S1`) and the hand it is worn on → **Connect**.
3. The card should show *streaming*, a device rate near 100 Hz, and counters for lines, samples, malformed lines and clock events.
4. Strap the board firmly in the same position every session. Start a **new recording session** in the Gesture Recorder every time you re-mount it; evaluation keeps sessions apart.

Unplugging the board marks it *disconnected* and disarms PC control. Auto-reconnect (Settings, off by default) retries every 2 s and never re-arms.

## Two sensors

- **Dual-sensor recording:** select two streaming sensors in the recorder. Each sensor gets its own file and clock, linked by a shared capture ID.
- **Clock alignment:** each board's clock is mapped to the host clock from the lower envelope of receive delays. **Measure alignment** (Sensor Connections) asks you to tap both boards together about once per second and reports the measured error.
- **Combined two-sensor inference is not implemented.** The sync gate records whether a measured alignment would allow it (error at most 20 ms), so that decision can be made on evidence later.

## Features that need different firmware

| Feature | Status | What is needed |
|---|---|---|
| Sound activation | Unavailable with real hardware; works with a labelled simulated microphone in Demo Mode | Firmware that streams a microphone level alongside the IMU lines on the same link, for example `M,<t_us>,<level>`, with its own device timestamps, plus a documented line format. The Lab 4 microphone sketch streams raw ADC values (`S,<value>`) without IMU data, so it cannot run alongside gesture sensing |
| Bluetooth LE | Not implemented (Bleak is not installed) | Firmware exposing a BLE GATT service for IMU data, with documented service/characteristic UUIDs and packet format, and a battery setup |
| Cursor mode | Implemented through the PC-control gate; not verified on hardware | Calibrate while holding still, then tune gain, dead zone and speed cap. Velocity = gain × (gyro rate − bias), so position does not drift the way double-integrated acceleration would |
| Air-writing | Experimental 1-NN DTW baseline; not verified on hardware | Trials recorded per character |

## Hardware verification still to do

Nothing below has been run with a board yet (no COM port was present during development). The checklist with results lives in [verification-log.md](verification-log.md).

1. COM discovery, connect, streaming and measured rate (expect about 100 Hz).
2. Header-at-boot versus headerless start (press the board's reset button while connected).
3. Unplug while streaming → card shows disconnected; with PC control armed → it disarms.
4. Port ownership: the app refuses a port held by Arduino Serial Monitor, and vice versa.
5. Record, save, reload and preview real trials; validation report on real data.
6. Train on real sessions (at least 2 sessions per label) and run Live Recognition.
7. Armed real keyboard/mouse actions in a safe target (Notepad or a test browser tab).
8. Emergency Stop: button, Shift+Esc, Ctrl+Alt+Backspace while another window has focus, and the PyAutoGUI corner fail-safe.
9. Two boards: dual recording and the tap alignment measurement.
10. Cursor mode with calibration.
