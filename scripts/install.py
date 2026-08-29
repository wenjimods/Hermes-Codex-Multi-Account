#!/usr/bin/env python3
"""Transactional installer for Hermes Codex Multi-Account plugin."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PLUGIN = "codex-quota-status"
REPO_ROOT = Path(__file__).resolve().parents[1]

def default_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]).expanduser()
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes"
    return Path.home() / ".hermes"

def check_hermes_cli() -> str | None:
    return shutil.which("hermes")

def backup_directory(src_dir: Path, backup_parent: Path) -> Path | None:
    if not src_dir.exists():
        return None
    backup_parent.mkdir(parents=True, exist_ok=True)
    target_bak = backup_parent / src_dir.name
    shutil.copytree(src_dir, target_bak)
    return target_bak

def restore_or_cleanup(
    backend_dst: Path,
    desktop_dst: Path,
    backend_bak: Path | None,
    desktop_bak: Path | None,
    backend_pre_existed: bool,
    desktop_pre_existed: bool
) -> None:
    print("[INSTALL] Transaction failed! Rolling back changes...", file=sys.stderr)

    # 1. Rollback backend
    if backend_dst.exists():
        shutil.rmtree(backend_dst, ignore_errors=True)
    if backend_pre_existed and backend_bak and backend_bak.exists():
        shutil.copytree(backend_bak, backend_dst)
        print(f"[INSTALL] Restored backend plugin from backup: {backend_dst}", file=sys.stderr)
    else:
        print(f"[INSTALL] Removed installed backend directory: {backend_dst}", file=sys.stderr)

    # 2. Rollback desktop
    if desktop_dst.exists():
        shutil.rmtree(desktop_dst, ignore_errors=True)
    if desktop_pre_existed and desktop_bak and desktop_bak.exists():
        shutil.copytree(desktop_bak, desktop_dst)
        print(f"[INSTALL] Restored desktop plugin from backup: {desktop_dst}", file=sys.stderr)
    else:
        print(f"[INSTALL] Removed installed desktop directory: {desktop_dst}", file=sys.stderr)

def copy_tree(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "node_modules")
    )

def install(
    hermes_home: Path,
    dry_run: bool = False,
    skip_enable: bool = False
) -> int:
    home = hermes_home.expanduser().resolve()
    backend_src = REPO_ROOT / "src" / "backend" / PLUGIN
    desktop_src = REPO_ROOT / "src" / "desktop" / PLUGIN
    backend_dst = home / "plugins" / PLUGIN
    desktop_dst = home / "desktop-plugins" / PLUGIN

    if not backend_src.is_dir() or not desktop_src.is_dir():
        print(f"[ERROR] Source plugin files missing in {REPO_ROOT}", file=sys.stderr)
        return 1

    # Pre-check hermes CLI if skip_enable is False
    if not skip_enable and not dry_run:
        hermes_bin = check_hermes_cli()
        if not hermes_bin:
            print(
                "[ERROR] 'hermes' command not found in PATH. "
                "Ensure hermes-agent is installed and on PATH, or pass --skip-enable.",
                file=sys.stderr
            )
            return 1

    print(f"Installing {PLUGIN} to {home} (dry_run={dry_run})")
    if dry_run:
        print(f"Would copy {backend_src} -> {backend_dst}")
        print(f"Would copy {desktop_src} -> {desktop_dst}")
        if not skip_enable:
            print("Would execute: hermes plugins enable codex-quota-status")
            print("Would execute: hermes plugins doctor codex-quota-status")
        return 0

    backup_root = home / "backups" / f"{PLUGIN}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backend_pre_existed = backend_dst.exists()
    desktop_pre_existed = desktop_dst.exists()
    backend_bak = None
    desktop_bak = None

    try:
        # Step 1: Backup existing
        if backend_pre_existed:
            backend_bak = backup_directory(backend_dst, backup_root / "backend")
            print(f"[INSTALL] Backed up existing backend to {backend_bak}")
        if desktop_pre_existed:
            desktop_bak = backup_directory(desktop_dst, backup_root / "desktop")
            print(f"[INSTALL] Backed up existing desktop to {desktop_bak}")

        # Step 2: Copy new plugin files
        copy_tree(backend_src, backend_dst)
        copy_tree(desktop_src, desktop_dst)
        print(f"[INSTALL] Copied backend files to {backend_dst}")
        print(f"[INSTALL] Copied desktop files to {desktop_dst}")

        # Step 3: Enable and doctor
        if not skip_enable:
            print("[INSTALL] Running: hermes plugins enable codex-quota-status")
            child_env = {**os.environ, "HERMES_HOME": str(home)}
            enable_res = subprocess.run([hermes_bin, "plugins", "enable", PLUGIN], check=False, env=child_env)
            if enable_res.returncode != 0:
                raise RuntimeError(f"'hermes plugins enable' failed with exit code {enable_res.returncode}")

            print("[INSTALL] Running: hermes plugins doctor codex-quota-status")
            doctor_res = subprocess.run([hermes_bin, "plugins", "doctor", PLUGIN], check=False, env=child_env)
            if doctor_res.returncode != 0:
                raise RuntimeError(f"'hermes plugins doctor' failed with exit code {doctor_res.returncode}")

    except Exception as e:
        print(f"[ERROR] Installation encountered an error: {e}", file=sys.stderr)
        if not backend_pre_existed and not skip_enable and hermes_bin:
            subprocess.run(
                [hermes_bin, "plugins", "disable", PLUGIN],
                check=False,
                env={**os.environ, "HERMES_HOME": str(home)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        restore_or_cleanup(
            backend_dst=backend_dst,
            desktop_dst=desktop_dst,
            backend_bak=backend_bak,
            desktop_bak=desktop_bak,
            backend_pre_existed=backend_pre_existed,
            desktop_pre_existed=desktop_pre_existed
        )
        return 1

    if backend_bak or desktop_bak:
        print(f"[INSTALL] Previous version retained at {backup_root}")
    print(f"[OK] Successfully installed {PLUGIN} to {home}")
    return 0

def main() -> int:
    ap = argparse.ArgumentParser(description="Install Hermes Codex Multi-Account plugin.")
    ap.add_argument("--hermes-home", type=Path, default=default_home())
    ap.add_argument("--dry-run", action="store_true", help="Show actions without modifying files")
    ap.add_argument("--skip-enable", action="store_true", help="Skip running hermes plugins enable and doctor")
    args = ap.parse_args()

    return install(
        hermes_home=args.hermes_home,
        dry_run=args.dry_run,
        skip_enable=args.skip_enable
    )

if __name__ == "__main__":
    sys.exit(main())
