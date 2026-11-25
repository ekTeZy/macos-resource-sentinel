# Contributing

Thanks for helping improve macOS Resource Sentinel.

## Development setup

```bash
git clone https://github.com/ektezy/macos-resource-sentinel.git
cd macos-resource-sentinel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

Python 3.11 or newer is required. The main target platform is macOS, but tests
should also pass on Linux where platform-specific signals are unavailable.

## Workflow

1. Open an issue or discuss the change in an existing one.
2. Create a branch from `main`.
3. Keep changes small and focused.
4. Add or update tests for behavior changes.
5. Update documentation and `CHANGELOG.md` when users are affected.
6. Run the full test suite.
7. Open a pull request.

## Commit style

Use clear conventional commit subjects where practical:

- `feat:` for user-facing features;
- `fix:` for bug fixes;
- `docs:` for documentation-only changes;
- `test:` for test-only changes;
- `refactor:` for behavior-preserving code changes;
- `chore:` for maintenance and release preparation.

Examples:

```text
feat: add telegram notification channel
fix: require full rule duration before activation
docs: document launchagent installation
```

## Code expectations

- Keep monitoring decisions deterministic.
- Do not put secrets, tokens, chat IDs, hostnames, or personal paths in the
  repository.
- Prefer structured data over parsing human-readable output.
- Keep privacy-sensitive process command lines out of logs by default.
- Validate user configuration and fail with actionable errors.
- Avoid new runtime dependencies unless they clearly reduce risk or complexity.

## Safety rules for actions

The action executor has a stricter bar than monitoring code:

- no arbitrary shell execution;
- no `sudo` requirement;
- no process termination without explicit confirmation;
- always validate PID, process identity, owner, and start time;
- record every request and result in the audit log.

## Tests

```bash
python -m pytest -q
```

Add regression tests for every bug fix. Platform-specific behavior should be
mocked so the suite remains portable.

## Versioning and releases

The project uses Semantic Versioning. See [docs/release.md](docs/release.md)
before changing versions or publishing a release.
