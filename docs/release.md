# Release process

This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Version policy

While the project is before `1.0.0`:

- **PATCH** (`0.2.1`) — backwards-compatible fixes and internal hardening.
- **MINOR** (`0.3.0`) — backwards-compatible features such as a new command,
  rule, notification channel, or installer capability.
- **MAJOR** (`1.0.0`) — the first stable public interface.

Breaking changes before `1.0.0` should be avoided where possible. If one is
necessary, document it prominently in the changelog and release notes.

## Version sources

The version must match in all of these places:

- `pyproject.toml` under `[project].version`;
- `src/macos_resource_sentinel/__init__.py`;
- the newest heading in `CHANGELOG.md`;
- the Git tag without the leading `v`.

The test suite checks the first three sources. The release workflow checks the
Git tag.

## Release checklist

1. Ensure `main` is green in CI.
2. Update `pyproject.toml` and `src/macos_resource_sentinel/__init__.py`:

   ```bash
   python3 scripts/bump_version.py X.Y.Z
   ```

3. Move changes from `Unreleased` to a new changelog section.
4. Update release documentation if the install or upgrade flow changed.
5. Run tests locally:

   ```bash
   python3 -m pip install -e '.[dev]'
   python3 -m pytest -q
   ```

6. Commit the release preparation:

   ```bash
   git add pyproject.toml src/macos_resource_sentinel/__init__.py CHANGELOG.md
   git commit -m "chore: release vX.Y.Z"
   git push origin main
   ```

7. Create and push an annotated tag:

   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

8. Confirm that the Release workflow created a GitHub release and attached the
   source distribution and wheel.

## Hotfix releases

For a hotfix:

1. Fix the bug on a branch.
2. Add or update a regression test.
3. Merge after CI passes.
4. Bump the patch version.
5. Tag `vX.Y.Z`.

## Pre-releases

Use PEP 440 versions for pre-releases:

- `0.3.0a1` — alpha;
- `0.3.0b1` — beta;
- `0.3.0rc1` — release candidate.

The matching Git tags are `v0.3.0a1`, `v0.3.0b1`, and `v0.3.0rc1`.
