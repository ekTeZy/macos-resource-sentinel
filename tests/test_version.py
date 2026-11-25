from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_package_version_matches_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    init_text = (ROOT / "src/macos_resource_sentinel/__init__.py").read_text()
    match = re.search(r'__version__ = "([^"]+)"', init_text)

    assert match is not None
    assert match.group(1) == project["version"]


def test_changelog_contains_current_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert f"## [{project['version']}]" in changelog
