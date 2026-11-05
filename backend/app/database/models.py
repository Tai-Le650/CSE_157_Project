from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class LabelRow(Base):
    __tablename__ = "labels"
    label_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LabelChangeRow(Base):
    __tablename__ = "label_changes"
    change_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    action: Mapped[str] = mapped_column(String(24))
    label_id: Mapped[str] = mapped_column(String(48))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SensorRow(Base):
    __tablename__ = "sensors"
    sensor_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    hand: Mapped[str] = mapped_column(String(16), default="unassigned")
    last_port: Mapped[str | None] = mapped_column(String(128), nullable=True)
    baud: Mapped[int] = mapped_column(Integer, default=115200)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SessionRow(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    name: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="live")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecordingRow(Base):
    __tablename__ = "recordings"
    recording_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="trial")
    source: Mapped[str] = mapped_column(String(16), default="live")
    label_id: Mapped[str | None] = mapped_column(ForeignKey("labels.label_id"), nullable=True, index=True)
    sensor_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sensor_hand: Mapped[str] = mapped_column(String(16), default="unassigned")
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.session_id"), nullable=True, index=True)
    capture_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_t0_us: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    fs_median_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    fs_mean_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_base: Mapped[str] = mapped_column(String(16), default="data")
    file_path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    header_alias: Mapped[str] = mapped_column(String(16), default="t_us")
    time_unit: Mapped[str] = mapped_column(String(8), default="us")
    accel_unit: Mapped[str] = mapped_column(String(8), default="g")
    gyro_unit: Mapped[str] = mapped_column(String(8), default="deg/s")
    firmware_header: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_state: Mapped[str] = mapped_column(String(16), default="valid")
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    source_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SegmentRow(Base):
    __tablename__ = "segments"
    segment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.recording_id", ondelete="CASCADE"), index=True)
    label_id: Mapped[str] = mapped_column(ForeignKey("labels.label_id"))
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DerivativeRow(Base):
    __tablename__ = "derivatives"
    derivative_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.recording_id", ondelete="CASCADE"), index=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    recipe_name: Mapped[str] = mapped_column(String(48), default="custom")
    recipe: Mapped[dict] = mapped_column(JSON, default=dict)
    file_path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    fs_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    uniform: Mapped[bool] = mapped_column(Boolean, default=False)
    step_counts: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DatasetRow(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("workspace", "name"),)
    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DatasetMemberRow(Base):
    __tablename__ = "dataset_members"
    __table_args__ = (UniqueConstraint("dataset_id", "recording_id", "segment_id"),)
    member_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.dataset_id", ondelete="CASCADE"), index=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.recording_id", ondelete="CASCADE"))
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.segment_id", ondelete="CASCADE"), nullable=True)
    derivative_id: Mapped[str | None] = mapped_column(ForeignKey("derivatives.derivative_id", ondelete="SET NULL"), nullable=True)


class ModelRow(Base):
    __tablename__ = "models"
    model_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(16), default="app")
    file_path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    feature_version: Mapped[str] = mapped_column(String(48))
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrainingJobRow(Base):
    __tablename__ = "training_jobs"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    dataset_id: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(48), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    model_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProfileRow(Base):
    __tablename__ = "mapping_profiles"
    profile_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MappingRow(Base):
    __tablename__ = "mappings"
    __table_args__ = (UniqueConstraint("profile_id", "label_id"),)
    mapping_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("mapping_profiles.profile_id", ondelete="CASCADE"), index=True)
    label_id: Mapped[str] = mapped_column(String(48))
    action: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncMeasurementRow(Base):
    __tablename__ = "sync_measurements"
    measurement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(8), default="real")
    sensor_ids: Mapped[list] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String(48))
    events_used: Mapped[int] = mapped_column(Integer, default=0)
    mean_abs_error_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_error_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
