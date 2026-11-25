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
from .incident_report import (
    IncidentQuery,
    IncidentReportError,
    build_diagnostic_bundle,
    find_incident,
    query_incidents,
    summarize,
)
from .monitor import MonitorRunner
from .storage import JsonlStore
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
        help="inspect recorded incidents",
    )
    incidents_sub = incidents_parser.add_subparsers(dest="incident_command", required=True)

    incidents_list = incidents_sub.add_parser("list", help="list incidents, newest first")
    incidents_list.add_argument("--state", help="filter by state (firing or resolved)")
    incidents_list.add_argument("--fingerprint", help="filter by rule fingerprint")
    incidents_list.add_argument("--limit", type=int, default=20, help="maximum rows (default: 20)")
    incidents_list.add_argument("--json", action="store_true", help="print a JSON array")

    incidents_show = incidents_sub.add_parser("show", help="show one incident in detail")
    incidents_show.add_argument("incident_id", help="incident identifier, e.g. INC-20261125-0001")
    incidents_show.add_argument("--json", action="store_true", help="print the incident as JSON")

    incidents_bundle = incidents_sub.add_parser(
        "bundle",
        help="print a diagnostic bundle for an assistant",
    )
    incidents_bundle.add_argument("incident_id", help="incident identifier")

    summary_parser = subparsers.add_parser(
        "summary",
        help="aggregate incident history for a period",
    )
    summary_parser.add_argument("--period", choices=["day", "week"], default="day")
    summary_parser.add_argument("--json", action="store_true", help="print the summary as JSON")

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
        if args.command == "incidents":
            return _cmd_incidents(args)
        if args.command == "summary":
            return _cmd_summary(args)
        if args.command == "actions":
            return _cmd_planned(args.command)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except CollectionError as exc:
        print(f"collection error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (StorageError, ServiceError, IncidentReportError, ValueError) as exc:
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


def _cmd_incidents(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    store = JsonlStore(state_dir(loaded.data))

    if args.incident_command == "list":
        query = IncidentQuery(
            state=args.state,
            fingerprint=args.fingerprint,
            limit=args.limit,
        )
        records = query_incidents(store, query)
        if args.json:
            print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2))
        else:
            _print_incident_table(records)
        return EXIT_OK

    if args.incident_command == "show":
        record = find_incident(store, args.incident_id)
        if args.json:
            print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_incident_detail(record)
        return EXIT_OK

    if args.incident_command == "bundle":
        bundle = build_diagnostic_bundle(store, args.incident_id)
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
        return EXIT_OK

    raise ValueError(f"unknown incidents command: {args.incident_command}")


def _cmd_summary(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    store = JsonlStore(state_dir(loaded.data))
    report = summarize(store, period=args.period)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"summary for the last {args.period} (since {report['window_start']})")
        print(f"total incidents: {report['total_incidents']} (open: {report['open_incidents']})")
        for rule, count in report["by_rule"].items():
            print(f"  {rule}: {count}")
    return EXIT_OK


def _print_incident_table(records: list[Any]) -> None:
    if not records:
        print("no incidents recorded")
        return
    header = f"{'INCIDENT':<22} {'STATE':<9} {'SEVERITY':<9} {'RULE':<18} OPENED"
    print(header)
    print("-" * len(header))
    for record in records:
        print(
            f"{record.incident_id:<22} {record.state:<9} {record.severity:<9} "
            f"{record.rule:<18} {record.opened_at:%Y-%m-%d %H:%M}Z"
        )


def _print_incident_detail(record: Any) -> None:
    print(f"incident:  {record.incident_id}")
    print(f"rule:      {record.rule}")
    print(f"state:     {record.state}")
    print(f"severity:  {record.severity}")
    print(f"message:   {record.message}")
    print(f"opened:    {record.opened_at:%Y-%m-%d %H:%M:%S}Z")
    if record.resolved_at:
        print(f"resolved:  {record.resolved_at:%Y-%m-%d %H:%M:%S}Z")
    if record.process:
        name = record.process.get("name", "?")
        pid = record.process.get("pid", "?")
        cpu = record.process.get("cpu_percent")
        cpu_text = f"{cpu:.0f}% CPU" if isinstance(cpu, (int, float)) else ""
        print(f"process:   {name} (pid {pid}) {cpu_text}".rstrip())
    print("\nuse 'mac-sentinel incidents bundle INCIDENT_ID' for the assistant-ready JSON")


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
