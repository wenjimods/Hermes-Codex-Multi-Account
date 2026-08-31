# Changelog

All notable changes to `hermes-codex-multi-account` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
