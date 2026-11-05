# Machine-learning pipeline

Dataset → windows → versioned features → grouped evaluation → final RandomForest → trusted artifact → live recognition with gating.

## Labels

| Label ID | Display name | State |
|---|---|---|
| `idle` | Idle / No Gesture | enabled; required in every model, never triggers an action |
| `swipe_left` | Swipe Left | enabled |
| `swipe_right` | Swipe Right | enabled |
| `wrist_rotation` | Twist (Wrist Rotation) | enabled |
| `swipe_up`, `swipe_down`, `tap`, `double_tap`, `circle` | | defined, disabled until you enable them |
| `flick_up` | Flick Up (legacy CLI) | defined, disabled; kept distinct from `swipe_up` |

Custom labels use `[a-z0-9_]`. Renaming an ID or merging labels is an explicit, logged action. Legacy file names are never renamed. Recordings with a disabled label stay valid.

## Feature pipelines (`ml/features/`)

| Version | Input | Window | Features |
|---|---|---|---|
| `summary-60-v1` | raw samples (not resampled), at least 30 per window | 0.9 s | The legacy CLI contract, computed by `src/imu_utils.extract_features` itself (loaded by file path, never by importing the CLI scripts). 6 axes × 10: mean, std, min, max, p10, p90, mean absolute difference, and 3 time-bin means. A golden-vector test pins it |
| `stats-spectral-v1` (default) | linear resampling to 100 Hz (`resample-linear-100hz-v1`); a gap over 50 ms rejects the window | 1.0 s | 8 channels (ax..gz, \|a\|, \|ω\|) × 8: mean, std, min, max, RMS, energy, dominant frequency (Hann window, DC excluded), spectral energy = 64 features |
| `airwriting-dtw-v1` (experimental) | gyro sequence of each trial, resampled to 32 points | whole trial | 1-nearest-neighbour dynamic time warping (band 20 %). Used only from the Air-writing panel |

`summary-60-v1` includes position-dependent time bins, so it works best on trial-aligned windows. For live sliding windows, `stats-spectral-v1` is recommended.

## Windows (`ml/dataset_builder.py`)

- **Trials:** one window centred on the peak of the smoothed gyro magnitude (50 ms smoothing). With augmentation (stats-spectral-v1 only), four more windows shifted by −0.25, −0.12, +0.12 and +0.25 s are added. Shifted windows stay inside the trial's clock epoch.
- **Short trials:** with `summary-60-v1`, a trial no longer than the window (+0.06 s) is used whole, as the CLI does. Otherwise a trial shorter than the window is rejected with the reason `shorter_than_window`.
- **Idle:** idle trials and segments at least 1.5 windows long give several non-overlapping windows.
- **Continuous recordings:** never used as single trials. Only their labelled segments are used.
- Rejected windows are counted by reason and shown with the training results.

## Grouped evaluation (`ml/evaluation.py`)

- Windows are grouped by **session** (one session = one sensor mounting). Recordings without a session are grouped by recording, and the dataset shows a `missing_sessions` warning because that can be optimistic.
- All windows from one recording, including its shifted copies, are in the same group, so augmentation cannot leak between train and test. A test asserts that no group appears in both.
- `StratifiedGroupKFold` with k = max(2, min(5, fewest groups of any label)), shuffled with `random_state = 42`.
- If any label has fewer than 2 groups, the result is **"insufficient grouped data"**: the classes that lack groups are listed and **no metrics are reported**.
- Reported: accuracy, macro and per-class precision/recall/F1, a confusion matrix summed over folds, windows and groups per class, and per-fold details.

With only two sessions per class the estimate is noisy: the same simulated recording protocol gave 96.0 % and 76.0 % accuracy in two runs (see [verification-log.md](verification-log.md)). Record more sessions for a stable estimate.

## Training jobs (`ml/training.py`, `ml/worker.py`)

- Each job runs in a separate process (Windows `spawn`), so acquisition and the UI never wait for it. Progress is published on the `training` topic: loading → windows → evaluating (fold k of n) → final fit → saving. **Cancel** terminates the process.
- RandomForest defaults match the CLI: 300 trees, `random_state = 42`, `class_weight = "balanced_subsample"`, plus `n_jobs = 2` threads.
- Job records keep the configuration, the evaluation, the rejected-window counts and any error.

## Artifacts and trust (`ml/artifacts.py`)

Each model is a folder `models\<model_id>\`:

- `model.joblib`: a plain dictionary `{model, feature_version, window_seconds, labels, model_id}` (no custom classes).
- `manifest.json`: name, feature version and preprocessing, window, labels and idle labels, rate requirements, training recordings with their SHA-256 hashes, evaluation, classifier parameters, library versions, and the artifact's SHA-256.

joblib files can run code when loaded, so:

- App-trained models are registered with the SHA-256 the app computed, and every load re-hashes the file. A mismatch is refused (`model_hash_mismatch`).
- A legacy `models\gestures.joblib` from `src\train.py` is registered as **untrusted** until you confirm you created it. If its hash changes later, it becomes untrusted again.

A model is shown as incompatible, with the reason, when it belongs to the other mode (Demo or real), is not trusted, is missing, has an unknown feature version, was trained with a different scikit-learn major.minor version, has no idle class, has unknown labels, or has a window outside 0.2–5 s.

**Rate requirement:** a model accepts sensors measuring between 0.85 × the lowest and 1.15 × the highest median rate of its training recordings. Recognition refuses to start (or pauses) outside that range.

## Live recognition (`ml/inference.py`)

Every hop (default 0.1 s) the recognition thread:

1. Takes the newest window of good samples in the current clock epoch. It skips the window if the newest sample is more than 0.5 s old, if the measured rate is outside the model's range, or if the feature pipeline rejects it (too few samples, a long gap).
2. Extracts features and runs `predict_proba` (single-threaded; one window at a time is faster without a thread pool).
3. Averages the last K = 3 probability vectors, applies the threshold (0.85), requires 2 consecutive windows (debounce), enforces a cooldown (1.2 s), and by default requires a confident idle window before the next detection.
4. Publishes every prediction, and each detection with its mapped action and outcome. Idle never triggers an action.

All of these are adjustable on the Live Recognition page and saved as defaults in Settings.

The reported latency is the measured processing latency: newest sample received → prediction published. Motion-to-action latency also includes the window length and is not measured.
