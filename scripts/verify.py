#!/usr/bin/env python3
"""Token-safe local installation and pool verification."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = "codex-quota-status"

def default_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]).expanduser()
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes"
    return Path.home() / ".hermes"

def check_auth_status(auth_path: Path) -> tuple[str, int, int, str | None]:
    """Check auth.json status without exposing secrets/emails/tokens.

    Returns:
        (status, account_count, healthy_count, error_detail)
        status is one of: "missing", "malformed", "valid"
    """
    if not auth_path.is_file():
        return "missing", 0, 0, None

    try:
        raw = auth_path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return "malformed", 0, 0, "Root JSON is not an object"

        pool = data.get("credential_pool")
        if pool is not None and not isinstance(pool, dict):
            return "malformed", 0, 0, "credential_pool is not an object"

        rows = (pool or {}).get("openai-codex", [])
        if not isinstance(rows, list):
            return "malformed", 0, 0, "openai-codex pool is not a list"

        accounts = 0
        healthy = 0
        for row in rows:
            if not isinstance(row, dict):
                return "malformed", 0, 0, "Account entry in openai-codex pool is not an object"
            accounts += 1
            if row.get("last_status") not in {"dead", "exhausted"}:
                healthy += 1

        return "valid", accounts, healthy, None
    except Exception as e:
        return "malformed", 0, 0, f"JSON parse error: {type(e).__name__}"

def verify_installation(
    hermes_home: Path,
    min_accounts: int = 2,
    skip_doctor: bool = False
) -> tuple[int, dict]:
    home = hermes_home.expanduser().resolve()
    backend = home / "plugins" / PLUGIN / "__init__.py"
    desktop = home / "desktop-plugins" / PLUGIN / "plugin.js"

    auth_path = home / "auth.json"
    auth_status, accounts, healthy, auth_err = check_auth_status(auth_path)

    report = {
        "hermes_home": str(home),
        "backend_installed": backend.is_file(),
        "desktop_installed": desktop.is_file(),
        "auth_status": auth_status,
        "codex_account_count": accounts,
        "healthy_or_untried_count": healthy,
        "min_accounts_required": min_accounts,
    }
    if auth_err:
        report["auth_error"] = auth_err

    # Check installation files
    if not backend.is_file() or not desktop.is_file():
        report["error"] = "Plugin files not installed properly"
        return 2, report

    # Check auth malformed
    if auth_status == "malformed":
        report["error"] = f"auth.json is malformed ({auth_err})"
        return 3, report

    # Check minimum accounts
    if min_accounts > 0:
        if auth_status == "missing":
            report["error"] = f"auth.json missing, cannot satisfy min-accounts={min_accounts}"
            return 4, report
        if accounts < min_accounts:
            report["error"] = f"Found {accounts} accounts, fewer than required min-accounts={min_accounts}"
            return 4, report

    # Run hermes doctor if requested
    if not skip_doctor and shutil.which("hermes"):
        doctor_res = subprocess.run(
            ["hermes", "plugins", "doctor", PLUGIN],
            check=False,
            env={**os.environ, "HERMES_HOME": str(home)},
        )
        report["doctor_exit_code"] = doctor_res.returncode
        if doctor_res.returncode != 0:
            report["error"] = f"hermes plugins doctor failed with exit code {doctor_res.returncode}"
            return doctor_res.returncode, report

    return 0, report

def main() -> int:
    ap = argparse.ArgumentParser(description="Verify Hermes Codex Multi-Account installation.")
    ap.add_argument("--hermes-home", type=Path, default=default_home())
    ap.add_argument("--min-accounts", type=int, default=2, help="Minimum number of Codex accounts required (default: 2)")
    ap.add_argument("--skip-doctor", action="store_true", help="Skip running 'hermes plugins doctor'")
    ap.add_argument("--json", action="store_true", help="Output report in JSON format (default behavior)")
    args = ap.parse_args()

    exit_code, report = verify_installation(
        hermes_home=args.hermes_home,
        min_accounts=args.min_accounts,
        skip_doctor=args.skip_doctor
    )
    print(json.dumps(report, indent=2))
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
