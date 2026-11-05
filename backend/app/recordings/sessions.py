from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ..api.errors import not_found
from ..database.models import RecordingRow, SessionRow, iso
from .storage import new_id


class SessionService:
    def __init__(self, db: Any, workspace_provider):
        self.db = db
        self.workspace = workspace_provider

    def _dict(self, row: SessionRow, counts: dict) -> dict:
        return {
            "session_id": row.session_id,
            "name": row.name,
            "notes": row.notes,
            "source": row.source,
            "workspace": row.workspace,
            "recordings": counts.get(row.session_id, 0),
            "created_at": iso(row.created_at),
        }

    def list(self) -> list[dict]:
        workspace = self.workspace()
        with self.db() as db:
            rows = db.scalars(select(SessionRow).where(SessionRow.workspace == workspace).order_by(SessionRow.created_at.desc())).all()
            counts = dict(db.execute(select(RecordingRow.session_id, func.count()).where(RecordingRow.workspace == workspace).group_by(RecordingRow.session_id)).all())
            return [self._dict(r, counts) for r in rows]

    def create(self, name: str, notes: str = "", source: str = "live") -> dict:
        with self.db.begin() as db:
            row = SessionRow(session_id=new_id("ses", name or "session"), workspace=self.workspace(), name=name or "Session", notes=notes, source=source)
            db.add(row)
            db.flush()
            return self._dict(row, {})

    def get(self, session_id: str) -> dict:
        with self.db() as db:
            row = db.get(SessionRow, session_id)
            if row is None or row.workspace != self.workspace():
                raise not_found("Session", session_id)
            count = db.scalar(select(func.count()).select_from(RecordingRow).where(RecordingRow.session_id == session_id)) or 0
            return self._dict(row, {session_id: count})

    def ensure_exists(self, session_id: str | None) -> None:
        if session_id is None:
            return
        self.get(session_id)

    def update(self, session_id: str, name: str | None, notes: str | None) -> dict:
        with self.db.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is None or row.workspace != self.workspace():
                raise not_found("Session", session_id)
            if name is not None:
                row.name = name
            if notes is not None:
                row.notes = notes
        return self.get(session_id)

    def assign(self, session_id: str | None, recording_ids: list[str]) -> int:
        self.ensure_exists(session_id)
        with self.db.begin() as db:
            return (
                db.query(RecordingRow)
                .filter(RecordingRow.recording_id.in_(recording_ids), RecordingRow.workspace == self.workspace())
                .update({RecordingRow.session_id: session_id}, synchronize_session=False)
            )
