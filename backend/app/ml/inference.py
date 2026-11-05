from __future__ import annotations

import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np

from ..api.errors import AppError, conflict
from ..control.actions import describe_action, parse_gesture_action
from .features.registry import WindowRejected

STALE_DATA_S = 0.5


class RecognitionEngine:
    snapshot_key = "recognition"

    def __init__(self, sensors: Any, registry: Any, settings: Any, hub: Any, activity: Any, control: Any, mappings: Any, src_dir: Path, workspace_provider):
        self.sensors = sensors
        self.registry = registry
        self.settings = settings
        self.hub = hub
        self.activity = activity
        self.control = control
        self.mappings = mappings
        self.src_dir = src_dir
        self.workspace = workspace_provider
        self.running = False
        self.model = None
        self.sensor_id: str | None = None
        self.config: dict = {}
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.history: deque[dict] = deque(maxlen=60)
        self.detections: deque[dict] = deque(maxlen=50)
        self.counters: Counter = Counter()
        self.last_prediction: dict | None = None
        self.message = ""
        self.started_at: float | None = None
        sensors.add_listener(self._on_sensor_event)

    def state(self) -> dict:
        model = self.model
        return {
            "running": self.running,
            "model": {"model_id": model.model_id, "name": model.name, "feature_version": model.feature.version, "window_s": model.window_s, "labels": model.labels, "idle_labels": model.idle_labels, "source": model.source, "rate_requirements": model.rate_requirements} if model else None,
            "sensor_id": self.sensor_id,
            "config": self.config,
            "last_prediction": self.last_prediction,
            "detections": list(self.detections)[-20:],
            "counters": dict(self.counters),
            "message": self.message,
            "started_at": self.started_at,
        }

    def snapshot(self) -> dict:
        return self.state()

    def publish_state(self) -> None:
        self.hub.publish("predictions", "recognition", self.state())

    def _choose_sensor(self, sensor_id: str | None) -> str:
        if sensor_id:
            return sensor_id
        selected = self.settings.current.selected_sensor_id
        if selected and selected in self.sensors.sessions:
            return selected
        streaming = [s.sensor_id for s in self.sensors.sessions.values() if s.status == "streaming"]
        if len(streaming) == 1:
            return streaming[0]
        raise conflict("sensor_required", "Choose which sensor to recognise from")

    def start(self, model_id: str | None = None, sensor_id: str | None = None, overrides: dict | None = None) -> dict:
        if self.running:
            raise conflict("recognition_running", "Recognition is already running; stop it first")
        settings = self.settings.current
        model_id = model_id or settings.selected_model_id
        if not model_id:
            raise conflict("no_model_selected", "Select a trained model on the Model Training page first")
        sensor_id = self._choose_sensor(sensor_id)
        model = self.registry.load(model_id)
        if model.workspace != self.workspace():
            raise conflict("model_workspace_mismatch", "Demo models work only in Demo Mode and real models only outside it")
        session = self.sensors.get(sensor_id)
        if session.status != "streaming":
            raise conflict("sensor_not_streaming", f"Sensor {sensor_id} is {session.status}")
        config = {**settings.inference.model_dump(), **(overrides or {})}
        requirement = model.rate_requirements
        measured = session.last_rates.get("device_hz")
        if requirement.get("accept_min_hz") and measured:
            if not (requirement["accept_min_hz"] <= measured <= requirement["accept_max_hz"]):
                raise conflict(
                    "rate_incompatible",
                    f"Sensor {sensor_id} measures {measured:.1f} Hz but the model was trained on {requirement['training_fs_min_hz']:.1f}–{requirement['training_fs_max_hz']:.1f} Hz",
                    {"measured_hz": measured, **requirement},
                )
        if hasattr(model.estimator, "n_jobs"):
            model.estimator.n_jobs = 1
        self.model = model
        self.sensor_id = sensor_id
        self.config = {**config, "window_s": model.window_s}
        self.counters = Counter()
        self.history.clear()
        self.last_prediction = None
        self.message = "Running"
        self.stop_event = threading.Event()
        self.running = True
        self.started_at = time.time()
        self.control.monitored_sensors = lambda: {sensor_id}
        self.thread = threading.Thread(target=self._loop, name="recognition", daemon=True)
        self.thread.start()
        if settings.selected_model_id != model_id or settings.selected_sensor_id != sensor_id:
            self.settings.update({"selected_model_id": model_id, "selected_sensor_id": sensor_id})
        self.activity.info("recognition", f"Recognition started: {model.name} on {sensor_id}", model_id=model_id, sensor_id=sensor_id)
        self.publish_state()
        return self.state()

    def stop(self, reason: str = "user") -> dict:
        if not self.running:
            return self.state()
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        self.running = False
        self.message = f"Stopped ({reason})"
        self.control.disarm("recognition_stopped")
        self.activity.info("recognition", f"Recognition stopped ({reason})")
        self.publish_state()
        return self.state()

    def on_shutdown(self) -> None:
        self.stop("shutdown")

    def _on_sensor_event(self, event: str, sensor_id: str, _data: dict) -> None:
        if self.running and sensor_id == self.sensor_id and event in ("lost", "disconnected", "open_failed"):
            threading.Thread(target=self.stop, args=(f"sensor {event}",), daemon=True).start()

    def _loop(self) -> None:
        model = self.model
        config = self.config
        hop = float(config["hop_s"])
        threshold = float(config["threshold"])
        debounce = int(config["debounce_n"])
        cooldown = float(config["cooldown_s"])
        require_rearm = bool(config["require_idle_rearm"])
        smoothing = deque(maxlen=int(config["smoothing_k"]))
        idle = set(model.idle_labels)
        streak_label: str | None = None
        streak = 0
        rearmed = True
        last_detection: dict[str, float] = {}
        next_tick = time.monotonic()
        while not self.stop_event.is_set():
            next_tick += hop
            delay = next_tick - time.monotonic()
            if delay < -hop:
                next_tick = time.monotonic()
                delay = 0
            if self.stop_event.wait(max(0.0, delay)):
                break
            session = self.sensors.sessions.get(self.sensor_id)
            if session is None:
                break
            t, h, v = session.buffer.window(model.window_s + 0.3)
            if len(t) < 3:
                self.counters["skipped_no_data"] += 1
                continue
            now_ns = time.perf_counter_ns()
            if (now_ns - int(h[-1])) / 1e9 > STALE_DATA_S:
                self.counters["skipped_stale"] += 1
                if self.counters["skipped_stale"] % 10 == 1:
                    self.message = "Waiting for fresh sensor data"
                    self.publish_state()
                continue
            requirement = model.rate_requirements
            measured = session.last_rates.get("device_hz")
            if requirement.get("accept_min_hz") and measured and not (requirement["accept_min_hz"] <= measured <= requirement["accept_max_hz"]):
                self.counters["skipped_rate_incompatible"] += 1
                self.message = f"Sensor rate {measured:.1f} Hz is outside the model's accepted range"
                continue
            start_us = float(t[-1]) - model.window_s * 1e6
            compute_start = time.perf_counter_ns()
            try:
                features = model.feature.window_features(t, v, start_us, model.window_s, self.src_dir)
            except WindowRejected as exc:
                self.counters[f"skipped_{exc.reason}"] += 1
                continue
            proba = model.estimator.predict_proba(features.reshape(1, -1))[0]
            smoothing.append(proba)
            smoothed = np.mean(np.vstack(smoothing), axis=0)
            best = int(np.argmax(smoothed))
            label = model.labels[best]
            score = float(smoothed[best])
            done_ns = time.perf_counter_ns()
            self.counters["windows"] += 1
            self.message = "Running"
            now = time.monotonic()
            detection = None
            suppressed = None
            if score >= threshold:
                if label in idle:
                    rearmed = True
                    streak, streak_label = 0, None
                else:
                    streak = streak + 1 if label == streak_label else 1
                    streak_label = label
                    cooldown_ok = now - last_detection.get(label, -1e9) >= cooldown
                    if streak >= debounce:
                        if require_rearm and not rearmed:
                            suppressed = "waiting_for_idle"
                        elif not cooldown_ok:
                            suppressed = "cooldown"
                        else:
                            detection = {"detection_id": uuid.uuid4().hex[:12], "label": label, "score": score, "at": time.time()}
                            last_detection[label] = now
                            streak, streak_label = 0, None
                            if require_rearm:
                                rearmed = False
            else:
                streak, streak_label = 0, None
            if suppressed:
                self.counters[f"suppressed_{suppressed}"] += 1
            prediction = {
                "at": time.time(),
                "label": label,
                "score": score,
                "raw_score": float(proba[best]),
                "above_threshold": score >= threshold,
                "probabilities": {lab: float(p) for lab, p in zip(model.labels, smoothed)},
                "latency_ms": (done_ns - int(h[-1])) / 1e6,
                "processing_ms": (done_ns - compute_start) / 1e6,
                "window_s": model.window_s,
                "hop_s": hop,
                "device_t_us": float(t[-1]),
                "rearmed": rearmed,
                "streak": streak,
                "suppressed": suppressed,
                "sensor_id": self.sensor_id,
                "simulated": session.simulated,
            }
            self.last_prediction = prediction
            self.history.append({k: prediction[k] for k in ("at", "label", "score", "latency_ms")})
            self.hub.publish("predictions", "prediction", prediction)
            if self.counters["windows"] % 10 == 0:
                self.publish_state()
            if detection:
                self._handle_detection(detection, session.simulated)

    def _handle_detection(self, detection: dict, simulated: bool) -> None:
        action = self.mappings.action_for(detection["label"])
        if action is None:
            outcome = "unmapped"
            description = None
        else:
            try:
                description = describe_action(parse_gesture_action(action))
            except Exception:
                description = "invalid action"
            outcome = self.control.submit(detection["label"], action, detection["detection_id"], source="gesture", sensor_id=self.sensor_id)
        detection.update({"mapped_action": description, "outcome": outcome, "simulated": simulated, "sensor_id": self.sensor_id})
        self.detections.append(detection)
        self.counters["detections"] += 1
        self.hub.publish("detections", "detection", detection)
        tail = f" → {description} ({outcome})" if description else " (no mapping)"
        self.activity.info("recognition", f"Detected {detection['label']} ({detection['score']:.2f}){tail}", label=detection["label"], outcome=outcome)
