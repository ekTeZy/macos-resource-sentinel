"""Tests for the LaunchAgent service management module."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from macos_resource_sentinel import service
from macos_resource_sentinel.service import (
    ServiceError,
    ServicePlan,
    build_plan,
    config_permission_warnings,
    render_plist,
)


@pytest.fixture
def plan(tmp_path: Path) -> ServicePlan:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    return ServicePlan(
        label="com.macos-resource-sentinel",
        executable="/usr/local/bin/mac-sentinel",
        config_path=config_path,
        state_dir=tmp_path / "state",
        plist_path=tmp_path / "LaunchAgents" / "com.macos-resource-sentinel.plist",
        environment={"MAC_SENTINEL_TELEGRAM_CHAT_ID": "42"},
    )


def test_render_plist_contains_monitor_invocation(plan: ServicePlan) -> None:
    document = plistlib.loads(render_plist(plan))

    assert document["Label"] == "com.macos-resource-sentinel"
    assert document["ProgramArguments"] == [
        "/usr/local/bin/mac-sentinel",
        "--config",
        str(plan.config_path),
        "monitor",
    ]
    assert document["RunAtLoad"] is True
    assert document["KeepAlive"] is True
    assert document["StandardOutPath"] == str(plan.state_dir / "monitor.stdout.log")
    assert document["StandardErrorPath"] == str(plan.state_dir / "monitor.stderr.log")
    assert document["EnvironmentVariables"] == {
        "MAC_SENTINEL_TELEGRAM_CHAT_ID": "42"
    }


def test_render_plist_escapes_paths(plan: ServicePlan) -> None:
    plan_with_space = ServicePlan(
        label=plan.label,
        executable=plan.executable,
        config_path=Path("/tmp/my config/config.toml"),
        state_dir=plan.state_dir,
        plist_path=plan.plist_path,
        environment={},
    )

    document = plistlib.loads(render_plist(plan_with_space))

    # plist arguments are an array, so spaces need no shell quoting.
    assert document["ProgramArguments"][2] == "/tmp/my config/config.toml"


def test_build_plan_requires_existing_config(tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="does not exist"):
        build_plan(
            config_path=tmp_path / "missing.toml",
            state_dir=tmp_path / "state",
            executable="/usr/local/bin/mac-sentinel",
        )


def test_build_plan_requires_executable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")

    with pytest.raises(ServiceError, match="executable"):
        build_plan(
            config_path=config_path,
            state_dir=tmp_path / "state",
            executable=None if sys.platform != "darwin" else "/nonexistent/mac-sentinel",
        )


def test_build_plan_collects_sentinel_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    monkeypatch.setenv("MAC_SENTINEL_TELEGRAM_BOT_TOKEN", "token-value")
    monkeypatch.setenv("UNRELATED_VARIABLE", "ignored")
    monkeypatch.setenv("MAC_SENTINEL_STATE_DIR", str(tmp_path / "state"))

    plan = build_plan(
        config_path=config_path,
        state_dir=tmp_path / "state",
        executable="/usr/local/bin/mac-sentinel",
    )

    assert plan.environment == {
        "MAC_SENTINEL_TELEGRAM_BOT_TOKEN": "token-value",
        "MAC_SENTINEL_STATE_DIR": str(tmp_path / "state"),
    }
    assert "UNRELATED_VARIABLE" not in plan.environment


def test_config_permission_warnings_detect_open_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    config_path.chmod(0o644)

    warnings = config_permission_warnings(config_path)

    assert warnings and "chmod 600" in warnings[0]


def test_config_permission_warnings_quiet_for_private_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    config_path.chmod(0o600)

    assert config_permission_warnings(config_path) == []


def test_install_and_uninstall_round_trip(
    plan: ServicePlan, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if sys.platform != "darwin":
        pytest.skip("launchctl interaction requires macOS")

    monkeypatch.setattr(service, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")
    monkeypatch.setattr(service, "PLIST_PATH", plan.plist_path)

    # run=False keeps the test hermetic: only the plist file is materialized.
    actions = service.install_service(plan, run=False)
    assert plan.plist_path.is_file()
    assert any("wrote" in action for action in actions)

    # Installing the same plan again is a no-op.
    repeat_actions = service.install_service(plan, run=False)
    assert any("up to date" in action for action in repeat_actions)


def test_status_reporting_without_launchd(plan: ServicePlan) -> None:
    status = service.service_status()
    assert status.plist_path == service.PLIST_PATH
    assert isinstance(status.message, str)
