# WebSocket protocol

One WebSocket per browser tab carries live data and state changes: `ws://127.0.0.1:8000/ws?token=<session token>`.

## Connecting

1. `GET /api/session` returns the per-launch token.
2. Open `/ws?token=<token>`. The server checks the `Origin` header against the same allowlist as REST, and the token. On failure it closes with code **1008** and reason `origin_rejected` or `invalid_session_token`. The frontend then fetches a fresh token before reconnecting.
3. The first message is `hello`, carrying a `client_id` and a full state snapshot (the same data as `GET /api/snapshot`). After every reconnect the client rebuilds its state from this snapshot.

The `client_id` doubles as the **control session**: arming PC control is tied to the tab that armed it. See [control-safety.md](control-safety.md).

## Envelope

Every server message uses the same envelope:

```json
{ "v": 1, "type": "samples", "topic": "samples:S1", "seq": 1234, "ts": 1762300000.123, "data": { } }
```

| Field | Meaning |
|---|---|
| `v` | Protocol version (1) |
| `type` | Message type, listed below |
| `topic` | Topic the message was published on |
| `seq` | Server-wide increasing sequence number |
| `ts` | Server time (Unix seconds) when the message was created |
| `data` | Payload |

## Client messages

| Message | Effect |
|---|---|
| `{"type":"subscribe","topics":["predictions","samples:S1"]}` | Add topics. Unknown topic prefixes are ignored. The server answers `subscribed` with the full topic list |
| `{"type":"unsubscribe","topics":["samples:S1"]}` | Remove topics. The server answers `subscribed` |
| `{"type":"heartbeat"}` | Keeps the control session alive. The frontend sends one every second |
| `{"type":"estop"}` | Emergency Stop fast path (same effect as `POST /api/control/emergency-stop`) |
| `{"type":"ping"}` | Server answers `pong` |

Invalid JSON or an unknown message type gets an `error` message on the `status` topic. The connection stays open.

## Topics

A client subscribes to exact topics such as `samples:S1`, or to all topics with a prefix using `samples:*`.

| Topic | Message types | Content |
|---|---|---|
| `status` | `hello`, `status`, `settings`, `control`, `subscribed`, `pong`, `error` | System status (every second and on change), persisted settings after each change, PC-control state after each change |
| `connections` | `connections` | Sensor list with status, counters, clock epochs and measured rates |
| `samples:<sensor>` | `samples` | Batched samples (see below) |
| `predictions` | `prediction`, `recognition` | Every recognition window (probabilities, smoothed score, gating state) and recognizer state |
| `detections` | `detection` | Accepted gestures with mapped action and outcome |
| `actions` | `action` | Outcome of each action request (executed, simulated, blocked with reason) |
| `training` | `training` | Training job progress and results |
| `recorder` | `recorder` | Recorder state and staged trials |
| `log` | `log` | Activity log entries |
| `sound` | `sound` | Sound-activation state and recent levels (Demo Mode only) |
| `cursor` | `cursor` | Cursor-mode state |
| `sync` | `sync` | Two-sensor clock alignment |
| `spectra:<sensor>` | (none yet) | Reserved. Live spectra are requested with `POST /api/analysis/spectrum` (`source: "live"`) |

### Sample batches

Samples are batched every 50 ms per sensor:

```json
{
  "sensor_id": "S1", "simulated": false, "epoch": 1,
  "t_us": [1000000, 1009615],
  "ax": [0.01, 0.02], "ay": [0.0, 0.0], "az": [1.0, 0.99],
  "gx": [0.5, 0.4], "gy": [0.0, 0.1], "gz": [-0.2, -0.1]
}
```

- `t_us` is the device timestamp after unwrapping, in microseconds. Rows flagged as glitches, duplicates or out-of-order are not sent.
- `epoch` changes when the device clock restarts (board reset). The frontend clears its chart buffer on a new epoch.
- Units are the source units: g and deg/s.

## Back-pressure

Each client has two queues:

- **Priority** (never dropped): everything except samples.
- **Frames** (droppable): sample batches, at most 40 per client. When a slow tab falls behind, the oldest frames are dropped and counted in `ui_frames_dropped` (shown by `GET /api/advanced/performance`).

Dropping only affects that tab's display. Recording, inference and the other tabs still get every sample. If the backend cannot hand samples to the WebSocket layer at all (more than 4 000 pending per sensor), the excess is counted as `ui_samples_dropped`.

## Frontend client

`frontend/src/services/ws.ts`:

- Reconnects with exponential backoff (800 ms, then up to 10 s) and re-subscribes to every topic in use.
- Reference-counts subscriptions: the first listener for a topic sends `subscribe`, and the last one to leave sends `unsubscribe`.
- `useLiveSamples` first loads up to 60 s of history from `GET /api/sensors/{id}/buffer?fmt=json`, then applies live batches that arrived in the meantime, skipping samples it already holds.
