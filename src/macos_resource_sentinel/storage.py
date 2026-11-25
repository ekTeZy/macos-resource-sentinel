"""Local JSONL event storage and monitor state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    """Raised when local monitor state cannot be read or written."""


class JsonlStore:
    """Append-only local storage for monitor events and incidents."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.events_path = state_dir / "events.jsonl"
        self.incidents_path = state_dir / "incidents.jsonl"
        self.actions_path = state_dir / "actions.jsonl"
        self.state_path = state_dir / "state.json"
        self.log_path = state_dir / "monitor.log"

    def prepare(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.state_dir, 0o700)
        except OSError as exc:
            raise StorageError(f"cannot prepare state directory {self.state_dir}: {exc}") from exc

    def append_event(self, record: dict[str, Any]) -> None:
        self._append_jsonl(self.events_path, record)

    def append_incident(self, record: dict[str, Any]) -> None:
        self._append_jsonl(self.incidents_path, record)

    def append_action(self, record: dict[str, Any]) -> None:
        self._append_jsonl(self.actions_path, record)

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return default_monitor_state()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read monitor state {self.state_path}: {exc}") from exc
        if data.get("schema_version") != 1:
            raise StorageError(f"unsupported monitor state schema in {self.state_path}")
        data.setdefault("incident_sequence", 0)
        data.setdefault("open_incidents", {})
        data.setdefault("cooldowns", {})
        data.setdefault("suppressed", {})
        return data

    def save_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.state_path)
        except OSError as exc:
            raise StorageError(f"cannot write monitor state {self.state_path}: {exc}") from exc

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        self.prepare()
        try:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.chmod(path, 0o600)
        except OSError as exc:
            raise StorageError(f"cannot append {path}: {exc}") from exc


def default_monitor_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "incident_sequence": 0,
        "open_incidents": {},
        "cooldowns": {},
        "suppressed": {},
    }
