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
    assert plugin.normalize_plan("unknown_plan") == "Unknown Plan"


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
    assert row["current"] is True
    serialized = json.dumps(row)
    assert e.runtime_api_key not in serialized
    assert e.access_token not in serialized


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


# 4. Fast path when select_id is supplied
def test_select_fast_path(monkeypatch, capsys):
    monkeypatch.setattr(plugin, "set_priority", lambda provider, account_id: (True, "ok"))
    monkeypatch.setattr(
        plugin,
        "build_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("must not snapshot"))
    )
    args = types.SimpleNamespace(select_id="opaque-b")
    assert plugin.quota_status_command(args) == 0
    payload = json.loads(capsys.readouterr().out.removeprefix(plugin.MARKER))
    assert payload["selected_id"] == "opaque-b"


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
