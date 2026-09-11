# Compatibility & Baseline Report

This document records the exact verified baseline and upstream integration points for `hermes-codex-multi-account`.

## Verified Test Baseline

Local verification was performed against the following working tree and environment; configured CI targets are listed separately:

| Property | Verified Value |
| :--- | :--- |
| **Hermes Agent Version** | `v0.21.1 (2026.9.7)` |
| **Upstream Git Commit** | `20f7ef4d` |
| **Verified Local Working Tree** | `4a39a3ff (+1 carried commit)` |
| **Python Version** | `Python 3.11.15` |
| **Locally verified OS** | `Windows 11` |
| **Configured CI targets** | `Windows`, `Ubuntu Linux`, `macOS` (remote run required) |
| **Node.js Environment** | `Node.js 22.x` |

The current verified local working tree was based on upstream commit `20f7ef4d` and included one carried local commit at `4a39a3ff`; it was not a pristine upstream checkout. Hermes Agent `v0.20.5` was the previous verified baseline and remains covered by focused compatibility tests for the older usage URL resolver.

## Internal API Dependencies & Risks

This plugin interfaces directly with internal APIs in the `hermes-agent` core:

1. **`agent.credential_pool`**:
   - Uses `load_pool("openai-codex")` to discover configured OAuth accounts.
   - Uses `CredentialPool.peek()` for status-only reads when available. Older-Hermes fallback reads `current()` or the first healthy priority-ordered entry and never invokes `select()`.
   - Reads `get_pool_strategy("openai-codex")` to explain whether priority can guarantee the next account; it does not override the configured routing strategy.
   - Leverages `STATUS_EXHAUSTED`, `STATUS_DEAD`, and `_exhausted_until` to determine whether an account is actively cooling down or permanently invalid.
2. **`hermes_cli.auth`**:
   - Uses `_auth_store_lock()`, `_load_auth_store()`, and `_save_auth_store()` for atomic priority reordering inside `auth.json`.
3. **`agent.account_usage`**:
   - Uses `_codex_backend_urls(base_url)` on Hermes v0.21.x to resolve the Codex usage endpoint.
   - Falls back to `_resolve_codex_usage_url(base_url)` on the previously verified v0.20.x line.
   - Fetches the raw usage payload so quota periods can be classified from `limit_window_seconds` rather than guessed from plan names.
   - Adds `ChatGPT-Account-Id` when the local OAuth JWT contains a `chatgpt_account_id` claim; the identifier is used only as a request header and is not returned to the Desktop UI.
4. **Desktop Plugin SDK**:
   - Invokes backend CLI queries via `host.request("cli.exec", {argv: [...]})`.
   - Uses `ctx.i18n.register(...)` and `usePluginI18n` with graceful inline fallback.

### Risk Mitigation Strategy

- **Released/local signature bridge**: cooldown checks support both the released
  `_exhausted_until(entry)` signature and newer
  `_exhausted_until(entry, sole_credential=False)` builds.
- **Usage URL compatibility bridge**: quota requests prefer the v0.21.x
  `_codex_backend_urls(...)` API and fall back to the v0.20.x
  `_resolve_codex_usage_url(...)` API. An unsupported future API fails with a
  bounded account-level error instead of crashing the Desktop plugin.
- **Graceful Error Handling**: If internal API structures change upstream, queries fail cleanly with standard error payloads (`query_failed`) rather than crashing the Desktop UI.
- **Strict Verification Gate**: `scripts/verify.py` detects broken auth files, schema mismatches, and plugin availability before run-time.
- **Scoped Prioritization**: Prioritization modifications only touch `priority` integers; all secret tokens and custom fields are preserved unmodified.
