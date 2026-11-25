# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-11-25

### Added

- Stable notification message formatting for opened and resolved incidents.
- Native macOS notification delivery through `osascript` without shell command
  interpolation.
- Telegram Bot API delivery with bounded retries.
- Notification rate limits, quiet hours, recovery policy, and delivery audit
  events.
- Notification tests for formatting, policy, macOS delivery, and Telegram
  retries.

## [0.2.0] - 2026-11-25

### Added

- Continuous foreground monitor loop with configurable sampling.
- Rolling rule engine for sustained aggregate CPU, process CPU, load average,
  memory pressure, swap growth, and disk capacity.
- macOS memory pressure collection through
  `kern.memorystatus_vm_pressure_level`.
- Persistent incident lifecycle with open, resolve, cooldown, and restart-safe
  state.
- Append-only JSONL event and incident history.
- Monitor regression tests and CLI coverage.

### Fixed

- Rules now require both enough samples and the configured time span before an
  incident can activate.

## [0.1.0] - 2026-11-25

### Added

- Public architecture and product specification.
- Python package metadata and `src` layout.
- TOML configuration loading, merging, and validation.
- `mac-sentinel doctor`.
- `mac-sentinel collect --once`.
- LaunchAgent template and installation documentation.
- Initial test suite.

[Unreleased]: https://github.com/ektezy/macos-resource-sentinel/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ektezy/macos-resource-sentinel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ektezy/macos-resource-sentinel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ektezy/macos-resource-sentinel/releases/tag/v0.1.0
