# Security model

## Core rule

Monitoring can be automatic. Potentially disruptive action cannot.

The daemon may collect metrics and notify without asking every time. A process action requires a bounded, explicit confirmation and must be validated again at execution time.

## Trust boundaries

### Operating system

The collector trusts operating-system metrics enough to report them, but not enough to treat a process name as a unique identity.

Process validation includes:

- PID;
- process name;
- executable path when available;
- owner;
- start time;
- parent PID when available.

### Assistant

An assistant is an untrusted advisor with access only to selected CLI output.

It may:

- inspect an incident;
- request a constrained action;
- explain a result.

It may not:

- execute arbitrary shell commands;
- read secrets;
- bypass confirmation;
- change protected-process rules at runtime;
- mark its own recommendation as user approval.

### Notification channel

A notification channel is not treated as a secure command interface by default.

The first version uses the assistant conversation or local CLI for approval. A notification can contain an incident ID, but receiving a message alone does not authorize action.

### Local executor

The executor is trusted to perform only operations compiled into its command set. It does not evaluate arbitrary command strings.

## MVP action policy

Allowed:

- `incident.inspect`;
- `process.terminate` using `SIGTERM`;
- `process.verify-exit`.

Not allowed:

- `SIGKILL`;
- `sudo`;
- arbitrary shell;
- file deletion;
- package removal;
- service modification;
- system settings changes;
- termination of another user's process.

Future operations require a new explicit capability and documentation.

## Protected targets

A target is protected when any condition is true:

- PID is 0 or 1;
- owner is not the current user;
- process is the daemon itself;
- process belongs to the configured assistant runtime;
- executable path is in a protected system location;
- process name matches the protected list;
- parent chain identifies a login, security, or window-management process;
- PID/start-time validation fails.

The protected list in configuration adds to the built-in list. Configuration cannot remove built-in protections.

## Confirmation flow

1. An incident is opened and assigned an incident ID.
2. The user or assistant requests an allowed action.
3. The executor snapshots target identity and creates an action request.
4. The request receives a short expiry time.
5. The user confirms the exact action ID.
6. The executor revalidates the target.
7. The action executes.
8. The result and verification are appended to the audit log.

Example:

```text
act_01JEXAMPLE
process.terminate
target: example-process, pid 1234
method: SIGTERM
expires: 120 seconds
```

The confirmation must include the action ID. A generic message such as “yes” is not enough.

## PID reuse protection

A PID alone is insufficient. Before execution, the executor compares the original target snapshot with the current process:

- PID matches;
- start time matches within a strict tolerance;
- executable identity matches;
- owner matches;
- process has not exited and been replaced.

Any mismatch fails closed with `target_changed`.

## Signal policy

The MVP supports only `SIGTERM`.

`SIGKILL` is intentionally excluded because it prevents cleanup and can cause data loss. If it is added later, it must be a separate action type with a separate confirmation and stronger warnings.

## Secrets

Secrets must not be stored in the public repository.

Allowed local sources:

- environment variable;
- macOS Keychain reference;
- user-only configuration with restrictive permissions.

A public config may contain only a reference:

```toml
[notifications.telegram]
enabled = true
bot_token_ref = "env:MAC_SENTINEL_TELEGRAM_BOT_TOKEN"
chat_id_ref = "env:MAC_SENTINEL_TELEGRAM_CHAT_ID"
```

The notifier must redact secrets from logs and exception messages.

## File permissions

Recommended permissions:

- config file: `0600`;
- state directory: `0700`;
- action audit log: `0600`;
- LaunchAgent plist: `0644` in the user's LaunchAgents directory.

The installer should warn rather than silently continue with unsafe permissions.

## Audit requirements

Every action request and result records:

- action ID;
- incident ID;
- action type;
- target snapshot;
- requesting component;
- confirmation status;
- result;
- timestamp;
- failure reason when applicable.

Audit records do not contain bot tokens or full command-line arguments unless explicitly classified as safe.

## Rate limits

The executor has independent rate limits from the notifier.

Suggested defaults:

- no more than three process termination requests per hour;
- no more than one action against the same process identity per incident;
- confirmation expiry of 120 seconds;
- no automatic retry after a terminated process disappears.

## Supply-chain controls

For an open-source implementation:

- pin direct dependencies;
- run tests in CI;
- scan for secrets before release;
- use conventional commits where practical;
- publish releases from tags;
- document macOS permissions required by each feature.

## Failure policy

The executor fails closed.

It must reject an action when:

- confirmation is expired;
- the target changed;
- the target is protected;
- the user does not own the target;
- the incident ID is unknown;
- the action type is not enabled;
- audit logging is unavailable.

A notification failure must not cause the daemon to repeatedly execute an action.

## Public sharing checklist

Before publishing logs or examples:

- remove bot tokens and chat IDs;
- remove real hostnames;
- replace usernames and home-directory paths;
- review process and document names;
- remove command-line arguments;
- verify that git history does not contain an earlier leaked value.
