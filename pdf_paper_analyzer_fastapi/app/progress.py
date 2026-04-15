"""In-memory progress tracker so the frontend can poll step-by-step status."""

from __future__ import annotations

from threading import Lock
from typing import Dict, List, Optional


class ProgressTracker:
    """Store progress steps keyed by request ID."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._store: Dict[str, List[Dict[str, Optional[str]]]] = {}

    def start(self, request_id: str) -> None:
        with self._lock:
            self._store[request_id] = []

    def update(self, request_id: str, name: str, status: str, detail: Optional[str] = None) -> None:
        if not request_id:
            return
        with self._lock:
            steps = self._store.setdefault(request_id, [])
            for step in steps:
                if step.get("name") == name:
                    step["status"] = status
                    if detail is not None:
                        step["detail"] = detail
                    return
            steps.append({"name": name, "status": status, "detail": detail})

    def get(self, request_id: str) -> List[Dict[str, Optional[str]]]:
        with self._lock:
            steps = self._store.get(request_id, [])
            return [step.copy() for step in steps]

    def clear(self, request_id: str) -> None:
        with self._lock:
            self._store.pop(request_id, None)


progress_tracker = ProgressTracker()

__all__ = ["progress_tracker", "ProgressTracker"]
