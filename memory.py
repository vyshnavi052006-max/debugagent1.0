"""
memory.py
----------
Context Memory & Decision Making layer for DebugMate.

Stores, per session_id:
- preferred_language   : the language the user most often debugs in
- bug_history           : list of {language, bug_type, summary} for past fixes
- last_code             : the most recent code snippet submitted
- task_progress         : current step in an in-flight multi-step debug task
- constraints           : free-form notes the user has told the agent to remember

Persisted to a local JSON file so memory survives server restarts during a
session-based demo. Thread-safe with a simple lock since this is a small,
single-process beginner project.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

STORE_PATH = os.path.join(os.path.dirname(__file__), "memory_store.json")
_lock = threading.Lock()


def _empty_session() -> Dict[str, Any]:
    return {
        "preferred_language": None,
        "bug_history": [],
        "last_code": None,
        "task_progress": None,
        "constraints": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }


class MemoryStore:
    def __init__(self, path: str = STORE_PATH):
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            # Non-fatal: memory still works in-process for this run.
            pass

    def get_session(self, session_id: str) -> Dict[str, Any]:
        with _lock:
            if session_id not in self._data:
                self._data[session_id] = _empty_session()
                self._save()
            return dict(self._data[session_id])

    def update_session(self, session_id: str, **updates: Any) -> Dict[str, Any]:
        with _lock:
            session = self._data.setdefault(session_id, _empty_session())
            session.update(updates)
            session["updated_at"] = time.time()
            self._save()
            return dict(session)

    def add_bug_record(self, session_id: str, language: Optional[str], bug_type: str, summary: str) -> None:
        with _lock:
            session = self._data.setdefault(session_id, _empty_session())
            history: List[Dict[str, str]] = session.get("bug_history", [])
            history.append({"language": language or "unknown", "bug_type": bug_type, "summary": summary})
            # Keep the memory bounded for a beginner demo.
            session["bug_history"] = history[-15:]
            if language:
                session["preferred_language"] = language
            session["updated_at"] = time.time()
            self._save()

    def add_constraint(self, session_id: str, constraint: str) -> None:
        with _lock:
            session = self._data.setdefault(session_id, _empty_session())
            constraints: List[str] = session.get("constraints", [])
            if constraint not in constraints:
                constraints.append(constraint)
            session["constraints"] = constraints[-10:]
            session["updated_at"] = time.time()
            self._save()

    def common_bug_types(self, session_id: str) -> List[str]:
        session = self.get_session(session_id)
        counts: Dict[str, int] = {}
        for record in session.get("bug_history", []):
            counts[record["bug_type"]] = counts.get(record["bug_type"], 0) + 1
        return sorted(counts, key=counts.get, reverse=True)

    def snapshot(self, session_id: str) -> Dict[str, Any]:
        """A compact view suitable for the frontend's memory indicator."""
        session = self.get_session(session_id)
        return {
            "preferred_language": session.get("preferred_language"),
            "constraints": session.get("constraints", []),
            "recent_bugs": session.get("bug_history", [])[-5:],
            "most_common_bug_types": self.common_bug_types(session_id)[:3],
            "task_progress": session.get("task_progress"),
        }
