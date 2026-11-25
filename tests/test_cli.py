from __future__ import annotations

import json
from pathlib import Path

from macos_resource_sentinel.cli import EXIT_OK, main


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "config" / "example.toml"


def test_version(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert "mac-sentinel" in output


def test_doctor_json_with_public_example(capsys) -> None:
    exit_code = main(["--config", str(EXAMPLE_CONFIG), "doctor", "--json"])

    assert exit_code == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert {check["name"] for check in report["checks"]} >= {
        "python.version",
        "dependency.psutil",
        "config.load",
        "process.access",
    }


def test_collect_once_outputs_normalized_json(capsys) -> None:
    exit_code = main([
        "--config",
        str(EXAMPLE_CONFIG),
        "collect",
        "--once",
        "--interval",
        "0",
        "--top",
        "1",
    ])

    assert exit_code == EXIT_OK
    sample = json.loads(capsys.readouterr().out)
    assert sample["logical_cpus"] >= 1
    assert "cpu_percent" in sample
    assert "memory" in sample
    assert "swap" in sample
    assert len(sample["top_processes"]) <= 1


def test_monitor_validate_config(capsys) -> None:
    exit_code = main(["--config", str(EXAMPLE_CONFIG), "monitor", "--validate-config"])

    assert exit_code == EXIT_OK
    assert "configuration is valid" in capsys.readouterr().out


def test_monitor_can_collect_one_sample_and_write_events(tmp_path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config_path.write_text(
        f'''
schema_version = 1

[sampling]
interval_seconds = 1
startup_grace_seconds = 60

[storage]
state_dir = "{state_dir}"
'''.strip(),
        encoding="utf-8",
    )

    exit_code = main([
        "--config",
        str(config_path),
        "monitor",
        "--max-samples",
        "1",
    ])

    assert exit_code == EXIT_OK
    assert "monitor stopped after 1 sample" in capsys.readouterr().out
    events = [json.loads(line) for line in (state_dir / "events.jsonl").read_text().splitlines()]
    assert [event["event_type"] for event in events] == ["monitor.started", "monitor.stopped"]
