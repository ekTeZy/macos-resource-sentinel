from __future__ import annotations

import json
from pathlib import Path

from macos_resource_sentinel.cli import EXIT_NOT_IMPLEMENTED, EXIT_OK, main


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


def test_monitor_loop_is_explicitly_not_implemented(capsys) -> None:
    exit_code = main(["--config", str(EXAMPLE_CONFIG), "monitor"])

    assert exit_code == EXIT_NOT_IMPLEMENTED
    assert "Milestone 2" in capsys.readouterr().err
