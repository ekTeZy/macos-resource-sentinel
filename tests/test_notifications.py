from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from macos_resource_sentinel.config import DEFAULT_CONFIG
from macos_resource_sentinel.incidents import IncidentTransition
from macos_resource_sentinel.notifications import (
    MacOSNotificationSender,
    NotificationManager,
    NotificationMessage,
    TelegramNotificationSender,
    format_notification,
)


class FakeSender:
    def __init__(self) -> None:
        self.messages = []

    def send(self, message: NotificationMessage) -> None:
        self.messages.append(message)


def transition(event_type: str = "incident.opened", severity: str = "warning") -> IncidentTransition:
    return IncidentTransition(
        event_type=event_type,
        incident_id="INC-20261125-0001",
        fingerprint="memory.pressure",
        severity=severity,
        message="memory pressure is warning",
        rule="memory.pressure",
        data={"duration_seconds": 120, "process": None},
    )


def notification_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["notifications"]["channels"] = ["macos"]
    return config


def test_opened_incident_sends_stable_message(tmp_path: Path) -> None:
    sender = FakeSender()
    manager = NotificationManager(notification_config(), state_dir=tmp_path, senders={"macos": sender})

    results = manager.process([transition()])

    assert results[0].status == "sent"
    assert len(sender.messages) == 1
    assert "memory pressure" in sender.messages[0].title
    assert "INC-20261125-0001" in sender.messages[0].body
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert events[0]["event_type"] == "notification.sent"


def test_warning_recovery_is_suppressed_by_default(tmp_path: Path) -> None:
    sender = FakeSender()
    manager = NotificationManager(notification_config(), state_dir=tmp_path, senders={"macos": sender})

    results = manager.process([transition(event_type="incident.resolved")])

    assert results[0].reason == "recovery_disabled"
    assert sender.messages == []


def test_hourly_rate_limit_suppresses_additional_notifications(tmp_path: Path) -> None:
    config = notification_config()
    config["notifications"]["max_per_hour"] = 1
    sender = FakeSender()
    manager = NotificationManager(config, state_dir=tmp_path, senders={"macos": sender})

    first = manager.process([transition()])
    second = manager.process([transition()])

    assert first[0].status == "sent"
    assert second[0].reason == "hourly_rate_limit"
    assert len(sender.messages) == 1


def test_notification_format_includes_process_for_process_incidents() -> None:
    item = IncidentTransition(
        event_type="incident.opened",
        incident_id="INC-20261125-0002",
        fingerprint="process.cpu:example:123:100",
        severity="warning",
        message="process example averaged 90% CPU",
        rule="process.cpu",
        data={
            "duration_seconds": 120,
            "process": {"pid": 123, "name": "example"},
        },
    )

    message = format_notification(item)

    assert "Process: example (pid 123)" in message.body


def test_macos_sender_uses_osascript_without_shell(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("macos_resource_sentinel.notifications.platform.system", lambda: "Darwin")
    monkeypatch.setattr("macos_resource_sentinel.notifications.subprocess.run", fake_run)

    MacOSNotificationSender().send(NotificationMessage(title='A "title"', body="line one\nline two"))

    assert calls[0][0] == "/usr/bin/osascript"
    assert calls[0][1] == "-e"
    assert "\\\"title\\\"" in calls[0][2]


def test_telegram_sender_retries_until_success(monkeypatch) -> None:
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise TimeoutError("temporary")
        return Response()

    monkeypatch.setattr("macos_resource_sentinel.notifications.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("macos_resource_sentinel.notifications.time.sleep", lambda seconds: None)

    TelegramNotificationSender(bot_token="token", chat_id="chat").send(
        NotificationMessage(title="Title", body="Body")
    )

    assert len(attempts) == 2
