# Hermes Codex Multi-Account

[![CI](https://github.com/wenjimods/Hermes-Codex-Multi-Account/actions/workflows/ci.yml/badge.svg)](https://github.com/wenjimods/Hermes-Codex-Multi-Account/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An unofficial plugin for **Hermes Agent** and **Hermes Desktop** that adds default OpenAI Codex OAuth account selection and real-time quota visibility across multiple pooled accounts.

> **DISCLAIMER**: This repository is a community-developed, **unofficial** third-party extension. It is not affiliated with, maintained by, or endorsed by the official Hermes Agent project or OpenAI.

---

## Verified Baseline & Compatibility

- **Hermes Agent Baseline**: `v0.20.5 (2026.8.19)`, upstream `7eee066c`, local `4a19dfa7 (+2 carried commits)`
- **Locally verified**: Windows 11, Python 3.11.15, Node.js 22
- **CI targets**: Windows, Ubuntu Linux, and macOS on Python 3.11 / Node.js 22

For technical details on integration and upstream API dependency analysis, refer to [COMPATIBILITY.md](COMPATIBILITY.md).

---

## V1 Scope & Architectural Boundaries

To preserve stability and compatibility across all platforms:
- **Default Account Only**: Selecting an account reorganizes priority in `auth.json` so that **newly initiated conversations** use the chosen default account.
- **No Per-Session Binding**: This plugin does **not** permanently lock or bind existing sessions to specific account IDs and does **not** rely on ephemeral `session.credential.select` APIs.
- **Strict Privacy**: Access tokens, refresh tokens, and credentials are never transmitted to the Desktop UI or logged. The backend parses only public JWT claims (such as email labels and plan tier) and communicates using opaque credential IDs.

---

## Internal API Dependencies & Risks

This extension interfaces with internal, non-public Hermes Agent modules (`agent.credential_pool`, `hermes_cli.auth`, and `agent.account_usage`). Upstream changes to `hermes-agent` could alter internal signatures. The plugin employs strict exception isolation and fallback payloads to prevent crashes in the desktop client.

---

## Features

- **Transactional Installation**: Auto-discovers Hermes directories, validates preflight requirements, creates timestamped backups, and automatically rolls back changes if installation or verification fails.
- **Status Bar & Dropdown Menu**: View remaining 5-hour / weekly quota percentages and reset countdowns directly in Hermes Desktop.
- **One-Click Default Switching**: Switch active priority to another healthy Codex account.
- **Bilingual Interface**: Native English and Chinese (`zh-CN`) support using Hermes Desktop i18n APIs with responsive fallbacks.
- **Cooldown & Exhaustion Awareness**: Transparently marks cooling-down or dead accounts as unselectable until quotas reset.

---

## Installation

### Prerequisites
1. Hermes Agent installed and configured on your system.
2. Authenticate at least two Codex accounts using the standard official flow:
   ```bash
   hermes auth add openai-codex
   ```

### Quick Install
Run the transactional installer from this repository:

```bash
# Standard installation
python scripts/install.py

# Skip automatic CLI enable if configuring manually
python scripts/install.py --skip-enable

# Dry-run mode to inspect target paths without writing files
python scripts/install.py --dry-run
```

The installer will:
1. Validate system prerequisites (`hermes` command and directory permissions).
2. Create a timestamped backup in `<HERMES_HOME>/backups/` if previous versions exist.
3. Install backend plugin to `<HERMES_HOME>/plugins/codex-quota-status`.
4. Install desktop plugin to `<HERMES_HOME>/desktop-plugins/codex-quota-status`.
5. Run `hermes plugins enable codex-quota-status` and `hermes plugins doctor codex-quota-status`. If either fails, changes are automatically reverted.

---

## Verification

After installation, verify that the plugin is properly recognized and that accounts are configured:

```bash
# Verify default setup (requires at least 2 pooled accounts by default)
python scripts/verify.py

# Allow single-account verification
python scripts/verify.py --min-accounts 1

# Output verification report in JSON format
python scripts/verify.py --json
```

---

## Backup, Restoration & Uninstallation

### Restoring from Backup
The installer keeps previous plugin directories under `<HERMES_HOME>/backups/codex-quota-status-<timestamp>/`. Disable the plugin, then copy the saved `backend/codex-quota-status` and `desktop/codex-quota-status` directories back to their corresponding plugin folders.

### Uninstallation
Disable the plugin first:
```bash
hermes plugins disable codex-quota-status
```
Then remove `codex-quota-status` from `<HERMES_HOME>/plugins/` and `<HERMES_HOME>/desktop-plugins/` using your file manager.

---

## Security & Privacy Gate

We take credential privacy strictly:
- No tokens or personal identifiers are stored in this repository.
- Run `python scripts/scan_public.py` to scan the repository for accidental personal data leaks, real email addresses, or token formats before publishing.
- See [SECURITY.md](SECURITY.md) for vulnerability reporting guidelines.

---

## License

This project is licensed under the [MIT License](LICENSE).
