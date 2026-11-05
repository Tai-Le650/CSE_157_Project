# Validation and repair

Every recording gets a validation report when it is saved or imported. Raw files are never modified: problems are fixed only by creating a **derivative** with an explicit, versioned repair recipe.

## Input format

| Column | Accepted | Unit |
|---|---|---|
| Time | `t_us` (gesture_stream firmware), `time_us` (imu_capture sketch), or `time` with an explicit unit chosen at import (s, ms, µs) | device microseconds after conversion |
| Acceleration | `ax, ay, az` | g |
| Angular rate | `gx, gy, gz` | deg/s |

The live parser also accepts headerless 7-field lines, because the board does not always reset when the port opens and the header (printed once at boot) is then missed. In that case the sensor card shows that the column order `t_us,ax,ay,az,gx,gy,gz` is assumed. Header lines, diagnostic lines such as `ERROR: IMU initialization failed`, and malformed lines are classified and counted separately.

Display conversions: m/s² = g × 9.80665 and rad/s = deg/s × π/180. Stored values keep the source units.

## Timestamp classifier (`processing/timestamps.py`)

The firmware has no sequence numbers, so the clock is the only evidence of lost or bad data. Each timestamp is judged against the running median interval, with one sample of lookahead (about 10 ms at 100 Hz):

| Case | Rule | Result |
|---|---|---|
| Normal | step forward within 50 × median | accepted |
| Gap | step forward more than 1.5 × median | accepted, flagged; estimated missing = round(Δ / median) − 1, minus any rows rejected in between (those arrived, they were not lost) |
| Duplicate | Δ = 0 | excluded, counted |
| Isolated glitch | a backward or wild value whose next sample continues normally (next − previous ≤ 3 × median) | excluded from display and inference, kept in the raw file |
| 32-bit `micros()` wrap | previous value within 10 s of 2³², new value below 10 s, and the next sample continues from it | unwrapped (+2³² µs) |
| Out of order | steps back by less than 1 s, and the new value is at least 5 s into the clock | excluded, counted |
| Reset | any other backward jump (or a new header line) | new clock **epoch** |

The glitch rule exists because of real data: the three `imu_capture` recordings each contain 1–3 rows whose timestamps lost leading digits (for example `368538339` became `538339`) while their neighbours stay continuous. `analyze_gesture.py` treated these as discontinuities and kept only 575 of the 1231 `swipe_left` rows. The classifier flags them as glitches and keeps the rest.

### Counters

- **Measured invalid counts:** malformed lines, non-finite values, glitches, duplicates and out-of-order rows. These are certain.
- **Estimated dropped samples:** derived from gaps. These are estimates.

The two are always reported separately. Rates are measured from device timestamps over good samples in the current epoch: `(n − 1) / span` and the median-interval rate. The line-arrival rate (host clock) is shown separately.

## Validation report (`processing/validation.py`, `validation-v1`)

| Issue code | Severity |
|---|---|
| `invalid_rows` (missing, non-numeric, non-finite or short fields) | repair required |
| `duplicate_timestamps` | repair required |
| `timestamp_glitches` | repair required |
| `out_of_order_timestamps` | repair required |
| `clock_resets` (file holds several clock epochs) | repair required |
| `micros_wrap` | repair required |
| `large_gaps` (longer than 50 ms) | repair required |
| `small_gaps` (bridged by interpolation when resampling) | info |
| `insufficient_samples` (fewer than 30 valid samples) | error |
| `no_valid_samples` | error |

The report also lists the column aliases and units, row counts, epochs, measured rates and the rate compatibility of a dataset (for example 57 Hz and 104 Hz recordings mixed together are flagged).

| State | Meaning |
|---|---|
| `valid` | Usable as is |
| `flagged` | Usable for training and analysis only through a repaired derivative |
| `invalid` | Not usable |

## Repair recipes (`processing/repair.py`, `repair-v1`)

A recipe is an ordered list of steps. There is deliberately **no sort step**: reordering rows would hide clock problems instead of handling them.

| Step | Options | Effect |
|---|---|---|
| `drop_invalid_rows` | | Remove rows with missing or non-finite values |
| `drop_duplicate_timestamps` | | Keep the first of repeated timestamps |
| `drop_timestamp_glitches` | `max_factor` (default 3) | Remove isolated glitches |
| `unwrap_micros` | | Undo 32-bit `micros()` wraps |
| `segments` | `split_at_resets`, `longest`, `longest_monotonic_raw` | Split at clock resets, keep the longest epoch, or keep the longest run without any backward step |
| `gaps` | `max_interpolate_ms` (default 50) | Start a new segment at gaps longer than the limit |
| `resample` | `target_hz` or `use_measured_median` | Linear resampling of each segment |

Presets:

| Preset | Steps | Use |
|---|---|---|
| `default-v1` | drop invalid → drop duplicates → drop glitches → unwrap → split at resets → split at gaps > 50 ms | Keeps original timestamps |
| `default-resampled-v1` | `default-v1`, then resample each segment to the measured median rate | Uniform sampling |
| `legacy-analyze-v1` | drop invalid → drop duplicates → longest monotonic run → resample to the median rate | Reproduces `imu_capture/analyze_gesture.py` exactly (used for the parity check) |

A derivative is written to `data\processed\<derivative_id>.csv` with a manifest: source recording ID and SHA-256, the full recipe, per-step row counts, output SHA-256 and resulting rate. Dataset members can point at a derivative, and **Repair flagged members** applies one recipe to every flagged member of a dataset after confirmation.

## Spectral analysis (`processing/spectral.py`)

`POST /api/analysis/spectrum` computes an FFT and an STFT for a recording, a derivative or the last seconds of the live buffer. Samples are resampled linearly to the measured median rate first.

- FFT: Hann window on the most energetic window (128 samples by default).
- STFT: Hann segments of 128 samples with a 32-sample hop by default (both adjustable per request).

With the `legacy-analyze-v1` preset these match `imu_capture/plots/swipe_left/gx/` exactly (pinned by a reference test).
