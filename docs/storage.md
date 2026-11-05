# Storage

All runtime data lives under the data folder (default `data\` in the project) and the models folder (default `models\`). Both are git-ignored except their `.gitkeep` markers.

## Layout

```
data\
  app.db                         SQLite metadata and settings (plus app.db-journal while writing)
  raw\
    _staging\                    trials waiting for Save or Discard
    imports\<source>\            copies of imported files (originals are never modified)
    YYYY\MM\DD\                  saved recordings (UTC date)
      rec_<UTC time>_<label>_<sensor>_<4 hex>.csv
      rec_<UTC time>_<label>_<sensor>_<4 hex>.meta.json
    demo\...                     the same structure for Demo Mode
  processed\                     repaired derivatives: <derivative_id>.csv + manifest
  processed\demo\
  exports\                       dataset ZIPs
  exports\demo\
  logs\                          rotating JSON-lines activity log (backend.log, 2 MB, 3 backups)
  *.csv                          legacy CLI trials (src\collect.py), registered in place
models\
  <model_id>\model.joblib        app-trained models
  <model_id>\manifest.json
  demo\<model_id>\...            Demo Mode models
  gestures.joblib                legacy CLI model, if you train one with src\train.py
```

## Recordings are immutable

- Trials are written to `raw\_staging\` while recording. **Save** moves them into `raw\YYYY\MM\DD\` with exclusive-create (a file is never overwritten), computes a SHA-256 and registers the recording. **Discard** deletes staged files after confirmation.
- Saved files are never rewritten. Relabelling, notes, sessions and segments only change database metadata. Repairs create separate derivative files.
- `POST /api/recordings/{id}/revalidate` recomputes the hash; a mismatch is reported.
- `POST /api/recordings/recover` re-registers saved recordings from their `.meta.json` if the database lost them.

### CSV format

```
t_us,ax,ay,az,gx,gy,gz,host_rx_ns
1000000,0.012,-0.004,0.998,0.53,-0.10,0.07,1762300000123456789
```

The first seven columns are exactly what the firmware sends (device microseconds, g, deg/s). `host_rx_ns` is the host receive time in nanoseconds, used for latency and two-sensor alignment. Lines the parser rejected are not written. They are counted by reason in the metadata (`stream_counters`), which also keeps the 20 most recent rejected lines.

`GET /api/recorder/staging/{id}/export` downloads a staged trial in the legacy 7-column format that `src\train.py` reads. Dataset exports keep the stored 8-column files.

### Metadata (`.meta.json` and database)

Recording ID, workspace, kind (`trial` or `continuous`), source (`live`, `demo`, `import`, `legacy_cli`), label, sensor ID and hand, session ID, capture ID (shared by the files of one dual-sensor capture), UTC start time and device `t0`, duration (device time), sample count, measured median and mean rate, header alias, time unit, units, firmware header if seen, whether the column order was assumed, notes, validation state and report, provenance (origin, SHA-256, importer version), port, baud, recorder settings and stream counters.

## Imports

- **Known reference files:** only the three `imu_capture\recordings` files (`swipe_left.csv`, `swipe_right.csv`, `wrist_rotation.csv`). They are imported only when you click Import, copied into `raw\imports\` with their original path and SHA-256, and marked `continuous` (they need labelled segments before training).
- **Upload:** any CSV with `t_us` or `time_us` (device microseconds), or `time` with an explicit unit (s, ms or µs), plus `ax, ay, az, gx, gy, gz`.
- **Legacy CLI trials:** `data\<label>_<NNNN>.csv` files from `src\collect.py` are registered in place (non-recursive scan of that one folder) and never renamed or moved. If a registered file's hash changes, it is flagged.

## Datasets

A dataset is a list of database references to recordings, labelled segments, or derivatives. Nothing is copied. Deleting a dataset never deletes recordings. **Export** writes a ZIP to `data\exports\` with the stored raw files (`raw/`), any derivatives used (`derived/`), `labels.csv` and `manifest.json`.

## Deleting

- **Remove from library** (`mode=metadata`): forgets the recording, its segments, derivatives and dataset memberships; the file stays on disk.
- **Delete files** (`mode=disk`): also deletes the CSV, its `.meta.json` and its derivative files, but only for files the app created under `data\raw` or `data\processed` (including import copies). For legacy CLI files the request is refused (409 `disk_delete_not_allowed`); the original files you imported from are never touched.
- Models: deleting an app-trained model removes its folder; a legacy `models\gestures.joblib` is only unregistered.

## Database

SQLite at `data\app.db`, accessed through SQLAlchemy with `foreign_keys=ON`, `journal_mode=DELETE` (rollback journal, fewer files for OneDrive than WAL), `busy_timeout=10000` and `synchronous=NORMAL`. The schema version is stored in the `settings` table.

Tables: `settings`, `labels`, `label_changes`, `sensors`, `sessions`, `recordings`, `segments`, `derivatives`, `datasets`, `dataset_members`, `models`, `training_jobs`, `mapping_profiles`, `mappings`, `sync_measurements`.

## Changing the data folder

Settings → Storage writes `settings.local.json` in the project folder (git-ignored). The new folder is used after the next restart, and the page says so. The environment variables `GESTURE_TO_PC_DATA_DIR` and `GESTURE_TO_PC_MODELS_DIR` override both; the end-to-end tests use them to run in a temp folder.
