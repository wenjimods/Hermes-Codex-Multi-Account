#!/usr/bin/env python3
"""Public leak scanner for Hermes Codex Multi-Account repository.

Scans tracked and untracked publishable files plus reachable Git authors for:
- Absolute personal filesystem paths (for example, OS user-home directories)
- Real user email addresses (allowing standard placeholders like user@example.com)
- Tokens, secrets, private keys, or API credentials
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Safe placeholder emails allowed in code/docs/tests
ALLOWED_EMAILS = {
    "user@example.com",
    "user-a@example.com",
    "user-b@example.com",
    "user-c@example.com",
    "account-a@example.com",
    "account-b@example.com",
    "test@example.com",
    "admin@example.com",
    "someone@example.com",
    "user1@example.com",
    "user2@example.com",
}

# Regex patterns
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Dangerous absolute user-home paths are rejected.
# Allow RUNNER_TEMP, generic placeholders, etc.
RE_WIN_USER_PATH = re.compile(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\(?!(?:Public|Default|Default User|All Users)(?:[\\]|$))([A-Za-z0-9_.-]+)", re.IGNORECASE)
RE_UNIX_USER_PATH = re.compile(r"/(?:home|Users)/(?!(?:runner|runneradmin|node|github|workspace)(?:[/]|$))([A-Za-z0-9_.-]+)", re.IGNORECASE)

# Credential patterns
RE_JWT_SECRET = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
RE_OPENAI_KEY = re.compile(r"\bsk-(?:live|test|proj)?[A-Za-z0-9_-]{20,}\b")
RE_GENERIC_SECRET_KV = re.compile(r"""(?i)(?:bearer\s+|access_token\s*[:=]\s*['"]|refresh_token\s*[:=]\s*['"]|api_key\s*[:=]\s*['"])([^'"\s\r\n]{16,})""")

def get_tracked_files(repo_root: Path) -> list[Path]:
    try:
        res = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True
        )
        files = [repo_root / line.strip() for line in res.stdout.splitlines() if line.strip()]
        return [f for f in files if f.is_file()]
    except Exception:
        # Fallback to walk if git not present
        files = []
        for root, dirs, filenames in os.walk(repo_root):
            if ".git" in dirs:
                dirs.remove(".git")
            for filename in filenames:
                files.append(Path(root) / filename)
        return files

def scan_file(path: Path) -> list[str]:
    issues = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [f"Could not read {path}: {e}"]

    # 1. Emails
    for match in RE_EMAIL.finditer(content):
        email = match.group(0).lower()
        if email.endswith("@example.com") or email.endswith("@example.org") or email.endswith("@example.net"):
            continue
        if email in ALLOWED_EMAILS:
            continue
        issues.append(f"Potential real email detected: {match.group(0)}")

    # 2. Personal paths
    for match in RE_WIN_USER_PATH.finditer(content):
        issues.append(f"Windows personal user path detected: {match.group(0)}")
    for match in RE_UNIX_USER_PATH.finditer(content):
        issues.append(f"Unix personal user path detected: {match.group(0)}")

    # 3. Tokens & Secrets
    for match in RE_JWT_SECRET.finditer(content):
        issues.append(f"Potential raw JWT token detected: {match.group(0)[:15]}...")
    for match in RE_OPENAI_KEY.finditer(content):
        issues.append(f"Potential API secret key detected: {match.group(0)[:10]}...")
    for match in RE_GENERIC_SECRET_KV.finditer(content):
        val = match.group(1)
        # Ignore mock/dummy test values
        if "mock" in val.lower() or "dummy" in val.lower() or "example" in val.lower():
            continue
        issues.append(f"Potential generic secret value detected: {match.group(0)[:20]}...")

    return issues

def scan_git_authors(repo_root: Path) -> list[str]:
    """Reject personal author emails in reachable history; GitHub noreply is safe."""
    try:
        res = subprocess.run(
            ["git", "log", "--all", "--format=%an <%ae>%n%cn <%ce>"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        return [f"Could not inspect Git authors: {type(exc).__name__}"]
    issues = []
    for match in RE_EMAIL.finditer(res.stdout):
        email = match.group(0).lower()
        if email.endswith("@users.noreply.github.com"):
            continue
        issues.append(f"Reachable Git history contains non-noreply author email: {match.group(0)}")
    return sorted(set(issues))

def main() -> int:
    parser = argparse.ArgumentParser(description="Scan repository for personal leaks and secrets")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    files = get_tracked_files(repo_root)

    total_issues = 0
    for file_path in sorted(files):
        rel_path = file_path.relative_to(repo_root)
        issues = scan_file(file_path)
        if issues:
            for issue in issues:
                print(f"[LEAK DETECTED] {rel_path}: {issue}", file=sys.stderr)
                total_issues += 1

    for issue in scan_git_authors(repo_root):
        print(f"[LEAK DETECTED] .git history: {issue}", file=sys.stderr)
        total_issues += 1

    if total_issues == 0:
        print(f"[OK] Leak scan clean: checked {len(files)} files, no personal leaks or secrets found.")
        return 0
    else:
        print(f"[FAIL] Found {total_issues} potential leaks/secrets!", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
