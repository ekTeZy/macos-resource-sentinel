"""User-level LaunchAgent installation for macOS Resource Sentinel."""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

LABEL = "com.macos-resource-sentinel"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
ENV_PREFIXES = ("MAC_SENTINEL_",)

THROTTLE_INTERVAL_SECONDS = 10


class ServiceError(RuntimeError):
    """Raised when service installation or removal fails."""


@dataclass(frozen=True, slots=True)
class ServicePlan:
    """Everything needed to materialize the LaunchAgent plist."""

    label: str
    executable: str
    config_path: Path
    state_dir: Path
    plist_path: Path
    environment: dict[str, str] = field(default_factory=dict)

    def plist_bytes(self) -> bytes:
        return render_plist(self)

    def summary(self) -> str:
        return (
            f"label={self.label} executable={self.executable} "
            f"config={self.config_path} state_dir={self.state_dir}"
        )


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Observed state of the LaunchAgent."""

    installed: bool
    loaded: bool
    plist_path: Path
    message: str


def render_plist(plan: ServicePlan) -> bytes:
    """Render the LaunchAgent plist without any shell interpolation."""
    document: dict[str, object] = {
        "Label": plan.label,
        "ProgramArguments": [
            plan.executable,
            "--config",
            str(plan.config_path),
            "monitor",
        ],
        "EnvironmentVariables": plan.environment,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": THROTTLE_INTERVAL_SECONDS,
        "StandardOutPath": str(plan.state_dir / "monitor.stdout.log"),
        "StandardErrorPath": str(plan.state_dir / "monitor.stderr.log"),
        "ProcessType": "Background",
        "LowPriorityIO": True,
    }
    return plistlib.dumps(document, sort_keys=False)


def build_plan(
    *,
    config_path: Path,
    state_dir: Path,
    environment: Mapping[str, str] | None = None,
    executable: str | None = None,
) -> ServicePlan:
    """Resolve the concrete plan for the current machine."""
    resolved_executable = executable or shutil.which("mac-sentinel")
    if not resolved_executable:
        raise ServiceError(
            "the 'mac-sentinel' executable was not found on PATH; "
            "install the package first (for example with pipx)"
        )

    resolved_config = config_path.expanduser().resolve()
    if not resolved_config.is_file():
        raise ServiceError(f"configuration file does not exist: {resolved_config}")

    resolved_state = state_dir.expanduser().resolve()
    environment = dict(environment) if environment is not None else _local_environment()

    return ServicePlan(
        label=LABEL,
        executable=str(Path(resolved_executable).resolve()),
        config_path=resolved_config,
        state_dir=resolved_state,
        plist_path=PLIST_PATH,
        environment=environment,
    )


def config_permission_warnings(config_path: Path) -> list[str]:
    """Warn when the config is readable by group or others."""
    warnings: list[str] = []
    try:
        mode = stat.S_IMODE(config_path.stat().st_mode)
    except OSError:
        return warnings
    if mode & 0o077:
        warnings.append(
            f"configuration permissions are {oct(mode)}; "
            "consider 'chmod 600' so other accounts cannot read it"
        )
    return warnings


def install_service(
    plan: ServicePlan,
    *,
    run: bool = True,
) -> list[str]:
    """Install the plist and load the agent. Returns human-readable actions."""
    actions: list[str] = []

    if sys.platform != "darwin":
        raise ServiceError("LaunchAgent installation is only supported on macOS")

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plan.state_dir.mkdir(parents=True, exist_ok=True)

    payload = plan.plist_bytes()
    existing = PLIST_PATH.read_bytes() if PLIST_PATH.is_file() else None
    if existing == payload:
        actions.append("plist is already up to date")
    else:
        PLIST_PATH.write_bytes(payload)
        os.chmod(PLIST_PATH, 0o644)
        actions.append(f"wrote {PLIST_PATH}")

    if not run:
        return actions

    domain = f"gui/{os.getuid()}"
    if _launchctl(["print", f"{domain}/{LABEL}"], check=False).returncode == 0:
        actions.append("agent already loaded; restarting it")
        _launchctl_or_raise(["kickstart", "-k", f"{domain}/{LABEL}"])
    else:
        result = _launchctl(["bootstrap", domain, str(PLIST_PATH)], check=False)
        if result.returncode != 0:
            # Older macOS accepts load; bootstrap output stays in the error.
            _launchctl_or_raise(["load", "-w", str(PLIST_PATH)])
        actions.append(f"loaded agent {LABEL}")

    return actions


def uninstall_service(*, run: bool = True) -> list[str]:
    """Unload the agent and remove the plist. Returns human-readable actions."""
    actions: list[str] = []
    domain = f"gui/{os.getuid()}"

    if run:
        result = _launchctl(["bootout", f"{domain}/{LABEL}"], check=False)
        if result.returncode == 0:
            actions.append(f"unloaded agent {LABEL}")
        elif _launchctl(["print", f"{domain}/{LABEL}"], check=False).returncode != 0:
            actions.append("agent was not loaded")
        else:
            _launchctl_or_raise(["unload", str(PLIST_PATH)])
            actions.append(f"unloaded agent {LABEL}")

    if PLIST_PATH.is_file():
        PLIST_PATH.unlink()
        actions.append(f"removed {PLIST_PATH}")
    else:
        actions.append("plist was already absent")

    return actions


def service_status() -> ServiceStatus:
    """Inspect the current LaunchAgent state."""
    installed = PLIST_PATH.is_file()
    if sys.platform != "darwin":
        return ServiceStatus(
            installed=installed,
            loaded=False,
            plist_path=PLIST_PATH,
            message="LaunchAgent status is only available on macOS",
        )

    domain = f"gui/{os.getuid()}"
    result = _launchctl(["print", f"{domain}/{LABEL}"], check=False)
    loaded = result.returncode == 0

    if loaded:
        message = f"agent {LABEL} is loaded"
    elif installed:
        message = f"plist exists at {PLIST_PATH} but the agent is not loaded"
    else:
        message = "agent is not installed"
    return ServiceStatus(
        installed=installed,
        loaded=loaded,
        plist_path=PLIST_PATH,
        message=message,
    )


def _local_environment() -> dict[str, str]:
    """Collect sentinel-specific variables from the current environment."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.startswith(ENV_PREFIXES)
    }


def _launchctl(arguments: Sequence[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _launchctl_or_raise(arguments: Sequence[str]) -> None:
    try:
        result = _launchctl(arguments, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"launchctl {' '.join(arguments)} failed: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ServiceError(f"launchctl {' '.join(arguments)} failed: {detail}")


__all__ = [
    "LABEL",
    "PLIST_PATH",
    "ServiceError",
    "ServicePlan",
    "ServiceStatus",
    "build_plan",
    "config_permission_warnings",
    "install_service",
    "render_plist",
    "service_status",
    "uninstall_service",
]
