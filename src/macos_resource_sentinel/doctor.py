"""Local environment and configuration checks."""

from __future__ import annotations

import os
import platform
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

from . import __version__
from .config import ConfigError, LoadedConfig, incident_spool_dir, load_config, state_dir


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str  # ok, warning, error
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok: bool
    version: str
    checks: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "checks": [check.to_dict() for check in self.checks],
        }


def run_doctor(config_path: str | None = None, *, create_state_dirs: bool = False) -> DoctorReport:
    """Run read-only local checks.

    State directories are created only when ``create_state_dirs`` is true. This
    lets CI and tests run doctor without writing to a user's home directory.
    """

    checks: list[CheckResult] = [
        _check_python(),
        _check_platform(),
        _check_psutil(),
    ]

    loaded: LoadedConfig | None = None
    try:
        loaded = load_config(config_path)
        status = "warning" if loaded.used_defaults else "ok"
        message = (
            "configuration file not found; built-in defaults are usable"
            if loaded.used_defaults
            else "configuration loaded"
        )
        checks.append(
            CheckResult(
                name="config.load",
                status=status,
                message=message,
                details={"path": str(loaded.path) if loaded.path else None},
            )
        )
        checks.extend(_check_config_details(loaded))
    except ConfigError as exc:
        checks.append(CheckResult(name="config.load", status="error", message=str(exc)))

    if loaded is not None:
        checks.extend(_check_state(loaded, create_state_dirs=create_state_dirs))
        checks.extend(_check_notifications(loaded))
        checks.append(_check_process_access())

    ok = all(check.status != "error" for check in checks)
    return DoctorReport(ok=ok, version=__version__, checks=checks)


def _check_python() -> CheckResult:
    version = sys.version_info
    if version >= (3, 11):
        return CheckResult(
            name="python.version",
            status="ok",
            message=f"Python {version.major}.{version.minor}.{version.micro}",
        )
    return CheckResult(
        name="python.version",
        status="error",
        message="Python 3.11 or newer is required",
        details={"current": platform.python_version()},
    )


def _check_platform() -> CheckResult:
    if platform.system() == "Darwin":
        return CheckResult(
            name="platform.macos",
            status="ok",
            message=f"macOS {platform.mac_ver()[0]}",
        )
    return CheckResult(
        name="platform.macos",
        status="warning",
        message="this tool is designed for macOS; some checks may be unavailable",
        details={"system": platform.system()},
    )


def _check_psutil() -> CheckResult:
    return CheckResult(
        name="dependency.psutil",
        status="ok",
        message=f"psutil {psutil.__version__}",
    )


def _check_config_details(config: LoadedConfig) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if config.path is None:
        return checks

    try:
        mode = stat.S_IMODE(config.path.stat().st_mode)
    except OSError as exc:
        checks.append(CheckResult(name="config.permissions", status="warning", message=str(exc)))
        return checks

    if mode & 0o077:
        checks.append(
            CheckResult(
                name="config.permissions",
                status="warning",
                message=f"configuration is readable by group or others: mode {mode:o}",
                details={"recommended": "chmod 600"},
            )
        )
    else:
        checks.append(
            CheckResult(
                name="config.permissions",
                status="ok",
                message=f"configuration permissions are private: mode {mode:o}",
            )
        )
    return checks


def _check_state(config: LoadedConfig, *, create_state_dirs: bool) -> list[CheckResult]:
    checks: list[CheckResult] = []
    directories = [
        ("storage.state_dir", state_dir(config.data)),
        ("assistant.incident_spool", incident_spool_dir(config.data)),
    ]
    for name, directory in directories:
        try:
            if create_state_dirs:
                directory.mkdir(parents=True, exist_ok=True)
                os.chmod(directory, 0o700)
            exists = directory.is_dir()
            writable = os.access(directory, os.W_OK) if exists else os.access(directory.parent, os.W_OK)
            status = "ok" if exists and writable else "warning"
            message = "directory is available" if exists and writable else "directory does not exist yet"
            checks.append(
                CheckResult(
                    name=name,
                    status=status,
                    message=message,
                    details={"path": str(directory)},
                )
            )
        except OSError as exc:
            checks.append(
                CheckResult(
                    name=name,
                    status="error",
                    message=f"cannot prepare directory: {exc}",
                    details={"path": str(directory)},
                )
            )
    return checks


def _check_notifications(config: LoadedConfig) -> list[CheckResult]:
    notifications = config.data["notifications"]
    checks: list[CheckResult] = []
    if not notifications["enabled"]:
        checks.append(CheckResult(name="notifications.enabled", status="warning", message="notifications are disabled"))
        return checks

    channels = set(notifications["channels"])
    if "macos" in channels and platform.system() != "Darwin":
        checks.append(
            CheckResult(
                name="notifications.macos",
                status="warning",
                message="native macOS notifications are unavailable on this platform",
            )
        )

    telegram = notifications["telegram"]
    if telegram["enabled"] or "telegram" in channels:
        missing = [
            name
            for name in ("bot_token_ref", "chat_id_ref")
            if _resolve_secret_ref(telegram[name]) is None
        ]
        if missing:
            checks.append(
                CheckResult(
                    name="notifications.telegram",
                    status="error",
                    message="Telegram is enabled but secret references cannot be resolved",
                    details={"missing": missing},
                )
            )
        else:
            checks.append(
                CheckResult(
                    name="notifications.telegram",
                    status="ok",
                    message="Telegram secret references are configured",
                )
            )
    return checks


def _check_process_access() -> CheckResult:
    try:
        iterator = psutil.process_iter(attrs=["pid", "name"])
        next(iterator, None)
    except (psutil.Error, OSError) as exc:
        return CheckResult(
            name="process.access",
            status="error",
            message=f"cannot inspect processes: {exc}",
        )
    return CheckResult(
        name="process.access",
        status="ok",
        message="process information is readable",
    )


def _resolve_secret_ref(reference: str) -> str | None:
    if reference.startswith("env:"):
        return os.environ.get(reference.removeprefix("env:"))
    if reference.startswith("keychain:"):
        # Keychain resolution is intentionally deferred to the notifier.
        return "configured"
    return None
