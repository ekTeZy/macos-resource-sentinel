"""Command-line interface for macOS Resource Sentinel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import __version__
from .collector import CollectionError, collect_once
from .config import ConfigError, load_config, state_dir
from .doctor import DoctorReport, run_doctor
from .monitor import MonitorRunner
from .service import (
    ServiceError,
    build_plan,
    config_permission_warnings,
    install_service,
    service_status,
    uninstall_service,
)
from .storage import StorageError


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_IMPLEMENTED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mac-sentinel",
        description="Local macOS resource incident monitor.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        help="path to config.toml (default: ~/.config/macos-resource-sentinel/config.toml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect",
        help="collect normalized system metrics",
    )
    collect_parser.add_argument(
        "--once",
        action="store_true",
        help="collect one sample and exit (current behavior)",
    )
    collect_parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="CPU measurement interval in seconds (default: 0.2)",
    )
    collect_parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="number of processes to include (default: 5)",
    )
    collect_parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON output",
    )
    collect_parser.add_argument(
        "--output",
        help="write JSON to a file instead of stdout",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="check local environment and configuration",
    )
    doctor_parser.add_argument("--json", action="store_true", help="print a JSON report")
    doctor_parser.add_argument(
        "--create-state-dirs",
        action="store_true",
        help="create the configured local state directories",
    )

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="run the continuous deterministic monitor",
    )
    monitor_parser.add_argument(
        "--validate-config",
        action="store_true",
        help="validate configuration without starting the loop",
    )
    monitor_parser.add_argument(
        "--max-samples",
        type=int,
        help="stop after collecting this many samples (useful for diagnostics)",
    )
    monitor_parser.add_argument(
        "--ignore-startup-grace",
        action="store_true",
        help="do not suppress confirmed signals during startup grace",
    )

    incidents_parser = subparsers.add_parser(
        "incidents",
        help="inspect recorded incidents (planned)",
    )
    incidents_parser.add_argument("incident_command", nargs="?", help="list or show")

    actions_parser = subparsers.add_parser(
        "actions",
        help="request or confirm constrained actions (planned)",
    )
    actions_parser.add_argument("action_command", nargs="?", help="request or confirm")

    subparsers.add_parser(
        "install-service",
        help="install the user-level LaunchAgent and start it",
    )
    subparsers.add_parser(
        "uninstall-service",
        help="stop the LaunchAgent and remove its plist",
    )
    subparsers.add_parser(
        "service-status",
        help="show LaunchAgent installation and load state",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            return _cmd_collect(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "monitor":
            return _cmd_monitor(args)
        if args.command == "install-service":
            return _cmd_install_service(args)
        if args.command == "uninstall-service":
            return _cmd_uninstall_service(args)
        if args.command == "service-status":
            return _cmd_service_status(args)
        if args.command in {"incidents", "actions"}:
            return _cmd_planned(args.command)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except CollectionError as exc:
        print(f"collection error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (StorageError, ServiceError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130

    parser.error(f"unknown command: {args.command}")
    return EXIT_ERROR


def _cmd_collect(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    _print_warnings(loaded.warnings, sys.stderr)

    disk_paths = loaded.data["rules"]["disk"]["paths"]
    sample = collect_once(
        interval_seconds=args.interval,
        disk_paths=disk_paths,
        top_process_count=args.top,
    )
    payload = sample.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
        print(str(output_path))
    else:
        print(text)
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(args.config, create_state_dirs=args.create_state_dirs)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_doctor_text(report)
    return EXIT_OK if report.ok else EXIT_ERROR


def _cmd_monitor(args: argparse.Namespace) -> int:
    loaded = load_config(args.config, require_file=True)
    _print_warnings(loaded.warnings, sys.stderr)
    if args.validate_config:
        print("configuration is valid")
        return EXIT_OK

    runner = MonitorRunner(loaded.data, state_dir=state_dir(loaded.data))
    collected = runner.run(
        max_samples=args.max_samples,
        ignore_startup_grace=args.ignore_startup_grace,
    )
    print(f"monitor stopped after {collected} sample(s)")
    return EXIT_OK


def _cmd_install_service(args: argparse.Namespace) -> int:
    loaded = load_config(args.config, require_file=True)
    _print_warnings(loaded.warnings, sys.stderr)

    config_path = Path(args.config).expanduser() if args.config else _default_config_path()
    plan = build_plan(
        config_path=config_path,
        state_dir=state_dir(loaded.data),
    )
    for warning in config_permission_warnings(plan.config_path):
        print(f"warning: {warning}", file=sys.stderr)

    actions = install_service(plan)
    for action in actions:
        print(action)
    print("service installed; check status with: mac-sentinel service-status")
    return EXIT_OK


def _cmd_uninstall_service(args: argparse.Namespace) -> int:
    actions = uninstall_service()
    for action in actions:
        print(action)
    return EXIT_OK


def _cmd_service_status(args: argparse.Namespace) -> int:
    status = service_status()
    print(f"installed: {'yes' if status.installed else 'no'}")
    print(f"loaded: {'yes' if status.loaded else 'no'}")
    print(f"plist: {status.plist_path}")
    print(f"message: {status.message}")
    return EXIT_OK


def _default_config_path() -> Path:
    from .config import DEFAULT_CONFIG_PATH

    return DEFAULT_CONFIG_PATH


def _cmd_planned(command: str) -> int:
    print(f"'{command}' is planned for a later milestone", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def _print_warnings(warnings: list[str], stream: TextIO) -> None:
    for warning in warnings:
        print(f"warning: {warning}", file=stream)


def _print_doctor_text(report: DoctorReport) -> None:
    status_icon = {
        "ok": "OK",
        "warning": "WARN",
        "error": "ERROR",
    }
    print(f"mac-sentinel doctor ({report.version})")
    for check in report.checks:
        label = status_icon.get(check.status, check.status.upper())
        print(f"[{label}] {check.name}: {check.message}")
    print("result: ok" if report.ok else "result: failed")
