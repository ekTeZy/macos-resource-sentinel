# Installation plan

## Target installation model

The project is installed as a user-level Python CLI and runs through a macOS LaunchAgent.

The MVP does not require a system daemon or `sudo`.

## Planned commands

```bash
mac-sentinel --version
mac-sentinel doctor
mac-sentinel collect --once
mac-sentinel monitor
mac-sentinel incidents list
mac-sentinel incidents show INCIDENT_ID
mac-sentinel actions request INCIDENT_ID terminate-process
mac-sentinel actions confirm ACTION_ID
mac-sentinel install-service
mac-sentinel uninstall-service
```

## User-level CLI setup

Python 3.11 or newer is required. `pipx` keeps the command available globally
without mixing project dependencies into the system Python environment:

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/ektezy/macos-resource-sentinel.git
mac-sentinel --version
mac-sentinel doctor
mac-sentinel collect --once --pretty
mac-sentinel monitor --max-samples 1
```

For a local checkout:

```bash
cd /path/to/macos-resource-sentinel
pipx install . --force
```

Upgrade after pulling changes:

```bash
pipx reinstall macos-resource-sentinel
```

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

For a checkout without installing the console script:

```bash
PYTHONPATH=src python3 -m macos_resource_sentinel doctor
PYTHONPATH=src python3 -m macos_resource_sentinel collect --once --pretty
PYTHONPATH=src python3 -m pytest -q
```

## Package layout

The implementation uses a `src` layout:

```text
src/macos_resource_sentinel/
```

The console script name is:

```text
mac-sentinel
```

## Local directories

Configuration:

```text
~/.config/macos-resource-sentinel/config.toml
```

State:

```text
~/.local/state/macos-resource-sentinel/
```

LaunchAgent:

```text
~/Library/LaunchAgents/
```

Log output should be available through both:

- `mac-sentinel logs`;
- the local state directory.

## LaunchAgent policy

The installer should render a plist from a generic template.

User-specific values are resolved locally:

- current executable path;
- current config path;
- current state directory;
- label based on the project name;
- standard output and error paths.

A generated plist with local paths is runtime state and must not be committed.

## First-run flow

```bash
# 1. Inspect the environment
mac-sentinel doctor

# 2. Copy the public example
mkdir -p ~/.config/macos-resource-sentinel
cp config/example.toml ~/.config/macos-resource-sentinel/config.toml
chmod 600 ~/.config/macos-resource-sentinel/config.toml

# 3. Verify one collection cycle
mac-sentinel collect --once

# 4. Run in the foreground
mac-sentinel monitor

# 5. Install the LaunchAgent after the foreground run is healthy
mac-sentinel install-service
```

## Upgrade flow

```bash
mac-sentinel doctor
mac-sentinel monitor --validate-config
mac-sentinel install-service --replace
```

An upgrade must preserve:

- local configuration;
- incident history;
- action audit history;
- notification credentials.

## Uninstall flow

```bash
mac-sentinel uninstall-service
```

Uninstalling the service must not delete incident history by default. A separate explicit command may remove local state.

## Build and release policy

Planned release artifacts:

- source repository tag;
- Python source distribution;
- Python wheel;
- optionally a Homebrew formula after the CLI is stable.

Release automation should never require a personal bot token on a contributor machine.
