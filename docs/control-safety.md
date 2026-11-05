# PC-control safety

Recognised gestures can press keys, click and scroll in whichever window has focus. That is only possible after several deliberate steps, and many things stop it.

## Off by default, armed explicitly

1. **Allow PC control** (Settings → PC control) is a persisted master switch. It defaults to **off**, and turning it on needs a confirmation. While it is off, arming is impossible.
2. **Arm** (Command Mapping or Dashboard) opens a dialog listing the active profile's enabled mappings and the running recognizer. Arming is refused, with every reason listed, unless all of these hold:
   - PC control is allowed in Settings and the Emergency Stop is not latched;
   - the request carries explicit confirmation;
   - this browser tab's live control session (its WebSocket) is connected;
   - Live Recognition is running with a model from the current mode, on a sensor that is streaming;
   - the active profile has at least one enabled mapping;
   - if Settings requires sound activation, a sound source is available.
3. The armed state lives only in memory. It is never saved, so every backend start begins disarmed.

## The central gate

The executor thread checks the gate (`control/gate.py`) **immediately before every OS call**, not when the gesture is detected:

| Check | Blocks with |
|---|---|
| Emergency Stop latched | `emergency_stop_latched` |
| Not armed | `not_armed` |
| Request queued before the latest arm or disarm (arm generation changed) | `stale_request` |
| Mode changed since arming | `workspace_changed` |
| Control session gone or silent | `control_session_lost` |
| Sensor not streaming | `sensor_unhealthy` |
| Action not on the allowlist | `action_not_allowlisted` |
| Idle label | `idle_never_acts` |
| Same detection already acted on | `repeat_detection` |
| Cooldown not over | `cooldown` |
| Sound activation required but not active | `sound_activation_inactive` |

Every outcome (executed, simulated, blocked with reason) is published on the `actions` topic, shown under **Recent action outcomes**, and logged.

## Allowlist (`control/actions.py`)

| Type | Allowed |
|---|---|
| `key` | arrows, space, enter, tab, esc, page up/down, home, end, a–z, 0–9, F1–F12, volume up/down/mute, play/pause, next/previous track |
| `hotkey` | 1–3 of Ctrl/Alt/Shift plus one allowed key. Blocked: Alt+F4, Ctrl+Shift+Esc, Ctrl+Alt+Esc. The Windows key is not available at all |
| `click` | left, right or middle button |
| `double_click` | left button |
| `scroll` | 1–20 notches up or down (one notch = one wheel click, 120 units on Windows) |
| `mouse_move` | cursor mode only, at most 400 px per step |

There is no text typing, no program launching, no shell command and no way for the browser to send a command or executable. Mappings are validated against these schemas on the server.

## Emergency Stop

Ways to trigger it:

- the red **Emergency Stop** button in the top bar (and on the Dashboard and Command Mapping pages), which uses both the WebSocket fast path and REST;
- **Shift+Esc** while the app's tab has focus;
- a **system-wide hotkey**, default **Ctrl+Alt+Backspace**, registered with Win32 `RegisterHotKey` **only while armed** (configurable in Settings; the status is shown, for example if another program already owns the combination);
- PyAutoGUI's **fail-safe**: if the mouse pointer is in a screen corner when an action is about to run, PyAutoGUI refuses it and the app latches the Emergency Stop.

Effect: PC control disarms, every pending action is cleared, and the arm generation changes so anything already queued is refused. The stop stays **latched** until you press Reset, and Reset does not re-arm. Acquisition, recording and recognition keep running.

## Automatic disarm

| Trigger | Reason shown |
|---|---|
| Recognition sensor lost, stalled, disconnected or failed to open | `sensor_<event>:<sensor>` |
| Live Recognition stopped | `recognition_stopped` |
| Active profile changed, or a mapping in it edited | `mappings_changed` |
| No heartbeat from the arming tab for 3 s (configurable) | `control_session_heartbeat_lost` |
| Arming tab closed or its WebSocket dropped | `control_session_closed` |
| Demo Mode switched on or off | `mode_changed` |
| Allow PC control switched off | `pc_control_disabled` |
| No executed action for 10 minutes (configurable, 0 = never) | `idle_timeout` |
| Unexpected executor error | `executor_error` |
| Backend shutdown | `shutdown` |

Reconnecting a sensor (manually or with auto-reconnect) never re-arms.

## Executors

- `PyAutoGuiBackend` performs real input, with PyAutoGUI's fail-safe on. It is created only outside Demo Mode.
- `SimulatedBackend` performs nothing and records what would have happened (for example "would press Ctrl+Tab"). Demo Mode always uses it.
- The tests use a recording fake and check that Demo Mode never constructs the real backend.

## Profiles

| Profile | Mappings | Notes |
|---|---|---|
| Browser navigation (suggested) | `swipe_left` → Ctrl+Shift+Tab (previous tab), `swipe_right` → Ctrl+Tab (next tab), `wrist_rotation` → scroll down 3 notches | Every entry starts **disabled**. Review and enable the ones you want |
| Legacy CLI (preserved) | `swipe_left` → Left, `swipe_right` → Right, `flick_up` → Space | Exact copy of `src/control.py`, read-only. Duplicate it to change anything (copies start disabled) |

Each mapping has a **Test** button that describes the action without sending anything to the OS.

## Limits

- Windows blocks input from a normal process into windows running as administrator (UIPI). PyAutoGUI cannot control elevated apps unless the backend also runs elevated, which is not recommended.
- The system-wide hotkey needs Windows. If another program has registered the same combination, registration fails and the status says so; the other stop methods still work.
- Real keyboard and mouse control has not been verified with hardware yet. See [verification-log.md](verification-log.md).
