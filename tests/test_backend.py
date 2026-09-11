import base64
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_INIT_PATH = REPO_ROOT / "src/backend/codex-quota-status/__init__.py"
INSTALLER_PATH = REPO_ROOT / "scripts/install.py"
VERIFIER_PATH = REPO_ROOT / "scripts/verify.py"

# Load backend module
backend_spec = spec_from_file_location("codex_quota_status_plugin", BACKEND_INIT_PATH)
assert backend_spec and backend_spec.loader
plugin = module_from_spec(backend_spec)
backend_spec.loader.exec_module(plugin)

# Load scripts
install_spec = spec_from_file_location("install_script", INSTALLER_PATH)
assert install_spec and install_spec.loader
installer = module_from_spec(install_spec)
install_spec.loader.exec_module(installer)

verify_spec = spec_from_file_location("verify_script", VERIFIER_PATH)
assert verify_spec and verify_spec.loader
verifier = module_from_spec(verify_spec)
verify_spec.loader.exec_module(verifier)


def make_token(email="user@example.com", plan="prolite"):
    payload = {
        plugin.PROFILE_CLAIM: {"email": email},
        plugin.AUTH_CLAIM: {"chatgpt_plan_type": plan}
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"x.{body}.x"


def make_entry(**overrides):
    values = dict(
        provider="openai-codex",
        id="opaque-a",
        label="GPT-A",
        priority=0,
        runtime_api_key=make_token(),
        access_token=make_token(),
        last_status=None,
        last_status_at=None,
        last_error_code=None,
        last_error_reason=None,
        last_error_message=None,
        last_error_reset_at=None,
        runtime_base_url="https://example.test"
    )
    values.update(overrides)
    return types.SimpleNamespace(**values)


# 1. Plan normalization
def test_plan_normalization():
    assert plugin.normalize_plan("prolite") == "Pro"
    assert plugin.normalize_plan("business") == "Business"
    assert plugin.normalize_plan("free") == "Free"
    assert plugin.normalize_plan("go") == "Go"
    assert plugin.normalize_plan("unknown_plan") == "Unknown Plan"


def make_usage_snapshot(plan, *, primary=25, secondary=50):
    windows = []
    if primary is not None:
        windows.append(types.SimpleNamespace(
            label="Session",
            used_percent=primary,
            reset_at=datetime(2026, 9, 30, 14, 0).astimezone(),
        ))
    if secondary is not None:
        windows.append(types.SimpleNamespace(
            label="Weekly",
            used_percent=secondary,
            reset_at=datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc),
        ))
    return types.SimpleNamespace(plan=plan, windows=tuple(windows))


def test_free_primary_window_is_monthly_not_session():
    plan, quotas = plugin.normalize_usage_windows(
        "Free",
        make_usage_snapshot("free", primary=0, secondary=None),
    )
    assert plan == "Free"
    assert quotas["session"]["remaining"] is None
    assert quotas["weekly"]["remaining"] is None
    assert quotas["monthly"]["remaining"] == 100
    assert quotas["monthly"]["reset"] == "09/30 14:00"


def test_paid_and_pro_window_mappings_are_preserved():
    plus_plan, plus = plugin.normalize_usage_windows(
        "Plus",
        make_usage_snapshot("plus", primary=25, secondary=50),
    )
    assert plus_plan == "Plus"
    assert plus["session"]["remaining"] == 75
    assert plus["weekly"]["remaining"] == 50
    assert plus["monthly"]["remaining"] is None

    pro_plan, pro = plugin.normalize_usage_windows(
        "Pro",
        make_usage_snapshot("prolite", primary=2, secondary=None),
    )
    assert pro_plan == "Pro"
    assert pro["session"]["remaining"] is None
    assert pro["weekly"]["remaining"] == 98
    assert pro["monthly"]["remaining"] is None


def make_raw_usage_payload(plan, *, primary_seconds, secondary_seconds=None):
    def window(used, seconds, reset_at):
        if seconds is None:
            return None
        return {
            "used_percent": used,
            "limit_window_seconds": seconds,
            "reset_at": reset_at,
        }

    return {
        "plan_type": plan,
        "rate_limit": {
            "primary_window": window(25, primary_seconds, 1788200000),
            "secondary_window": window(40, secondary_seconds, 1788800000),
        },
    }


def test_go_uses_server_window_durations_not_a_hard_coded_period():
    plan, quotas = plugin.normalize_usage_payload(
        "Free",
        make_raw_usage_payload("go", primary_seconds=5 * 60 * 60, secondary_seconds=7 * 24 * 60 * 60),
    )
    assert plan == "Go"
    assert quotas["session"]["remaining"] == 75
    assert quotas["weekly"]["remaining"] == 60
    assert quotas["monthly"]["remaining"] is None


def test_go_monthly_rollout_is_rendered_as_monthly_when_server_says_monthly():
    plan, quotas = plugin.normalize_usage_payload(
        "Go",
        make_raw_usage_payload("go", primary_seconds=30 * 24 * 60 * 60),
    )
    assert plan == "Go"
    assert quotas["session"]["remaining"] is None
    assert quotas["weekly"]["remaining"] is None
    assert quotas["monthly"]["remaining"] == 75


def test_usage_error_reason_extracts_expired_token_without_exposing_body():
    response = types.SimpleNamespace(
        status_code=401,
        json=lambda: {"error": {"code": "token_expired", "message": "secret server body"}},
    )
    exc = types.SimpleNamespace(response=response)
    assert plugin.usage_error_reason(exc) == "token_expired"


def test_usage_headers_include_account_id_without_exposing_it_in_rows(monkeypatch):
    monkeypatch.setattr(
        plugin,
        "_claims",
        lambda _: {
            plugin.PROFILE_CLAIM: {"email": "user@example.com"},
            plugin.AUTH_CLAIM: {
                "chatgpt_plan_type": "plus",
                "chatgpt_account_id": " account-scope-a ",
            },
        },
    )
    entry = make_entry(runtime_api_key="dummy-access-token")

    headers = plugin._usage_headers(entry)
    row = plugin.account_row(entry, None)

    assert headers["Authorization"] == "Bearer dummy-access-token"
    assert headers["ChatGPT-Account-Id"] == "account-scope-a"
    assert "account-scope-a" not in json.dumps(row)
    assert "dummy-access-token" not in json.dumps(row)


def test_usage_headers_omit_missing_account_id(monkeypatch):
    monkeypatch.setattr(plugin, "_claims", lambda _: {plugin.AUTH_CLAIM: {}})

    assert "ChatGPT-Account-Id" not in plugin._usage_headers(make_entry())


def test_usage_url_prefers_current_hermes_api(monkeypatch):
    import agent.account_usage as account_usage

    monkeypatch.setattr(
        account_usage,
        "_codex_backend_urls",
        lambda base_url: (f"{base_url}/usage-current", "reset", "consume"),
        raising=False,
    )
    monkeypatch.setattr(
        account_usage,
        "_resolve_codex_usage_url",
        lambda base_url: f"{base_url}/usage-legacy",
        raising=False,
    )

    assert plugin._resolve_usage_url("https://example.test") == "https://example.test/usage-current"


def test_usage_url_falls_back_to_released_hermes_api(monkeypatch):
    import agent.account_usage as account_usage

    monkeypatch.delattr(account_usage, "_codex_backend_urls", raising=False)
    monkeypatch.setattr(
        account_usage,
        "_resolve_codex_usage_url",
        lambda base_url: f"{base_url}/usage-legacy",
        raising=False,
    )

    assert plugin._resolve_usage_url("https://example.test") == "https://example.test/usage-legacy"


def test_usage_url_reports_unsupported_hermes_api(monkeypatch):
    import agent.account_usage as account_usage

    monkeypatch.delattr(account_usage, "_codex_backend_urls", raising=False)
    monkeypatch.delattr(account_usage, "_resolve_codex_usage_url", raising=False)

    with pytest.raises(ImportError, match="Codex usage URL resolver"):
        plugin._resolve_usage_url("https://example.test")


# 2. Account row does not contain raw tokens
def test_account_row_contains_no_token(monkeypatch):
    monkeypatch.setattr(
        plugin,
        "_claims",
        lambda _: {
            plugin.PROFILE_CLAIM: {"email": "user@example.com"},
            plugin.AUTH_CLAIM: {"chatgpt_plan_type": "prolite"}
        }
    )
    e = make_entry()
    row = plugin.account_row(e, "opaque-a")
    assert row["email"] == "user@example.com"
    assert row["email_verified"] is True
    assert row["current"] is True
    serialized = json.dumps(row)
    assert e.runtime_api_key not in serialized
    assert e.access_token not in serialized


def test_fallback_label_is_not_treated_as_verified_email(monkeypatch):
    monkeypatch.setattr(plugin, "_claims", lambda _: {})

    row = plugin.account_row(make_entry(label="GPT fallback"), None)

    assert row["email"] == "GPT fallback"
    assert row["email_verified"] is False


# 3. Cooldown accounts are marked non-selectable
def test_cooldown_not_selectable(monkeypatch):
    monkeypatch.setattr(plugin, "_cooldown_until", lambda _: time.time() + 60)
    row = plugin.account_row(make_entry(last_status="exhausted"), None)
    assert row["status"] == "cooldown"
    assert row["selectable"] is False


def test_cooldown_supports_older_hermes_helper_signature(monkeypatch):
    future = time.time() + 60

    def legacy_exhausted_until(entry):
        return future

    monkeypatch.setattr("agent.credential_pool._exhausted_until", legacy_exhausted_until)
    assert plugin._cooldown_until(make_entry(last_status="exhausted")) == future


# 4. Status snapshots prefer non-selecting pool reads
def _snapshot_row(entry_id="opaque-a"):
    return {
        "id": entry_id,
        "email": "user@example.com",
        "email_verified": True,
        "display": "user@example.com",
        "plan": "Plus",
        "status": "ok",
        "cooldown": None,
        "current": True,
        "priority": 0,
        "selectable": True,
        "session": {"remaining": None, "reset": None},
        "weekly": {"remaining": None, "reset": None},
        "monthly": {"remaining": None, "reset": None},
    }


def _usage_result():
    return {
        "plan": "Plus",
        "session": {"remaining": 80, "reset": "12:00"},
        "weekly": {"remaining": 60, "reset": "09/18 12:00"},
        "monthly": {"remaining": None, "reset": None},
        "fetched_at": "2026-09-11T20:00:00+08:00",
    }


def test_build_snapshot_uses_peek_without_selecting(monkeypatch):
    entry = make_entry()

    class Pool:
        def entries(self):
            return [entry]

        def peek(self):
            return entry

        def select(self):
            raise AssertionError("status query must not select from the pool")

    monkeypatch.setattr("agent.credential_pool.load_pool", lambda _: Pool())
    monkeypatch.setattr("agent.credential_pool.get_pool_strategy", lambda _: "round_robin")
    monkeypatch.setattr(plugin, "account_row", lambda item, current_id: _snapshot_row(str(item.id)))
    monkeypatch.setattr(plugin, "_cooldown_until", lambda _: None)
    monkeypatch.setattr(plugin, "_email", lambda _: "user@example.com")
    monkeypatch.setattr(plugin, "_entry_plan", lambda _: "Plus")
    monkeypatch.setattr(plugin, "fetch_account_usage", lambda _: _usage_result())

    payload = plugin.build_snapshot()

    assert payload["credential"]["id"] == "opaque-a"
    assert payload["pool_strategy"] == "round_robin"
    assert payload["priority_guaranteed"] is False


def test_legacy_pool_fallback_is_read_only(monkeypatch):
    cooling = make_entry(id="cooling", priority=0, last_status="exhausted")
    healthy = make_entry(id="healthy", priority=1)

    class LegacyPool:
        def current(self):
            return None

        def select(self):
            raise AssertionError("legacy status fallback must not select from the pool")

    monkeypatch.setattr(
        plugin,
        "_cooldown_until",
        lambda entry: time.time() + 60 if entry.id == "cooling" else None,
    )

    selected = plugin._peek_pool(LegacyPool(), [cooling, healthy])

    assert selected.id == "healthy"


def test_legacy_pool_fallback_prefers_existing_current(monkeypatch):
    current = make_entry(id="current", priority=2, last_status="exhausted")

    class LegacyPool:
        def current(self):
            return current

        def select(self):
            raise AssertionError("legacy status fallback must not select from the pool")

    monkeypatch.setattr(plugin, "_cooldown_until", lambda _: time.time() + 60)

    assert plugin._peek_pool(LegacyPool(), [current]).id == "current"


# 5. Fast path when select_id is supplied
def test_select_fast_path(monkeypatch, capsys):
    monkeypatch.setattr(plugin, "set_priority", lambda provider, account_id: (True, "ok"))
    monkeypatch.setattr(plugin, "_pool_strategy", lambda pool=None: "least_used")
    monkeypatch.setattr(
        plugin,
        "build_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("must not snapshot"))
    )
    args = types.SimpleNamespace(select_id="opaque-b")
    assert plugin.quota_status_command(args) == 0
    payload = json.loads(capsys.readouterr().out.removeprefix(plugin.MARKER))
    assert payload["selected_id"] == "opaque-b"
    assert payload["pool_strategy"] == "least_used"
    assert payload["priority_guaranteed"] is False


def test_select_unknown_account_preserves_machine_reason(monkeypatch, capsys):
    monkeypatch.setattr(plugin, "set_priority", lambda provider, account_id: (False, "unknown_account"))

    assert plugin.quota_status_command(types.SimpleNamespace(select_id="borrowed-id")) == 1
    payload = json.loads(capsys.readouterr().out.removeprefix(plugin.MARKER))

    assert payload["reason"] == "unknown_account"
    assert "borrowed-id" not in json.dumps(payload)


def test_pool_strategy_falls_back_to_pool_metadata(monkeypatch):
    import agent.credential_pool as credential_pool

    monkeypatch.delattr(credential_pool, "get_pool_strategy", raising=False)
    pool = types.SimpleNamespace(_strategy="random")

    assert plugin._pool_strategy(pool) == "random"


# 5. set_priority changes ONLY priority field, preserves other pool entry properties
def test_set_priority_preserves_other_properties(monkeypatch):
    store_data = {
        "credential_pool": {
            "openai-codex": [
                {"id": "acc-1", "priority": 1, "custom_field": "keep-1", "access_token": "tok1"},
                {"id": "acc-2", "priority": 0, "custom_field": "keep-2", "access_token": "tok2"}
            ]
        },
        "other_root_config": "preserved"
    }
    saved_store = {}

    @contextmanager
    def mock_auth_lock():
        yield

    monkeypatch.setattr("hermes_cli.auth._auth_store_lock", mock_auth_lock)
    monkeypatch.setattr("hermes_cli.auth._load_auth_store", lambda: json.loads(json.dumps(store_data)))
    def mock_save_auth_store(st):
        saved_store.clear()
        saved_store.update(json.loads(json.dumps(st)))
    monkeypatch.setattr("hermes_cli.auth._save_auth_store", mock_save_auth_store)

    ok, msg = plugin.set_priority("openai-codex", "acc-1")
    assert ok is True
    assert msg == "ok"

    assert saved_store["other_root_config"] == "preserved"
    pool = saved_store["credential_pool"]["openai-codex"]
    acc1 = next(a for a in pool if a["id"] == "acc-1")
    acc2 = next(a for a in pool if a["id"] == "acc-2")

    # Selected account gets priority 0, other gets priority 1
    assert acc1["priority"] == 0
    assert acc1["custom_field"] == "keep-1"
    assert acc1["access_token"] == "tok1"

    assert acc2["priority"] == 1
    assert acc2["custom_field"] == "keep-2"
    assert acc2["access_token"] == "tok2"


# 6. Reject selecting cooldown or dead accounts
def test_set_priority_rejects_cooldown_and_dead_accounts(monkeypatch):
    future_reset = time.time() + 1000
    store_data = {
        "credential_pool": {
            "openai-codex": [
                {"id": "acc-dead", "priority": 1, "last_status": "dead"},
                {"id": "acc-cooling", "priority": 2, "last_status": "exhausted", "last_error_reset_at": future_reset}
            ]
        }
    }

    @contextmanager
    def mock_auth_lock():
        yield

    monkeypatch.setattr("hermes_cli.auth._auth_store_lock", mock_auth_lock)
    monkeypatch.setattr("hermes_cli.auth._load_auth_store", lambda: json.loads(json.dumps(store_data)))
    monkeypatch.setattr("hermes_cli.auth._save_auth_store", lambda st: None)

    # Dead account rejected
    ok, msg = plugin.set_priority("openai-codex", "acc-dead")
    assert ok is False
    assert msg == "dead"

    # Cooldown account rejected
    ok, msg = plugin.set_priority("openai-codex", "acc-cooling")
    assert ok is False
    assert msg == "cooldown"


# 7. Verifier handles missing / malformed / valid auth.json correctly
def test_verify_auth_parsing(tmp_path):
    # 7.1 Missing auth.json
    non_existent = tmp_path / "non_existent.json"
    status, count, healthy, err = verifier.check_auth_status(non_existent)
    assert status == "missing"
    assert count == 0
    assert healthy == 0

    # 7.2 Malformed JSON
    malformed_file = tmp_path / "bad.json"
    malformed_file.write_text("{ broken json", encoding="utf-8")
    status, count, healthy, err = verifier.check_auth_status(malformed_file)
    assert status == "malformed"
    assert "JSON parse error" in err

    # 7.3 Valid auth.json
    valid_file = tmp_path / "valid.json"
    valid_file.write_text(json.dumps({
        "credential_pool": {
            "openai-codex": [
                {"id": "1", "last_status": "active"},
                {"id": "2", "last_status": "dead"}
            ]
        }
    }), encoding="utf-8")
    status, count, healthy, err = verifier.check_auth_status(valid_file)
    assert status == "valid"
    assert count == 2
    assert healthy == 1


# 8. Verifier returns non-zero when min_accounts unsatisfied or malformed
def test_verifier_min_accounts_and_malformed(tmp_path):
    hermes_home = tmp_path / "hermes_home"
    plugins_dir = hermes_home / "plugins" / "codex-quota-status"
    desktop_dir = hermes_home / "desktop-plugins" / "codex-quota-status"
    plugins_dir.mkdir(parents=True)
    desktop_dir.mkdir(parents=True)
    (plugins_dir / "__init__.py").write_text("# backend", encoding="utf-8")
    (desktop_dir / "plugin.js").write_text("// desktop", encoding="utf-8")

    # Case 1: missing auth.json with default min_accounts=2 -> fails (code 4)
    code, rep = verifier.verify_installation(hermes_home, min_accounts=2, skip_doctor=True)
    assert code == 4
    assert rep["auth_status"] == "missing"

    # Case 2: malformed auth.json -> fails (code 3)
    (hermes_home / "auth.json").write_text("invalid json", encoding="utf-8")
    code, rep = verifier.verify_installation(hermes_home, min_accounts=2, skip_doctor=True)
    assert code == 3
    assert rep["auth_status"] == "malformed"

    # Case 3: 1 account when min_accounts=2 -> fails (code 4)
    (hermes_home / "auth.json").write_text(json.dumps({
        "credential_pool": {"openai-codex": [{"id": "only-one"}]}
    }), encoding="utf-8")
    code, rep = verifier.verify_installation(hermes_home, min_accounts=2, skip_doctor=True)
    assert code == 4
    assert rep["codex_account_count"] == 1

    # Case 4: 2 accounts when min_accounts=2 -> succeeds (code 0)
    (hermes_home / "auth.json").write_text(json.dumps({
        "credential_pool": {"openai-codex": [{"id": "acc-1"}, {"id": "acc-2"}]}
    }), encoding="utf-8")
    code, rep = verifier.verify_installation(hermes_home, min_accounts=2, skip_doctor=True)
    assert code == 0
    assert rep["codex_account_count"] == 2


def test_verifier_passes_target_home_to_doctor(tmp_path, monkeypatch):
    hermes_home = tmp_path / "isolated-home"
    backend_dir = hermes_home / "plugins" / "codex-quota-status"
    desktop_dir = hermes_home / "desktop-plugins" / "codex-quota-status"
    backend_dir.mkdir(parents=True)
    desktop_dir.mkdir(parents=True)
    (backend_dir / "__init__.py").write_text("# backend", encoding="utf-8")
    (desktop_dir / "plugin.js").write_text("// desktop", encoding="utf-8")

    calls = []

    def record_subprocess(argv, **kwargs):
        calls.append((argv, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(verifier.shutil, "which", lambda _: "C:/fake/hermes")
    monkeypatch.setattr(verifier.subprocess, "run", record_subprocess)

    code, _ = verifier.verify_installation(
        hermes_home,
        min_accounts=0,
        skip_doctor=False,
    )

    assert code == 0
    assert calls[0][0] == ["hermes", "plugins", "doctor", "codex-quota-status"]
    assert calls[0][1]["env"]["HERMES_HOME"] == str(hermes_home.resolve())


# 9. Installer failure triggers rollback of old directory or removes new installation
def test_installer_rollback_on_failure(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    backend_dst = hermes_home / "plugins" / "codex-quota-status"
    desktop_dst = hermes_home / "desktop-plugins" / "codex-quota-status"

    backend_dst.mkdir(parents=True)
    desktop_dst.mkdir(parents=True)
    (backend_dst / "old.txt").write_text("original backend content", encoding="utf-8")
    (desktop_dst / "old.txt").write_text("original desktop content", encoding="utf-8")

    # Force subprocess to fail during enable
    def fail_subprocess(*args, **kwargs):
        return types.SimpleNamespace(returncode=127)

    monkeypatch.setattr("shutil.which", lambda bin_name: "/usr/bin/hermes")
    monkeypatch.setattr("subprocess.run", fail_subprocess)

    ret = installer.install(hermes_home=hermes_home, dry_run=False, skip_enable=False)
    assert ret == 1

    # Ensure original files restored
    assert (backend_dst / "old.txt").exists()
    assert (backend_dst / "old.txt").read_text(encoding="utf-8") == "original backend content"
    assert (desktop_dst / "old.txt").exists()
    assert (desktop_dst / "old.txt").read_text(encoding="utf-8") == "original desktop content"


def test_installer_passes_target_home_to_hermes_subprocess(tmp_path, monkeypatch):
    hermes_home = tmp_path / "isolated-home"
    calls = []

    def record_subprocess(argv, **kwargs):
        calls.append((argv, kwargs))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(installer, "check_hermes_cli", lambda: "/fake/hermes")
    monkeypatch.setattr(installer.subprocess, "run", record_subprocess)
    assert installer.install(hermes_home, skip_enable=False) == 0
    assert [call[0][2] for call in calls] == ["enable", "doctor"]
    assert all(call[1]["env"]["HERMES_HOME"] == str(hermes_home.resolve()) for call in calls)


def test_installer_real_copy_and_verifier_fixture(tmp_path):
    hermes_home = tmp_path / "isolated-home"

    assert installer.install(hermes_home, skip_enable=True) == 0
    backend = hermes_home / "plugins" / "codex-quota-status"
    desktop = hermes_home / "desktop-plugins" / "codex-quota-status"
    assert (backend / "__init__.py").is_file()
    assert (backend / "plugin.yaml").is_file()
    assert (desktop / "plugin.js").is_file()
    assert not (backend / "__pycache__").exists()

    (hermes_home / "auth.json").write_text(json.dumps({
        "credential_pool": {
            "openai-codex": [
                {"id": "opaque-a", "last_status": "active"},
                {"id": "opaque-b", "last_status": "active"},
            ]
        }
    }), encoding="utf-8")

    code, report = verifier.verify_installation(
        hermes_home,
        min_accounts=2,
        skip_doctor=True,
    )
    assert code == 0
    assert report["backend_installed"] is True
    assert report["desktop_installed"] is True
    assert report["codex_account_count"] == 2


# 10. Default home resolution across platforms
def test_cross_platform_default_home(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)

    # Windows simulation
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Custom\\AppData\\Local")
    win_home = installer.default_home()
    assert str(win_home).startswith("C:\\Custom\\AppData\\Local")
    assert win_home.name == "hermes"

    # Linux / macOS simulation
    monkeypatch.setattr("platform.system", lambda: "Linux")
    linux_home = installer.default_home()
    assert linux_home == Path.home() / ".hermes"

    # HERMES_HOME override
    monkeypatch.setenv("HERMES_HOME", "/custom/hermes/dir")
    override_home = installer.default_home()
    assert override_home == Path("/custom/hermes/dir")
