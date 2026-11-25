"""Tests for the constrained action executor."""

from __future__ import annotations

import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest

from macos_resource_sentinel.actions import (
    ActionError,
    ProcessIdentity,
    confirm_action,
    is_protected,
    list_actions,
    request_termination,
)
from macos_resource_sentinel.storage import JsonlStore


@pytest.fixture
def store(tmp_path: Path) -> JsonlStore:
    jsonl_store = JsonlStore(tmp_path / "state")
    jsonl_store.prepare()
    return jsonl_store


@pytest.fixture
def config() -> dict:
    return {
        "actions": {
            "enabled": True,
            "require_confirmation": True,
            "confirmation_ttl_seconds": 120,
            "max_termination_requests_per_hour": 3,
            "allowed_actions": ["incident.inspect", "process.terminate", "process.verify-exit"],
            "protected_names": ["kernel_task", "launchd"],
            "protected_paths": ["/System/", "/sbin/"],
        }
    }


def _identity(
    pid: int = 4242,
    name: str = "node",
    executable: str = "/usr/local/bin/node",
    create_time: float = 1_700_000_000.0,
) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        name=name,
        username="egor",
        executable=executable,
        create_time=create_time,
    )


def test_request_requires_actions_enabled(store: JsonlStore, config: dict) -> None:
    config["actions"]["enabled"] = False
    with pytest.raises(ActionError, match="disabled"):
        request_termination(store, config, incident_id="INC-1", pid=4242)


def test_request_rejects_protected_name(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process",
        lambda pid: _identity(name="kernel_task", executable="/kernel"),
    )
    with pytest.raises(ActionError, match="protected"):
        request_termination(store, config, incident_id="INC-1", pid=4242)


def test_request_rejects_protected_path(store: JsonlStore, config: dict) -> None:
    identity = _identity(executable="/System/Library/CoreServices/dock")
    assert is_protected(identity, config["actions"]) is not None


def test_request_allows_regular_process(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process",
        lambda pid: _identity(pid=pid),
    )

    record = request_termination(store, config, incident_id="INC-1", pid=4242)

    assert record.state == "pending"
    assert record.action_id.startswith("ACT-")
    assert record.process is not None and record.process.name == "node"
    assert record.expires_at is not None


def test_request_enforces_hourly_rate_limit(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process",
        lambda pid: _identity(pid=pid),
    )
    config["actions"]["max_termination_requests_per_hour"] = 2
    for pid in (100, 101):
        request_termination(store, config, incident_id="INC-1", pid=pid)

    with pytest.raises(ActionError, match="rate limit"):
        request_termination(store, config, incident_id="INC-1", pid=102)


def test_confirm_executes_sigterm(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _identity()
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process", lambda pid: identity
    )
    sent_signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "macos_resource_sentinel.actions._wait_for_exit", lambda *args, **kwargs: True
    )

    def fake_killer(pid: int, signum: int) -> None:
        sent_signals.append((pid, signum))

    record = request_termination(store, config, incident_id="INC-1", pid=4242)
    confirmed = confirm_action(
        store, config, record.action_id, killer=fake_killer, exit_grace_seconds=0
    )

    assert sent_signals == [(4242, signal.SIGTERM)]
    assert confirmed.state == "executed"
    assert confirmed.confirmed_at is not None
    events = [entry["event"] for entry in confirmed.audit]
    assert events == ["requested", "executed"]


def test_confirm_rejects_pid_reuse(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _identity(create_time=1_700_000_000.0)
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process", lambda pid: original
    )
    record = request_termination(store, config, incident_id="INC-1", pid=4242)

    reused = _identity(create_time=1_800_000_000.0)
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process", lambda pid: reused
    )

    with pytest.raises(ActionError, match="identity changed"):
        confirm_action(store, config, record.action_id, exit_grace_seconds=0)

    latest = list_actions(store)[0]
    assert latest.state == "failed"
    assert any(entry["event"] == "failed" for entry in latest.audit)


def test_confirm_rejects_expired_request(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process",
        lambda pid: _identity(pid=pid),
    )
    now = datetime.now(UTC)
    record = request_termination(store, config, incident_id="INC-1", pid=4242, now=now)

    with pytest.raises(ActionError, match="expired"):
        confirm_action(
            store,
            config,
            record.action_id,
            now=now + timedelta(seconds=500),
            exit_grace_seconds=0,
        )

    assert list_actions(store)[0].state == "expired"


def test_confirm_rejects_unknown_action(store: JsonlStore, config: dict) -> None:
    with pytest.raises(ActionError, match="not found"):
        confirm_action(store, config, "ACT-missing", exit_grace_seconds=0)


def test_list_actions_collapses_states(
    store: JsonlStore, config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _identity()
    monkeypatch.setattr(
        "macos_resource_sentinel.actions.identify_process", lambda pid: identity
    )
    monkeypatch.setattr(
        "macos_resource_sentinel.actions._wait_for_exit", lambda *args, **kwargs: True
    )
    record = request_termination(store, config, incident_id="INC-1", pid=4242)
    confirm_action(store, config, record.action_id, killer=lambda pid, sig: None, exit_grace_seconds=0)

    records = list_actions(store)

    assert len(records) == 1
    assert records[0].state == "executed"


def test_identify_process_raises_for_missing_pid() -> None:
    with pytest.raises(ActionError, match="does not exist"):
        _unused = psutil  # keep import referenced
        from macos_resource_sentinel.actions import identify_process

        identify_process(999_999)
