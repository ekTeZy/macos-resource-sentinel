"""Constrained, confirmable actions with a full local audit trail.

The executor is deliberately narrow:

- allowlisted action types only (`process.terminate` in the MVP);
- no arbitrary shell, no `sudo`;
- protected names and executable paths can never be terminated;
- the recorded PID is revalidated against name and start time before
  `SIGTERM`, which blocks PID-reuse mistakes;
- every step is appended to the local audit log.
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import uuid4

import psutil

from .storage import JsonlStore


class ActionError(RuntimeError):
    """Raised when an action request or confirmation is rejected."""


class TerminationKiller(Protocol):
    def __call__(self, pid: int, signum: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    name: str | None
    username: str | None
    executable: str | None
    create_time: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "username": self.username,
            "executable": self.executable,
            "create_time": self.create_time,
        }


@dataclass(frozen=True, slots=True)
class ActionRecord:
    action_id: str
    incident_id: str
    action: str
    state: str  # pending, executed, rejected, expired, failed
    requested_at: datetime
    expires_at: datetime | None
    confirmed_at: datetime | None
    process: ProcessIdentity | None
    reason: str | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "action_id": self.action_id,
            "incident_id": self.incident_id,
            "action": self.action,
            "state": self.state,
            "requested_at": _iso(self.requested_at),
            "expires_at": _iso(self.expires_at) if self.expires_at else None,
            "confirmed_at": _iso(self.confirmed_at) if self.confirmed_at else None,
            "process": self.process.to_dict() if self.process else None,
            "reason": self.reason,
            "audit": self.audit,
        }


def identify_process(pid: int) -> ProcessIdentity:
    """Read the identity of a live process or raise ActionError."""
    try:
        process = psutil.Process(pid)
        return ProcessIdentity(
            pid=pid,
            name=process.name(),
            username=process.username(),
            executable=process.exe(),
            create_time=process.create_time(),
        )
    except psutil.NoSuchProcess as exc:
        raise ActionError(f"process {pid} does not exist") from exc
    except psutil.AccessDenied as exc:
        raise ActionError(f"cannot inspect process {pid}: access denied") from exc


def is_protected(identity: ProcessIdentity, policy: dict[str, Any]) -> str | None:
    """Return the protection reason, or None when termination is allowed."""
    if identity.name and identity.name in set(policy.get("protected_names", [])):
        return f"process name '{identity.name}' is protected"
    executable = identity.executable or ""
    for prefix in policy.get("protected_paths", []):
        if executable.startswith(prefix):
            return f"executable path '{executable}' is protected by '{prefix}'"
    return None


def request_termination(
    store: JsonlStore,
    config: dict[str, Any],
    *,
    incident_id: str,
    pid: int,
    now: datetime | None = None,
) -> ActionRecord:
    """Stage a `SIGTERM` request that must be confirmed separately."""
    now = now or datetime.now(UTC)
    policy = config["actions"]
    if not policy["enabled"]:
        raise ActionError("actions are disabled in the configuration")
    if "process.terminate" not in policy["allowed_actions"]:
        raise ActionError("process.terminate is not in actions.allowed_actions")

    _check_rate_limit(store, policy, now)

    identity = identify_process(pid)
    protection = is_protected(identity, policy)
    if protection:
        raise ActionError(protection)

    ttl = int(policy["confirmation_ttl_seconds"])
    record = ActionRecord(
        action_id=_new_action_id(now),
        incident_id=incident_id,
        action="process.terminate",
        state="pending",
        requested_at=now,
        expires_at=now + timedelta(seconds=ttl),
        confirmed_at=None,
        process=identity,
        audit=[
            {
                "at": _iso(now),
                "event": "requested",
                "detail": f"SIGTERM requested for pid {pid} ({identity.name})",
            }
        ],
    )
    _append(store, record)
    return record


def confirm_action(
    store: JsonlStore,
    config: dict[str, Any],
    action_id: str,
    *,
    now: datetime | None = None,
    killer: TerminationKiller | None = None,
    exit_grace_seconds: float = 10.0,
) -> ActionRecord:
    """Execute a pending request after revalidating the process identity."""
    now = now or datetime.now(UTC)
    killer = killer or _default_killer
    policy = config["actions"]
    if not policy["enabled"]:
        raise ActionError("actions are disabled in the configuration")
    if not policy["require_confirmation"]:
        raise ActionError("confirmation is required by the security model")

    record = _find_latest(store, action_id)
    if record is None:
        raise ActionError(f"action not found: {action_id}")
    if record.state != "pending":
        raise ActionError(f"action {action_id} is {record.state}, not pending")
    if record.expires_at is not None and now > record.expires_at:
        expired = _with_audit(record, now, "expired", "confirmation window elapsed")
        _append(store, _replace_latest_state(expired))
        raise ActionError(f"action {action_id} expired; request it again")

    identity = record.process
    if identity is None:
        raise ActionError("pending action has no recorded process identity")

    try:
        current = identify_process(identity.pid)
    except ActionError as exc:
        failed = _with_audit(record, now, "failed", str(exc))
        _append(store, _replace_latest_state(failed))
        raise

    if current.create_time != identity.create_time or current.executable != identity.executable:
        failed = _with_audit(
            record,
            now,
            "failed",
            "process identity changed between request and confirmation (possible PID reuse)",
        )
        _append(store, _replace_latest_state(failed))
        raise ActionError(failed.audit[-1]["detail"])

    killer(identity.pid, signal.SIGTERM)

    if _wait_for_exit(identity.pid, identity.create_time, exit_grace_seconds):
        confirmed = _with_audit(record, now, "executed", f"SIGTERM sent to pid {identity.pid}")
        _append(store, _replace_latest_state(confirmed))
        return confirmed

    failed = _with_audit(record, now, "failed", f"pid {identity.pid} still alive after SIGTERM")
    _append(store, _replace_latest_state(failed))
    raise ActionError(failed.audit[-1]["detail"])


def list_actions(store: JsonlStore, *, limit: int = 20) -> list[ActionRecord]:
    """Latest record per action, newest first."""
    latest: dict[str, ActionRecord] = {}
    for record in _read_all(store):
        latest[record.action_id] = record
    records = sorted(latest.values(), key=lambda item: item.requested_at, reverse=True)
    return records[:limit] if limit > 0 else records


def _append(store: JsonlStore, record: ActionRecord) -> None:
    store.append_action(record.to_dict())


def _find_latest(store: JsonlStore, action_id: str) -> ActionRecord | None:
    for record in reversed(_read_all(store)):
        if record.action_id == action_id:
            return record
    return None


def _read_all(store: JsonlStore) -> list[ActionRecord]:
    from .incident_report import read_jsonl

    records: list[ActionRecord] = []
    for raw in read_jsonl(store.actions_path):
        process_raw = raw.get("process")
        records.append(
            ActionRecord(
                action_id=str(raw.get("action_id", "")),
                incident_id=str(raw.get("incident_id", "")),
                action=str(raw.get("action", "")),
                state=str(raw.get("state", "unknown")),
                requested_at=_parse_time(raw.get("requested_at")) or datetime.now(UTC),
                expires_at=_parse_time(raw.get("expires_at")),
                confirmed_at=_parse_time(raw.get("confirmed_at")),
                process=ProcessIdentity(**process_raw) if isinstance(process_raw, dict) else None,
                reason=raw.get("reason"),
                audit=raw.get("audit") if isinstance(raw.get("audit"), list) else [],
            )
        )
    return records


def _check_rate_limit(store: JsonlStore, policy: dict[str, Any], now: datetime) -> None:
    max_requests = int(policy["max_termination_requests_per_hour"])
    cutoff = now - timedelta(hours=1)
    recent = [
        record
        for record in _read_all(store)
        if record.action == "process.terminate" and record.requested_at >= cutoff
    ]
    if len(recent) >= max_requests:
        raise ActionError(
            f"termination request rate limit reached ({max_requests} per hour)"
        )


def _with_audit(record: ActionRecord, now: datetime, state: str, detail: str) -> ActionRecord:
    return ActionRecord(
        action_id=record.action_id,
        incident_id=record.incident_id,
        action=record.action,
        state=state,
        requested_at=record.requested_at,
        expires_at=record.expires_at,
        confirmed_at=now if state == "executed" else record.confirmed_at,
        process=record.process,
        reason=detail if state in {"rejected", "expired", "failed"} else record.reason,
        audit=[*record.audit, {"at": _iso(now), "event": state, "detail": detail}],
    )


def _replace_latest_state(record: ActionRecord) -> ActionRecord:
    """Appended records supersede earlier ones with the same action_id."""
    return record


def _wait_for_exit(pid: int, create_time: float | None, grace_seconds: float) -> bool:
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            current = psutil.Process(pid)
            if create_time is not None and current.create_time() != create_time:
                return True  # PID reused: the original process is gone
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.2)
    return False


def _default_killer(pid: int, signum: int) -> None:
    os.kill(pid, signum)


def _new_action_id(now: datetime) -> str:
    return f"ACT-{now:%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


__all__ = [
    "ActionError",
    "ActionRecord",
    "ProcessIdentity",
    "confirm_action",
    "identify_process",
    "is_protected",
    "list_actions",
    "request_termination",
]
