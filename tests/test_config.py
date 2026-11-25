from __future__ import annotations

from pathlib import Path

import pytest

from macos_resource_sentinel.config import (
    ConfigError,
    DEFAULT_CONFIG,
    load_config,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "config" / "example.toml"


def test_default_config_is_valid() -> None:
    validate_config(DEFAULT_CONFIG)


def test_public_example_loads_and_matches_schema() -> None:
    loaded = load_config(EXAMPLE_CONFIG)

    assert loaded.path == EXAMPLE_CONFIG
    assert loaded.used_defaults is False
    assert loaded.data["schema_version"] == 1
    assert loaded.data["rules"]["cpu"]["trigger_percent"] == 85


def test_partial_config_is_merged_with_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
schema_version = 1

[rules.cpu]
trigger_percent = 90
""".strip(),
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.data["rules"]["cpu"]["trigger_percent"] == 90
    assert loaded.data["rules"]["cpu"]["recover_percent"] == 65
    assert loaded.data["notifications"]["channels"] == ["macos"]


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\nunknown_field = true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown configuration field"):
        load_config(config_path)


def test_recovery_threshold_must_be_lower_than_trigger(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
schema_version = 1

[rules.cpu]
trigger_percent = 80
recover_percent = 80
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="recover_percent"):
        load_config(config_path)


def test_literal_telegram_secret_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
schema_version = 1

[notifications.telegram]
bot_token_ref = "123456:not-a-real-token"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="env: or keychain:"):
        load_config(config_path)
