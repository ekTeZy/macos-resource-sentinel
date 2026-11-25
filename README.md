# macOS Resource Sentinel

[![CI](https://github.com/ektezy/macos-resource-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/ektezy/macos-resource-sentinel/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ektezy/macos-resource-sentinel)](https://github.com/ektezy/macos-resource-sentinel/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local monitoring agent for macOS that watches for **sustained resource problems**, not harmless two-second spikes.

It tracks CPU, memory pressure, swap growth, load average, and disk capacity. When a problem persists long enough to matter, it creates a structured incident, stores local evidence, and sends a stable notification through macOS or Telegram. Assistant diagnostics and user-approved actions are staged in the following milestones.

## What it does

- Samples system metrics every few seconds.
- Ignores short-lived CPU spikes and other noisy measurements.
- Opens an incident only after a threshold has held for a configured duration.
- Keeps related evidence in a structured incident record; notification grouping is planned with the notifier.
- Identifies the processes most likely responsible for the incident.
- Stores local machine-readable history for later inspection.
- Sends deterministic incident notifications with cooldowns, quiet hours, and rate limits.
- Will support safe, explicit follow-up actions such as diagnostics and confirmed `SIGTERM`.

## How it works

```text
metrics → rules → incident state → notification → optional assistant diagnostics
```

The monitoring path is deterministic:

1. **Collector** reads CPU, memory, swap, load, disk, and process data.
2. **Rule Engine** checks thresholds, durations, recovery values, and exclusions.
3. **Incident Manager** applies startup grace, cooldowns, grouping, and recovery.
4. **Notifier** sends one stable message for a confirmed incident.
5. **Assistant Bridge** can inspect the incident and suggest a next step.
6. **Action Executor** performs only allowlisted operations after confirmation.

Short spike:

```text
CPU: 97% for 4 seconds → no notification
```

Sustained problem:

```text
CPU: 85%+ for 3 minutes → incident opened → one notification
```

## Example notification

```text
MacBook: sustained CPU usage

Average for 3 minutes: 91%
Primary process: node — 184% CPU, 2.4 GB RAM
Additional signal: swap grew by 780 MB
Duration: 03:20
Incident: INC-20261125-0007

Available actions:
1. Inspect the incident
2. Request process termination
3. Snooze this process for 30 minutes
```

The template is stable and machine-generated, so automated tooling and an assistant can rely on its structure. The action list is shown only when actions are enabled locally.

## CLI quick start

The command is `mac-sentinel`. Milestone 1 currently includes environment checks and one-shot metric collection:

```bash
# Check the local environment and configuration
mac-sentinel doctor

# Print one normalized system sample as JSON
mac-sentinel collect --once --pretty

# Validate a configuration file without starting the monitor
mac-sentinel monitor --validate-config

# Run the deterministic monitor in the foreground
mac-sentinel monitor

# Collect a limited number of samples and exit
mac-sentinel monitor --max-samples 3
```

Incident history is inspectable at any time:

```bash
# List incidents, newest first
mac-sentinel incidents list

# Show one incident with its rule, process, and timing
mac-sentinel incidents show INCIDENT_ID

# Print an assistant-ready diagnostic bundle as JSON
mac-sentinel incidents bundle INCIDENT_ID

# Aggregate history for a report
mac-sentinel summary --period day
mac-sentinel summary --period week --json
```

Approved process actions (disabled by default, see below):

```bash
mac-sentinel actions request INCIDENT_ID process.terminate --pid 4242
mac-sentinel actions confirm ACT-20261125-165245-324561
mac-sentinel actions list
```

Foreground monitoring writes local incident history and state to:

```text
~/.local/state/macos-resource-sentinel/
├── events.jsonl
├── incidents.jsonl
├── actions.jsonl
├── monitor.log
├── notification-state.json
└── state.json
```

## User installation

Python 3.11 or newer is required. The recommended user-level installer is
[`pipx`](https://pipx.pypa.io/):

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/ektezy/macos-resource-sentinel.git
mac-sentinel doctor
```

After a tagged release is published, install that release explicitly:

```bash
pipx install git+https://github.com/ektezy/macos-resource-sentinel.git@v0.2.0
```

Upgrade or remove:

```bash
pipx upgrade macos-resource-sentinel
pipx uninstall macos-resource-sentinel
```

## Development installation

```bash
git clone https://github.com/ektezy/macos-resource-sentinel.git
cd macos-resource-sentinel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

For local development without installing the package:

```bash
PYTHONPATH=src python3 -m macos_resource_sentinel doctor
PYTHONPATH=src python3 -m macos_resource_sentinel collect --once --pretty
PYTHONPATH=src python3 -m pytest -q
```

## Configuration

The public example configuration lives at:

```text
config/example.toml
```

A local copy should be placed at:

```text
~/.config/macos-resource-sentinel/config.toml
```

Basic setup:

```bash
mkdir -p ~/.config/macos-resource-sentinel
cp config/example.toml ~/.config/macos-resource-sentinel/config.toml
chmod 600 ~/.config/macos-resource-sentinel/config.toml
```

Example CPU rule:

```toml
[rules.cpu]
enabled = true
trigger_percent = 85
recover_percent = 65
min_duration_seconds = 180
recovery_duration_seconds = 120
cooldown_minutes = 30
```

This means:

- CPU must stay above 85% for three minutes before an incident opens;
- CPU must fall below 65% for two minutes before the incident resolves;
- the same problem is not reported again for at least thirty minutes.

## Notifications and actions

Two notification channels are supported:

- native macOS notifications;
- Telegram Bot API.

Native macOS delivery works out of the box:

```toml
[notifications]
enabled = true
channels = ["macos"]
max_per_hour = 4
quiet_hours_enabled = false
```

For Telegram, create a bot with [@BotFather](https://t.me/BotFather), get your chat ID, and reference the credentials through environment variables — never as literals in the config file:

```toml
[notifications]
channels = ["macos", "telegram"]

[notifications.telegram]
enabled = true
bot_token_ref = "env:MAC_SENTINEL_TELEGRAM_BOT_TOKEN"
chat_id_ref = "env:MAC_SENTINEL_TELEGRAM_CHAT_ID"
```

```bash
export MAC_SENTINEL_TELEGRAM_BOT_TOKEN="..."
export MAC_SENTINEL_TELEGRAM_CHAT_ID="..."
```

Anti-spam behavior is built in: per-incident cooldowns, an hourly delivery cap, optional quiet hours, and recovery messages that are sent only for critical incidents by default. Every delivery or suppression is written to the local audit history, and delivery state is kept in `notification-state.json`.

Potentially disruptive actions exist but are disabled by default. When enabled in the config, the executor supports a single constrained action — `SIGTERM` for a user-approved process:

```bash
# 1. Stage a termination request against a process from an incident
mac-sentinel actions request INCIDENT_ID process.terminate --pid 4242

# 2. Review and confirm within the TTL window
mac-sentinel actions confirm ACT-20261125-165245-324561

# 3. Inspect the audit history
mac-sentinel actions list
```

Safety properties: protected names and system paths are refused, the PID is revalidated against its recorded identity before the signal (PID-reuse safe), confirmation expires after a short TTL, hourly request rate limits apply, and every step lands in the local audit log. Arbitrary shell commands, `sudo`, and autonomous termination are outside the action model.

See the [security model](docs/security-model.md) for details.

## Running as a background service

The monitor can run as a user-level macOS LaunchAgent:

```bash
mac-sentinel install-service
mac-sentinel service-status
mac-sentinel uninstall-service
```

The installer renders a plist at `~/Library/LaunchAgents/com.macos-resource-sentinel.plist`, creates the state directory, and loads the agent with `launchctl`. `MAC_SENTINEL_*` environment variables (such as Telegram credentials) are copied into the agent environment, so export them before installing. The agent restarts automatically at login and keeps running until uninstalled; stdout and stderr go to `monitor.stdout.log` and `monitor.stderr.log` in the state directory.

A generic plist template for reference is available at:

```text
launchd/com.macos-resource-sentinel.plist.template
```

Re-run `install-service` after upgrading the package so the plist points at the current executable.

## Project status

Architecture, alert behavior, event formats, security boundaries, configuration, and installation are documented. Milestone 1 added the Python package, configuration validation, `doctor`, and `collect --once`. Milestone 2 added the foreground monitor loop, rolling rules, incident state, cooldowns, macOS memory pressure, and JSONL history. Milestone 3 added stable notification formatting, native macOS and Telegram delivery, rate limits, quiet hours, and delivery auditing. Milestone 4 added the user-level LaunchAgent with `install-service`, `service-status`, and `uninstall-service`. Milestone 5 added incident inspection (`incidents list/show/bundle`), daily and weekly summaries, and the assistant integration contract. Milestone 6 adds the constrained action executor with request/confirmation, PID revalidation, protected-process policy, and a full audit trail.

Current milestone: **Milestone 6 — constrained actions**.

## Documentation

- [Architecture](docs/architecture.md) — components and data flow.
- [Alert rules](docs/alert-rules.md) — thresholds, lifecycle, grouping, and cooldowns.
- [Event schema](docs/event-schema.md) — incident and action records.
- [Security model](docs/security-model.md) — confirmation, allowlists, and audit policy.
- [Configuration](docs/configuration.md) — local setup and defaults.
- [Installation](docs/installation.md) — CLI and LaunchAgent plan.
- [Release process](docs/release.md) — SemVer, tags, and GitHub releases.
- [Assistant integration](docs/assistant.md) — how an assistant reads incidents and what it may do.
- [Roadmap](docs/roadmap.md) — implementation milestones.
- [Changelog](CHANGELOG.md) — notable changes by version.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, commit style,
testing expectations, and safety rules. Security reports are described in
[SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
