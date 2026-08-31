"""Codex account quota status and safe manual account selection."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

MARKER = "HERMES_CODEX_QUOTA_JSON "
PROVIDER = "openai-codex"
PROFILE_CLAIM = "https://api.openai.com/profile"
AUTH_CLAIM = "https://api.openai.com/auth"
PLAN_NAMES = {
    "plus": "Plus",
    "prolite": "Pro",
    "pro_lite": "Pro",
    "pro": "Pro",
    "team": "Business",
    "business": "Business",
}


def normalize_plan(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Unknown"
    return PLAN_NAMES.get(raw.lower(), raw.replace("_", " ").replace("-", " ").title())


def _format_reset(value: datetime | None, *, long_term: bool = False) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime("%m/%d %H:%M" if long_term else "%H:%M")


def _claims(entry: Any) -> dict[str, Any]:
    from agent.credential_pool import _decode_jwt_claims

    token = str(getattr(entry, "runtime_api_key", "") or getattr(entry, "access_token", "") or "")
    claims = _decode_jwt_claims(token)
    return claims if isinstance(claims, dict) else {}


def _email(entry: Any) -> str:
    claims = _claims(entry)
    profile = claims.get(PROFILE_CLAIM)
    if isinstance(profile, dict):
        value = profile.get("email")
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("email", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(getattr(entry, "label", "") or "Codex").strip()


def _entry_plan(entry: Any) -> str:
    auth = _claims(entry).get(AUTH_CLAIM)
    value = auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None
    return normalize_plan(value)


def _cooldown_until(entry: Any) -> float | None:
    from agent.credential_pool import STATUS_EXHAUSTED, _exhausted_until

    if getattr(entry, "last_status", None) != STATUS_EXHAUSTED:
        return None
    try:
        until = _exhausted_until(entry, sole_credential=False)
    except TypeError:
        # Older released Hermes builds expose the same helper without the
        # sole_credential keyword. Keep the plugin compatible with both APIs.
        until = _exhausted_until(entry)
    return float(until) if until is not None and until > time.time() else None


def account_row(entry: Any, current_id: str | None) -> dict[str, Any]:
    from agent.credential_pool import STATUS_DEAD

    cooldown = _cooldown_until(entry)
    dead = getattr(entry, "last_status", None) == STATUS_DEAD
    status = "dead" if dead else ("cooldown" if cooldown else "ok")
    email = _email(entry)
    return {
        "id": str(entry.id),
        "email": email,
        "display": email,
        "plan": _entry_plan(entry),
        "status": status,
        "cooldown": cooldown,
        "current": str(entry.id) == current_id,
        "priority": int(entry.priority),
        "selectable": not dead and cooldown is None,
        "session": {"remaining": None, "reset": None},
        "weekly": {"remaining": None, "reset": None},
        "monthly": {"remaining": None, "reset": None},
    }


def set_priority(provider: str, opaque_id: str) -> tuple[bool, str]:
    """Atomically change only priority fields in the active auth store."""
    from agent.credential_pool import PooledCredential
    from hermes_cli.auth import _auth_store_lock, _load_auth_store, _save_auth_store

    with _auth_store_lock():
        store = _load_auth_store()
        pools = store.get("credential_pool")
        raw_entries = pools.get(provider) if isinstance(pools, dict) else None
        if not isinstance(raw_entries, list) or not raw_entries:
            return False, "no_accounts"
        chosen_index = next(
            (idx for idx, raw in enumerate(raw_entries) if isinstance(raw, dict) and str(raw.get("id")) == opaque_id),
            None,
        )
        if chosen_index is None:
            return False, "unknown_account"
        chosen_entry = PooledCredential.from_dict(provider, raw_entries[chosen_index])
        row = account_row(chosen_entry, None)
        if not row["selectable"]:
            return False, row["status"]

        ordered = [raw_entries[chosen_index]] + [
            raw for idx, raw in enumerate(raw_entries) if idx != chosen_index
        ]
        for priority, raw in enumerate(ordered):
            if isinstance(raw, dict):
                raw["priority"] = priority
        pools[provider] = ordered
        _save_auth_store(store)
    return True, "ok"


def normalize_usage_windows(
    fallback_plan: str,
    snapshot: Any,
) -> tuple[str, dict[str, dict[str, int | str | None]]]:
    """Map generic Codex API windows onto plan-specific display periods."""
    windows = {window.label.lower(): window for window in snapshot.windows}
    plan = normalize_plan(snapshot.plan or fallback_plan)
    session = windows.get("session")
    weekly = windows.get("weekly")
    monthly = windows.get("monthly")

    # The shared Hermes parser labels the API primary window "session" even
    # when its actual period is plan-specific. Pro's sole primary window is
    # weekly; Free's sole primary window is monthly.
    if plan == "Pro" and weekly is None:
        weekly, session = session, None
    elif plan == "Free":
        monthly, session, weekly = monthly or session, None, None

    def quota(window: Any, *, long_term: bool = False) -> dict[str, int | str | None]:
        used = getattr(window, "used_percent", None) if window is not None else None
        remaining = None if used is None else max(0, min(100, round(100 - float(used))))
        reset_at = getattr(window, "reset_at", None) if window is not None else None
        return {
            "remaining": remaining,
            "reset": _format_reset(reset_at, long_term=long_term),
        }

    return plan, {
        "session": quota(session),
        "weekly": quota(weekly, long_term=True),
        "monthly": quota(monthly, long_term=True),
    }


def build_snapshot() -> dict[str, Any]:
    from agent.credential_pool import load_pool

    pool = load_pool(PROVIDER)
    entries = pool.entries()
    selected = pool.select()
    current_id = str(selected.id) if selected is not None else None
    rows = [account_row(entry, current_id) for entry in entries]
    payload: dict[str, Any] = {
        "available": bool(entries),
        "provider": PROVIDER,
        "accounts": rows,
        "credential": None,
        "plan": "Unknown",
        "session": {"remaining": None, "reset": None},
        "weekly": {"remaining": None, "reset": None},
        "monthly": {"remaining": None, "reset": None},
    }
    if selected is None:
        payload["reason"] = "no_available_credential"
        return payload

    email = _email(selected)
    payload["credential"] = {"id": str(selected.id), "email": email, "display": email}
    payload["plan"] = _entry_plan(selected)

    def fetch(entry: Any) -> tuple[str, Any, str | None]:
        if _cooldown_until(entry) or getattr(entry, "last_status", None) == "dead":
            return str(entry.id), None, "skipped"
        try:
            from agent.account_usage import _fetch_codex_account_usage
            return str(entry.id), _fetch_codex_account_usage(
                base_url=entry.runtime_base_url, api_key=entry.runtime_api_key), None
        except Exception as exc:
            return str(entry.id), None, type(exc).__name__

    def apply_usage(row: dict[str, Any], snapshot: Any) -> None:
        row["plan"], quotas = normalize_usage_windows(row["plan"], snapshot)
        row.update(quotas)
        row["fetched_at"] = snapshot.fetched_at.astimezone().isoformat(timespec="seconds")

    row_by_id = {row["id"]: row for row in rows}
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(entries)))) as executor:
        futures = [executor.submit(fetch, entry) for entry in entries]
        for future in as_completed(futures):
            account_id, snapshot, error = future.result()
            if snapshot is not None:
                apply_usage(row_by_id[account_id], snapshot)
            elif error and error != "skipped":
                row_by_id[account_id]["usage_error"] = error
    current_row = row_by_id.get(current_id)
    if current_row:
        payload["plan"] = current_row["plan"]
        payload["session"] = current_row["session"]
        payload["weekly"] = current_row["weekly"]
        payload["monthly"] = current_row["monthly"]
    return payload


def _emit(payload: dict[str, Any]) -> None:
    print(MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def quota_status_command(args: Any = None) -> int:
    selected_id = str(getattr(args, "select_id", None) or "").strip()
    if selected_id:
        ok, reason = set_priority(PROVIDER, selected_id)
        if not ok:
            _emit({"available": False, "provider": PROVIDER, "reason": reason})
            return 1
        # Selection is deliberately a fast path: the UI already has the
        # account metadata and will refresh the full quota snapshot once in
        # the background after this marker is received.
        _emit({"ok": True, "provider": PROVIDER, "selected_id": selected_id})
        return 0
    try:
        payload = build_snapshot()
    except Exception as exc:
        payload = {
            "available": False,
            "provider": PROVIDER,
            "accounts": [],
            "reason": "query_failed",
            "error_type": type(exc).__name__,
        }
    _emit(payload)
    return 0


def setup_cli(parser: Any) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable account status")
    parser.add_argument("--select-id", help="Prioritize one opaque account id")
    parser.set_defaults(func=quota_status_command)


def register(ctx: Any) -> None:
    ctx.register_cli_command(
        name="codex-quota-status",
        help="Show or select a Codex account",
        setup_fn=setup_cli,
        handler_fn=quota_status_command,
        description="Safe Codex account selector and quota status for Hermes Desktop.",
    )
