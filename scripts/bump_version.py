#!/usr/bin/env python3
"""Update the package version in pyproject.toml and __init__.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "macos_resource_sentinel" / "__init__.py"
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)(0|[1-9]\d*))?$")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 scripts/bump_version.py X.Y.Z", file=sys.stderr)
        return 2

    version = sys.argv[1].removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        print(f"invalid semantic version: {sys.argv[1]}", file=sys.stderr)
        return 2

    pyproject = PYPROJECT.read_text(encoding="utf-8")
    updated_pyproject, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        pyproject,
        count=1,
    )
    if count != 1:
        print("could not find [project].version in pyproject.toml", file=sys.stderr)
        return 1
    PYPROJECT.write_text(updated_pyproject, encoding="utf-8")

    init = INIT.read_text(encoding="utf-8")
    updated_init, count = re.subn(
        r'(?m)^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        init,
        count=1,
    )
    if count != 1:
        print("could not find __version__ in package __init__.py", file=sys.stderr)
        return 1
    INIT.write_text(updated_init, encoding="utf-8")

    print(f"version set to {version}")
    print("next: update CHANGELOG.md and run tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
