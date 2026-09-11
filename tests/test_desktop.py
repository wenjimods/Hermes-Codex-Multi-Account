from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_PLUGIN = REPO_ROOT / "src/desktop/codex-quota-status/plugin.js"


def desktop_source() -> str:
    return DESKTOP_PLUGIN.read_text(encoding="utf-8")


def test_desktop_dropdown_is_bounded_to_the_viewport() -> None:
    source = desktop_source()

    assert "maxWidth: 'calc(100vw - 1rem)'" in source
    assert "maxHeight: 'min(32rem, calc(100vh - 1rem))'" in source
    assert "overflowY: 'auto'" in source
    assert "collisionPadding: 8" in source


def test_exact_duplicate_accounts_are_collapsed_without_hiding_plan_variants() -> None:
    source = desktop_source()

    assert "function distinctAccounts(accounts)" in source
    assert "account?.email_verified && email && plan" in source
    assert "? `${email}\\u0000${plan}`" in source
    assert ": `credential\\u0000${String(account?.id || '')}`" in source
    assert "const visibleAccounts = distinctAccounts(accounts)" in source
    assert "...visibleAccounts.map(account =>" in source
    assert "slotLabel" not in source
    assert "accountSlotMeta" not in source


def test_long_account_labels_do_not_expand_the_status_bar() -> None:
    source = desktop_source()

    assert "min-w-0 max-w-full" in source
    assert "min-w-0 truncate whitespace-nowrap font-medium" in source


def test_non_fill_first_strategy_and_unknown_account_have_clear_messages() -> None:
    source = desktop_source()

    assert "strategyWarning" in source
    assert "priority_guaranteed" in source
    assert "unknownAccount" in source
    assert "Account is visible but cannot be reprioritized in the current Hermes profile." in source
