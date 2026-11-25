"""Deterministic notification formatting and delivery."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .incidents import IncidentTransition
from .storage import JsonlStore


RULE_LABELS = {
    "cpu.aggregate": "sustained CPU usage",
    "process.cpu": "process CPU usage",
    "load.average": "high load average",
    "memory.pressure": "memory pressure",
    "swap.growth": "swap growth",
    "disk.capacity": "low disk space",
}


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: str
    status: str  # sent, skipped, failed
    reason: str | None = None


class NotificationSender(Protocol):
    def send(self, message: NotificationMessage) -> None:
        """Deliver a message or raise NotificationDeliveryError."""


class NotificationDeliveryError(RuntimeError):
    """Raised when a notification channel cannot deliver a message."""


class NotificationManager:
    """Apply notification policy and deliver incident transitions."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        state_dir: Path,
        senders: dict[str, NotificationSender] | None = None,
    ) -> None:
        self.config = config
        self.notifications = config["notifications"]
        self.store = JsonlStore(state_dir)
        self.state_path = state_dir / "notification-state.json"
        self.senders = senders or {}

    def process(
        self,
        transitions: list[IncidentTransition],
        *,
        now: datetime | None = None,
    ) -> list[DeliveryResult]:
        now = now or datetime.now(UTC)
        results: list[DeliveryResult] = []
        for transition in transitions:
            results.extend(self._process_transition(transition, now))
        return results

    def _process_transition(self, transition: IncidentTransition, now: datetime) -> list[DeliveryResult]:
        if not self.notifications["enabled"]:
            return [self._suppressed(transition, "notifications_disabled", now)]

        if transition.event_type == "incident.resolved" and not self._send_recovery(transition.severity):
            return [self._suppressed(transition, "recovery_disabled", now)]

        if self._in_quiet_hours(now) and transition.severity != "critical":
            return [self._suppressed(transition, "quiet_hours", now)]

        if self._rate_limited(now):
            return [self._suppressed(transition, "hourly_rate_limit", now)]

        message = format_notification(transition)
        results: list[DeliveryResult] = []
        for channel in self.notifications["channels"]:
            sender = self._sender_for(channel)
            if sender is None:
                result = DeliveryResult(channel=channel, status="skipped", reason="channel_unavailable")
                results.append(result)
                continue
            try:
                sender.send(message)
            except NotificationDeliveryError as exc:
                result = DeliveryResult(channel=channel, status="failed", reason=str(exc))
            else:
                result = DeliveryResult(channel=channel, status="sent")
            results.append(result)
            self._append_delivery_event(transition, result, now)

        if any(result.status == "sent" for result in results):
            self._record_delivery(now)
        return results

    def _sender_for(self, channel: str) -> NotificationSender | None:
        if channel in self.senders:
            return self.senders[channel]
        if channel == "macos":
            if platform.system() != "Darwin":
                return None
            return MacOSNotificationSender()
        if channel == "telegram":
            telegram = self.notifications["telegram"]
            if not telegram["enabled"]:
                return None
            try:
                return TelegramNotificationSender(
                    bot_token=_resolve_secret_ref(telegram["bot_token_ref"]),
                    chat_id=_resolve_secret_ref(telegram["chat_id_ref"]),
                )
            except NotificationDeliveryError:
                return None
        return None

    def _send_recovery(self, severity: str) -> bool:
        if severity == "critical":
            return bool(self.notifications["send_critical_recovery"])
        return bool(self.notifications["send_warning_recovery"])

    def _rate_limited(self, now: datetime) -> bool:
        state = self._load_delivery_state()
        cutoff = now - timedelta(hours=1)
        deliveries = [
            timestamp
            for timestamp in state["deliveries"]
            if datetime.fromisoformat(timestamp) > cutoff
        ]
        state["deliveries"] = deliveries
        self._save_delivery_state(state)
        return len(deliveries) >= int(self.notifications["max_per_hour"])

    def _record_delivery(self, now: datetime) -> None:
        state = self._load_delivery_state()
        state["deliveries"].append(now.isoformat())
        self._save_delivery_state(state)

    def _load_delivery_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": 1, "deliveries": []}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "deliveries": []}
        if state.get("schema_version") != 1 or not isinstance(state.get("deliveries"), list):
            return {"schema_version": 1, "deliveries": []}
        return state

    def _save_delivery_state(self, state: dict[str, Any]) -> None:
        self.store.prepare()
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.state_path)

    def _in_quiet_hours(self, now: datetime) -> bool:
        if not self.notifications["quiet_hours_enabled"]:
            return False
        start = _parse_time(self.notifications["quiet_hours_start"])
        end = _parse_time(self.notifications["quiet_hours_end"])
        current = now.astimezone().time().replace(second=0, microsecond=0)
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def _suppressed(
        self,
        transition: IncidentTransition,
        reason: str,
        now: datetime,
    ) -> DeliveryResult:
        result = DeliveryResult(channel="policy", status="skipped", reason=reason)
        self._append_delivery_event(transition, result, now)
        return result

    def _append_delivery_event(
        self,
        transition: IncidentTransition,
        result: DeliveryResult,
        now: datetime,
    ) -> None:
        event_type = {
            "sent": "notification.sent",
            "failed": "notification.failed",
            "skipped": "notification.suppressed",
        }[result.status]
        self.store.append_event(
            {
                "schema_version": 1,
                "event_id": f"evt_{uuid4().hex}",
                "incident_id": transition.incident_id,
                "timestamp": now.isoformat(),
                "event_type": event_type,
                "severity": "warning" if result.status == "failed" else "info",
                "source": "notifier",
                "message": f"notification {result.status}: {result.channel}",
                "data": {
                    "channel": result.channel,
                    "reason": result.reason,
                    "transition": transition.event_type,
                },
            }
        )


class MacOSNotificationSender:
    """Send a native macOS notification through AppleScript."""

    def send(self, message: NotificationMessage) -> None:
        if platform.system() != "Darwin":
            raise NotificationDeliveryError("macOS notifications are unavailable on this platform")
        script = (
            f'display notification "{_apple_script_escape(message.body)}" '
            f'with title "{_apple_script_escape(message.title)}"'
        )
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotificationDeliveryError(f"cannot run osascript: {exc}") from exc
        if result.returncode != 0:
            raise NotificationDeliveryError("osascript returned an error")


class TelegramNotificationSender:
    """Send a plain-text Telegram message through the Bot API."""

    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: int = 10) -> None:
        if not bot_token or not chat_id:
            raise NotificationDeliveryError("Telegram credentials are not configured")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    def send(self, message: NotificationMessage) -> None:
        payload = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": f"{message.title}\n\n{message.body}",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if body.get("ok") is True:
                    return
                last_error = NotificationDeliveryError("Telegram API returned ok=false")
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
        raise NotificationDeliveryError("Telegram delivery failed after retries") from last_error


def format_notification(transition: IncidentTransition) -> NotificationMessage:
    label = RULE_LABELS.get(transition.rule, transition.rule or "resource incident")
    data = transition.data
    process = data.get("process") or {}
    duration = data.get("duration_seconds")

    if transition.event_type == "incident.resolved":
        title = f"macOS Resource Sentinel resolved: {label}"
        lines = [
            f"Severity: {transition.severity}",
            transition.message,
            f"Incident: {transition.incident_id}",
        ]
    else:
        title = f"macOS Resource Sentinel {transition.severity}: {label}"
        lines = [
            transition.message,
            f"Incident: {transition.incident_id}",
        ]
        if duration:
            lines.append(f"Confirmed for: {duration} seconds")
        if process.get("name"):
            lines.append(f"Process: {process['name']} (pid {process.get('pid')})")

    return NotificationMessage(title=title, body="\n".join(lines))


def _apple_script_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _parse_time(value: str) -> datetime_time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return datetime_time(hour=hour, minute=minute)


def _resolve_secret_ref(reference: str) -> str:
    if reference.startswith("env:"):
        value = os.environ.get(reference.removeprefix("env:"), "")
        if value:
            return value
        raise NotificationDeliveryError(f"environment variable is not set: {reference.removeprefix('env:')}")
    if reference.startswith("keychain:"):
        service = reference.removeprefix("keychain:")
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotificationDeliveryError("cannot read secret from Keychain") from exc
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        raise NotificationDeliveryError("Keychain secret was not found")
    raise NotificationDeliveryError("unsupported secret reference")
