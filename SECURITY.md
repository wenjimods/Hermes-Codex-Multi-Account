# Security Policy

## Never commit

- `auth.json` or profile copies
- access, refresh, ID, session, or API tokens
- browser profiles, cookies, device-code receipts, or account screenshots
- personal emails, absolute home paths, logs, quota snapshots, or conversation exports

OAuth and MFA must be completed by the user in the official flow. The installer copies plugin source only and never reads or exports tokens.

Report vulnerabilities without attaching credentials. Redact email labels and opaque credential IDs unless essential to reproduction.
