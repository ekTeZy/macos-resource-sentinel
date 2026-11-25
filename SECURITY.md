# Security policy

## Supported versions

Security fixes are applied to the latest minor release.

| Version | Supported |
|---|---:|
| 0.2.x | yes |
| 0.1.x | no |

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting for this repository if it is
available. Otherwise, open a minimal public issue asking for a private contact
and do not include exploit details, tokens, personal paths, process history, or
other sensitive data.

## Sensitive information

Never include the following in issues, pull requests, logs, or screenshots:

- bot tokens or API keys;
- Telegram chat IDs;
- private hostnames;
- real usernames or home-directory paths;
- command-line arguments from local processes;
- incident history containing personal context.

## Security model highlights

- Monitoring is read-only.
- Actions are disabled by default.
- Potentially disruptive actions require explicit confirmation.
- The executor does not accept arbitrary shell commands.
- Built-in protected processes cannot be removed through configuration.
- Action requests and results are audit logged.

See [docs/security-model.md](docs/security-model.md) for the full model.
