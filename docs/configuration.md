# Configuration

## Files

The public example lives at:

```text
config/example.toml
```

A real local configuration should be copied to:

```text
~/.config/macos-resource-sentinel/config.toml
```

The local file is not committed and should use `0600` permissions.

## Precedence

Later sources override earlier ones:

1. built-in defaults;
2. `config/example.toml` values;
3. user config;
4. explicit CLI overrides.

A CLI override is intended for diagnostics and should not become the normal way of running the daemon.

## Secrets

Use references instead of literal values:

```toml
[notifications.telegram]
bot_token_ref = "env:MAC_SENTINEL_TELEGRAM_BOT_TOKEN"
chat_id_ref = "env:MAC_SENTINEL_TELEGRAM_CHAT_ID"
```

A keychain-backed reference can be added later without changing the schema:

```text
keychain:macos-resource-sentinel/telegram-bot-token
```

## Important defaults

### Sampling

```toml
[sampling]
interval_seconds = 5
startup_grace_seconds = 120
```

Five seconds is frequent enough to build useful evidence but still cheap for a local agent.

### Aggregate CPU

```toml
[rules.cpu]
trigger_percent = 85
recover_percent = 65
min_duration_seconds = 180
recovery_duration_seconds = 120
cooldown_minutes = 30
```

The gap between trigger and recovery thresholds prevents repeated open/close transitions around one value.

### Disk

```toml
[rules.disk]
warning_free_percent = 15
critical_free_percent = 8
warning_recovery_percent = 20
critical_recovery_percent = 12
paths = ["/"]
```

Additional volumes can be added, but network mounts should usually be handled separately from the system volume.

### Notifications

```toml
[notifications]
channels = ["macos"]
max_per_hour = 4
default_cooldown_minutes = 30
```

The first local setup can use native macOS notifications before any external channel is configured.

### Actions

Actions are disabled by default:

```toml
[actions]
enabled = false
require_confirmation = true
```

Enabling actions should be a deliberate local choice.

## Environment overrides

Suggested variables:

```text
MAC_SENTINEL_CONFIG
MAC_SENTINEL_STATE_DIR
MAC_SENTINEL_TELEGRAM_BOT_TOKEN
MAC_SENTINEL_TELEGRAM_CHAT_ID
```

Environment variables are convenient locally but should still be kept out of shell history and public screenshots.

## Validation

`mac-sentinel doctor` should validate:

- TOML syntax;
- unknown fields;
- impossible thresholds;
- missing notification credentials;
- unsafe file permissions;
- state directory creation;
- LaunchAgent status;
- Python version;
- permission to inspect process information.

Invalid local configuration must not silently fall back to a permissive action policy.
