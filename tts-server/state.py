"""StateStore — persists last-seen event IDs to JSON for deduplication."""

import json
import os
from pathlib import Path


class StateStore:
    """Persists seen-event state to a JSON file keyed by event_type."""

    def __init__(self, path: str):
        self._path = Path(path) / "state.json"
        self._state: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        """Load state from disk, creating the file if it doesn't exist."""
        if self._path.exists():
            raw = json.loads(self._path.read_text())
            # Rebuild set objects from lists for O(1) lookup
            self._state = {k: set(v) for k, v in raw.items()}
        else:
            self._state = {}
            self._persist()

    def _persist(self) -> None:
        """Write state to disk atomically."""
        raw = {k: list(v) for k, v in self._state.items()}
        self._path.write_text(json.dumps(raw, indent=2))

    def seen(self, event_type: str, event_id: str) -> bool:
        """Return True if this (event_type, event_id) pair has been marked."""
        return event_id in self._state.get(event_type, set())

    def mark(self, event_type: str, event_id: str) -> None:
        """Record that (event_type, event_id) has been seen."""
        if event_type not in self._state:
            self._state[event_type] = set()
        self._state[event_type].add(event_id)
        self._persist()