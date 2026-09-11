# Changelog

All notable changes to `hermes-codex-multi-account` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.5] - 2026-09-11

### Changed
- Read the displayed account with `pool.peek()` so periodic Desktop status refreshes do not advance request counters or rotate account priority; retain `pool.select()` only as a compatibility fallback for older Hermes releases without `peek()`.
- Report the active Hermes credential-pool strategy and warn after reprioritization when a non-`fill_first` strategy does not guarantee the selected account will be used next.
- Replace the raw `unknown_account` code with a clear current-Profile reprioritization message in the Desktop UI.

## [1.0.4] - 2026-09-11

Version `1.0.3` was an unpublished local iteration; its changes are consolidated into this release candidate.

### Added
- Bound the Desktop account menu to the visible viewport and allow vertical scrolling when many accounts are configured.
- Collapse duplicate display rows only when they share a verified email claim and plan; preserve fallback labels, unknown identities, and different plan variants as separate credentials.
- Add regression tests for responsive menu bounds, long account labels, duplicate display rows, and release-version consistency.

### Changed
- Support both known Hermes Codex usage URL resolver APIs: `_resolve_codex_usage_url(...)` in the v0.20.x line and `_codex_backend_urls(...)` in the v0.21.x line.
- Send the optional `ChatGPT-Account-Id` request header when that claim is present in the local OAuth token, matching current Hermes behavior for account-scoped Codex endpoints.

### Fixed
- Prevent long account labels from expanding the Desktop composer status strip.
- Restore quota queries on Hermes v0.21.x after the internal usage URL resolver changed.

## [1.0.2] - 2026-08-31

### Added
- Recognize OpenAI's `go` plan claim and display it as ChatGPT Go.
- Classify 5-hour, weekly, and monthly quotas from the upstream `limit_window_seconds` value instead of assuming the period from the plan name.

### Fixed
- Mark revoked or expired Codex OAuth tokens as requiring re-authorization, rather than presenting a misleading empty quota row.
- Support both five-hour/weekly and monthly Go quota rollouts according to the window durations returned by OpenAI.

## [1.0.1] - 2026-08-31

### Fixed
- Render Free-plan primary quota windows as monthly instead of incorrectly labeling them as 5-hour sessions.
- Keep Pro on its weekly-only display while preserving 5-hour and weekly windows for Plus and Business plans.
- Replace ambiguous missing-quota copy such as “Unavailable” / “暂不可用” with neutral “No quota data” / “暂无额度信息” messaging.
- Include the date in monthly reset timestamps.

## [1.0.0] - 2026-08-19

### Added
- **Multi-Account Quota Status Backend Plugin**:
  - Registered CLI command `codex-quota-status` with `--json` and `--select-id` flags.
  - Safe JWT payload parsing for plan types and email identifiers without exposing raw access tokens.
  - Normalized plan labeling (e.g., mapping `prolite` to Pro, `business` to Business).
  - Parallel background usage polling using thread pools with per-account error isolation.
- **Desktop UI Status Bar & Menu Dropdown**:
  - Integrated status bar indicator showing current primary account quota.
  - Interactive dropdown menu to view all pooled Codex accounts, live session/weekly usage, cooldown states, and priority toggles.
  - Native bilingual support (English and Chinese `zh-CN`) via Hermes Desktop plugin i18n API and reactive fallbacks.
- **Transactional Installer (`scripts/install.py`)**:
  - Hermetic preflight checks for `hermes` CLI and environment sanity.
  - Timestamped backup directory creation before file copy.
  - Automatic atomic rollback upon failure during installation, plugin enablement, or doctor diagnostics.
  - Manual uninstallation and backup restoration procedures documented in the README; the installer does not provide `--uninstall` or `--restore` flags.
- **Comprehensive Verifier (`scripts/verify.py`)**:
  - Distinguishes between `missing`, `malformed`, and `valid` `auth.json` configurations.
  - Configurable minimum accounts threshold (default `--min-accounts 2`).
  - Strict privacy protections: never exposes or logs tokens or full secrets.
- **Public Privacy & Leak Gatekeeper (`scripts/scan_public.py`)**:
  - Enforces repository-level hygiene against accidental check-in of personal paths, real emails, or live token strings.
- **Multi-Platform CI Matrix**:
  - Automated testing on Ubuntu Linux, Windows, and macOS with Python 3.11 and Node.js 22.
