from __future__ import annotations

from datetime import datetime
from threading import Lock
from uuid import uuid4


_lock = Lock()
_active_job: dict | None = None
_last_finished_job: dict | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_import_job(kind: str, label: str, file_name: str, imported_by: str | None) -> dict:
    """Register one active import job for UI recovery after browser reload."""
    global _active_job

    with _lock:
        if _active_job is not None:
            raise RuntimeError(
                f"Đang import {_active_job['label']}: {_active_job['file_name']}. "
                "Vui lòng chờ import hiện tại hoàn tất."
            )

        _active_job = {
            "id": uuid4().hex,
            "kind": kind,
            "label": label,
            "file_name": file_name,
            "started_at": _now_iso(),
            "imported_by": imported_by,
            "status": "running",
        }
        return dict(_active_job)


def finish_import_job(job_id: str, success: bool, error: str | None = None) -> None:
    """Mark the active job as finished if it is still the same job."""
    global _active_job, _last_finished_job

    with _lock:
        if _active_job is None or _active_job.get("id") != job_id:
            return

        _last_finished_job = {
            **_active_job,
            "status": "success" if success else "failed",
            "success": success,
            "error": error,
            "finished_at": _now_iso(),
        }
        _active_job = None


def get_import_job_status() -> dict:
    with _lock:
        return {
            "active": _active_job is not None,
            "job": dict(_active_job) if _active_job else None,
            "last_finished": dict(_last_finished_job) if _last_finished_job else None,
        }
