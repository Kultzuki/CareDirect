# PayPal Feasibility Spike

This directory is reserved for minimal, isolated PayPal Sandbox REST tests. Do not add application business logic here.

## Guardrails

- India Business Sandbox REST application only.
- US Personal Sandbox buyer only.
- Sandbox host only: `https://api-m.sandbox.paypal.com`.
- Read REST Client ID/Secret from local `.env`; never print them.
- Legacy NVP/SOAP credentials shown in an earlier screenshot must be revoked/rotated and must not be used.
- Save redacted status codes, PayPal debug IDs and decisions in `docs/PAYPAL_FEASIBILITY_CHECKLIST.md`.
- Do not run Live API calls or charge real funds.

Claude Code should create a minimal `httpx` client here only when executing Prompt 1. Keep the spike isolated and delete or archive it only after its findings are recorded.
