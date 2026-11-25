"""Configuration loading, merging, and validation."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APP_NAME = "macos-resource-sentinel"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / APP_NAME / "config.toml"
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / APP_NAME


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "sampling": {
        "interval_seconds": 5,
        "startup_grace_seconds": 120,
        "retain_samples_hours": 24,
    },
    "storage": {
        "state_dir": str(DEFAULT_STATE_DIR),
        "incident_retention_days": 180,
        "action_retention_days": 365,
    },
    "rules": {
        "cpu": {
            "enabled": True,
            "trigger_percent": 85,
            "recover_percent": 65,
            "min_duration_seconds": 180,
            "recovery_duration_seconds": 120,
            "cooldown_minutes": 30,
        },
        "process_cpu": {
            "enabled": True,
            "trigger_percent": 70,
            "recover_percent": 40,
            "min_duration_seconds": 120,
            "recovery_duration_seconds": 120,
            "cooldown_minutes": 30,
            "ignored_names": [],
        },
        "load_average": {
            "enabled": True,
            "trigger_multiplier": 1.5,
            "recovery_multiplier": 1.0,
            "min_duration_seconds": 600,
            "cooldown_minutes": 60,
        },
        "memory_pressure": {
            "enabled": True,
            "min_duration_seconds": 120,
            "recovery_duration_seconds": 180,
            "cooldown_minutes": 30,
        },
        "swap": {
            "enabled": True,
            "minimum_used_mib": 2048,
            "growth_mib": 512,
            "growth_window_seconds": 600,
            "cooldown_minutes": 60,
        },
        "disk": {
            "enabled": True,
            "warning_free_percent": 15,
            "critical_free_percent": 8,
            "warning_recovery_percent": 20,
            "critical_recovery_percent": 12,
            "paths": ["/"],
        },
    },
    "notifications": {
        "enabled": True,
        "channels": ["macos"],
        "max_per_hour": 4,
        "default_cooldown_minutes": 30,
        "send_warning_recovery": False,
        "send_critical_recovery": True,
        "quiet_hours_enabled": False,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "08:00",
        "telegram": {
            "enabled": False,
            "bot_token_ref": "env:MAC_SENTINEL_TELEGRAM_BOT_TOKEN",
            "chat_id_ref": "env:MAC_SENTINEL_TELEGRAM_CHAT_ID",
        },
    },
    "assistant": {
        "enabled": False,
        "bridge_mode": "cli",
        "incident_spool": str(DEFAULT_STATE_DIR / "spool"),
    },
    "actions": {
        "enabled": False,
        "require_confirmation": True,
        "confirmation_ttl_seconds": 120,
        "max_termination_requests_per_hour": 3,
        "allowed_actions": [
            "incident.inspect",
            "process.terminate",
            "process.verify-exit",
        ],
        "protected_names": [
            "kernel_task",
            "launchd",
            "WindowServer",
            "loginwindow",
            "SecurityAgent",
        ],
        "protected_paths": ["/System/", "/usr/libexec/", "/sbin/"],
    },
}


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """Validated configuration and information about where it came from."""

    data: dict[str, Any]
    path: Path | None
    used_defaults: bool
    warnings: list[str] = field(default_factory=list)


def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, base_value in base.items():
        override_value = override.get(key, base_value)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = _deep_merge(base_value, override_value)
        else:
            result[key] = override_value
    return result


def _copy_defaults() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(path: str | Path | None = None, *, require_file: bool = False) -> LoadedConfig:
    """Load TOML configuration and merge it with built-in defaults."""

    warnings: list[str] = []
    config_path = expand_path(str(path)) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        if require_file:
            raise ConfigError(f"configuration file does not exist: {config_path}")
        warnings.append(f"configuration file not found, using built-in defaults: {config_path}")
        data = _copy_defaults()
        validate_config(data)
        return LoadedConfig(data=data, path=None, used_defaults=True, warnings=warnings)

    if not config_path.is_file():
        raise ConfigError(f"configuration path is not a file: {config_path}")

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read configuration {config_path}: {exc}") from exc

    merged = _deep_merge(_copy_defaults(), raw)
    validate_config(merged)
    _validate_unknown_keys(raw)
    return LoadedConfig(data=merged, path=config_path, used_defaults=False, warnings=warnings)


def _validate_unknown_keys(raw: dict[str, Any], defaults: dict[str, Any] | None = None, prefix: str = "") -> None:
    defaults = DEFAULT_CONFIG if defaults is None else defaults
    for key, value in raw.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if key not in defaults:
            raise ConfigError(f"unknown configuration field: {dotted}")
        if isinstance(value, dict):
            expected = defaults[key]
            if not isinstance(expected, dict):
                raise ConfigError(f"configuration field must not be a table: {dotted}")
            _validate_unknown_keys(value, expected, dotted)


def validate_config(data: dict[str, Any]) -> None:
    """Validate the merged configuration."""

    if data.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")

    _validate_types(data, DEFAULT_CONFIG)

    sampling = data["sampling"]
    _require_range("sampling.interval_seconds", sampling["interval_seconds"], 1, 300)
    _require_range("sampling.startup_grace_seconds", sampling["startup_grace_seconds"], 0, 3600)
    _require_range("sampling.retain_samples_hours", sampling["retain_samples_hours"], 1, 24 * 30)

    storage = data["storage"]
    _require_range("storage.incident_retention_days", storage["incident_retention_days"], 1, 3650)
    _require_range("storage.action_retention_days", storage["action_retention_days"], 1, 3650)

    rules = data["rules"]
    _validate_cpu_rule("rules.cpu", rules["cpu"])
    _validate_cpu_rule("rules.process_cpu", rules["process_cpu"])

    load_average = rules["load_average"]
    _require_range("rules.load_average.trigger_multiplier", load_average["trigger_multiplier"], 0.1, 20)
    _require_range("rules.load_average.recovery_multiplier", load_average["recovery_multiplier"], 0.1, 20)
    if load_average["recovery_multiplier"] >= load_average["trigger_multiplier"]:
        raise ConfigError("rules.load_average.recovery_multiplier must be lower than trigger_multiplier")

    swap = rules["swap"]
    _require_range("rules.swap.minimum_used_mib", swap["minimum_used_mib"], 0, 1024 * 1024)
    _require_range("rules.swap.growth_mib", swap["growth_mib"], 1, 1024 * 1024)
    _require_range("rules.swap.growth_window_seconds", swap["growth_window_seconds"], 60, 24 * 3600)

    disk = rules["disk"]
    _require_range("rules.disk.warning_free_percent", disk["warning_free_percent"], 1, 99)
    _require_range("rules.disk.critical_free_percent", disk["critical_free_percent"], 1, 99)
    _require_range("rules.disk.warning_recovery_percent", disk["warning_recovery_percent"], 1, 100)
    _require_range("rules.disk.critical_recovery_percent", disk["critical_recovery_percent"], 1, 100)
    if disk["critical_free_percent"] >= disk["warning_free_percent"]:
        raise ConfigError("rules.disk.critical_free_percent must be lower than warning_free_percent")
    if not disk["paths"] or not all(isinstance(path, str) and path for path in disk["paths"]):
        raise ConfigError("rules.disk.paths must contain at least one non-empty path")

    notifications = data["notifications"]
    allowed_channels = {"macos", "telegram"}
    channels = notifications["channels"]
    if not channels:
        raise ConfigError("notifications.channels must not be empty")
    unknown_channels = set(channels) - allowed_channels
    if unknown_channels:
        raise ConfigError(f"unknown notification channels: {sorted(unknown_channels)}")
    _require_range("notifications.max_per_hour", notifications["max_per_hour"], 1, 60)
    _validate_time("notifications.quiet_hours_start", notifications["quiet_hours_start"])
    _validate_time("notifications.quiet_hours_end", notifications["quiet_hours_end"])

    telegram = notifications["telegram"]
    _validate_secret_ref("notifications.telegram.bot_token_ref", telegram["bot_token_ref"])
    _validate_secret_ref("notifications.telegram.chat_id_ref", telegram["chat_id_ref"])

    assistant = data["assistant"]
    if assistant["bridge_mode"] != "cli":
        raise ConfigError("assistant.bridge_mode currently supports only 'cli'")

    actions = data["actions"]
    _require_range("actions.confirmation_ttl_seconds", actions["confirmation_ttl_seconds"], 10, 3600)
    _require_range(
        "actions.max_termination_requests_per_hour",
        actions["max_termination_requests_per_hour"],
        1,
        60,
    )
    allowed_actions = {
        "incident.inspect",
        "process.terminate",
        "process.verify-exit",
    }
    unknown_actions = set(actions["allowed_actions"]) - allowed_actions
    if unknown_actions:
        raise ConfigError(f"unknown actions: {sorted(unknown_actions)}")
    if actions["enabled"] and not actions["require_confirmation"]:
        raise ConfigError("actions.require_confirmation must be true when actions are enabled")


def state_dir(config: dict[str, Any]) -> Path:
    return expand_path(config["storage"]["state_dir"])


def incident_spool_dir(config: dict[str, Any]) -> Path:
    return expand_path(config["assistant"]["incident_spool"])


def _validate_types(value: Any, expected: Any, prefix: str = "") -> None:
    for key, expected_value in expected.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        actual = value.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual, dict):
                raise ConfigError(f"{dotted} must be a table")
            _validate_types(actual, expected_value, dotted)
        elif isinstance(expected_value, bool):
            if not isinstance(actual, bool):
                raise ConfigError(f"{dotted} must be a boolean")
        elif isinstance(expected_value, int) and not isinstance(expected_value, bool):
            if not isinstance(actual, int) or isinstance(actual, bool):
                raise ConfigError(f"{dotted} must be an integer")
        elif isinstance(expected_value, float):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                raise ConfigError(f"{dotted} must be a number")
        elif isinstance(expected_value, str):
            if not isinstance(actual, str):
                raise ConfigError(f"{dotted} must be a string")
        elif isinstance(expected_value, list):
            if not isinstance(actual, list):
                raise ConfigError(f"{dotted} must be a list")


def _validate_cpu_rule(name: str, rule: dict[str, Any]) -> None:
    _require_range(f"{name}.trigger_percent", rule["trigger_percent"], 1, 100)
    _require_range(f"{name}.recover_percent", rule["recover_percent"], 1, 100)
    if rule["recover_percent"] >= rule["trigger_percent"]:
        raise ConfigError(f"{name}.recover_percent must be lower than trigger_percent")
    _require_range(f"{name}.min_duration_seconds", rule["min_duration_seconds"], 5, 24 * 3600)
    _require_range(f"{name}.recovery_duration_seconds", rule["recovery_duration_seconds"], 5, 24 * 3600)
    _require_range(f"{name}.cooldown_minutes", rule["cooldown_minutes"], 1, 24 * 60)


def _require_range(name: str, value: int | float, minimum: int | float, maximum: int | float) -> None:
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")


def _validate_time(name: str, value: str) -> None:
    parts = value.split(":")
    if len(parts) != 2:
        raise ConfigError(f"{name} must use HH:MM format")
    try:
        hour, minute = (int(part) for part in parts)
    except ValueError as exc:
        raise ConfigError(f"{name} must use HH:MM format") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigError(f"{name} must use a valid 24-hour time")


def _validate_secret_ref(name: str, value: str) -> None:
    if value and not value.startswith(("env:", "keychain:")):
        raise ConfigError(f"{name} must use an env: or keychain: reference, not a literal secret")
