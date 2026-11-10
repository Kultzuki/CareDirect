# CareDirect — Security Notes and Immediate Actions

## Credential exposure incident

A screenshot previously shared in the project conversation visibly contained legacy NVP/SOAP Sandbox credential material (API password and signature). Treat those values as compromised.

Actions:
1. Revoke/rotate the exposed NVP/SOAP credentials in PayPal Sandbox account settings before using the account further.
2. Do not place NVP/SOAP credentials in the project. CareDirect uses the REST API only.
3. The REST Client Secret was masked in the screenshot, but continue to treat it as confidential and store it only in local `.env`.
4. Do not paste credentials into Claude Code prompts, logs, GitHub issues, screenshots, or documents.
5. If any credential was ever committed, rotate it; adding it to `.gitignore` does not remove it from Git history.

## Environment and Git

- `.env` must be ignored by Git. `.env.example` contains only empty placeholders.
- Before staging: run `git status --short`, `git check-ignore .env`, and inspect staged files.
- Never stage raw bills, UPI receipts, webhook payloads, tokens, local databases or private storage.

## Payment safety

- Sandbox base URL only: `https://api-m.sandbox.paypal.com`.
- All payment creation requires an immutable human approval record tied to exact amount, currency, provider merchant identifier and case version.
- Prevent duplicate payment attempts; use server-side idempotency where documented and maintain an internal operation key.
- Never mark a payment successful based on a browser redirect or client-supplied status.
- Re-fetch the PayPal resource server-side; verify webhook signatures and deduplicate event IDs.
- Use explicit payee/merchant identity evidence from PayPal responses; email-string matching alone is not identity verification.

## Health and personal data

- Use synthetic or redacted sample bills only in development and demos.
- Do not upload actual medical records to external AI providers without a specific privacy/legal review and approved handling arrangement.
- Keep uploads private, short-lived where possible, and inaccessible without scoped expiring tokens.
- Do not log document text, patient names, phone numbers, addresses, UPI IDs or full payment references.
- Minimise collected data and define a deletion/retention path before any real-user pilot.
