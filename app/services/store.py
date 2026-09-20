"""In-memory async request store.

Replaces the previous Firestore-backed queue. The identity service is a
stateless demo that runs with --max-instances=1 on Cloud Run, so a process-local
dict is sufficient: the async flow (POST /verify-id enqueues, POST /cron/verify-id
processes, GET /get/{id} polls) all hit the same single instance.

Nothing here is durable — requests live only for the lifetime of the instance,
which is exactly what a demo needs (no biometric data is persisted anywhere).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# Process-local store: request_id -> request dict.
_requests: dict[str, dict[str, Any]] = {}
# Guards mutations to _requests. The cron and the HTTP handlers can run
# concurrently within the process; a simple lock keeps updates atomic.
_lock = threading.Lock()
# Serializes cron processing so two overlapping /cron/verify-id calls don't
# process the same pending request twice (replaces the old Firestore lock).
cron_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_request(input_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new pending request and return the stored document."""
    request_id = uuid.uuid4().hex
    doc = {
        "id": request_id,
        "status": "pending",
        "type": "verify-id",
        "message": "Request created successfully",
        "success": None,
        "created_at": _now(),
        "updated_at": _now(),
        "data": {
            "input": input_data,
            "output": None,
        },
    }
    with _lock:
        _requests[request_id] = doc
    return doc


def get_request(request_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        doc = _requests.get(request_id)
        return doc.copy() if doc else None


def list_pending() -> list[dict[str, Any]]:
    with _lock:
        return [d.copy() for d in _requests.values() if d.get("status") == "pending"]


def update_request(request_id: str, updates: dict[str, Any]) -> None:
    """Shallow-merge top-level keys; supports dotted keys like 'data.output.x'."""
    with _lock:
        doc = _requests.get(request_id)
        if doc is None:
            return
        for key, value in updates.items():
            if "." in key:
                parts = key.split(".")
                target = doc
                for p in parts[:-1]:
                    target = target.setdefault(p, {})
                target[parts[-1]] = value
            else:
                doc[key] = value
        doc["updated_at"] = _now()
