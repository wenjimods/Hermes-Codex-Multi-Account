# Compatibility & Baseline Report

This document records the exact verified baseline and upstream integration points for `hermes-codex-multi-account`.

## Verified Test Baseline

The current implementation has been tested and verified against the following environment:

| Property | Verified Value |
| :--- | :--- |
| **Hermes Agent Version** | `v0.20.5 (2026.8.19)` |
| **Upstream Git Commit** | `7eee066c` |
| **Local Working State** | `4a19dfa7 (+2 carried commits)` |
| **Python Version** | `Python 3.11.15` |
| **Locally verified OS** | `Windows 11` |
| **Configured CI targets** | `Windows`, `Ubuntu Linux`, `macOS` (remote run required) |
| **Node.js Environment** | `Node.js 22.x` |

## Internal API Dependencies & Risks

This plugin interfaces directly with internal APIs in the `hermes-agent` core:

1. **`agent.credential_pool`**:
   - Uses `load_pool("openai-codex")` to discover configured OAuth accounts.
   - Leverages `STATUS_EXHAUSTED`, `STATUS_DEAD`, and `_exhausted_until` to determine whether an account is actively cooling down or permanently invalid.
2. **`hermes_cli.auth`**:
   - Uses `_auth_store_lock()`, `_load_auth_store()`, and `_save_auth_store()` for atomic priority reordering inside `auth.json`.
3. **`agent.account_usage`**:
   - Calls `_fetch_codex_account_usage(...)` to fetch upstream rate-limit quotas directly from OpenAI Codex endpoints.
4. **Desktop Plugin SDK**:
   - Invokes backend CLI queries via `host.request("cli.exec", {argv: [...]})`.
   - Uses `ctx.i18n.register(...)` and `usePluginI18n` with graceful inline fallback.

### Risk Mitigation Strategy

- **Released/local signature bridge**: cooldown checks support both the released
  `_exhausted_until(entry)` signature and newer
  `_exhausted_until(entry, sole_credential=False)` builds.
- **Graceful Error Handling**: If internal API structures change upstream, queries fail cleanly with standard error payloads (`query_failed`) rather than crashing the Desktop UI.
- **Strict Verification Gate**: `scripts/verify.py` detects broken auth files, schema mismatches, and plugin availability before run-time.
- **Scoped Prioritization**: Prioritization modifications only touch `priority` integers; all secret tokens and custom fields are preserved unmodified.
