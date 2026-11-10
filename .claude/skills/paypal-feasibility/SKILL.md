---
name: paypal-feasibility
description: Run or review CareDirect's PayPal Sandbox feasibility tests, including OAuth, provider-owned invoices, external payment recording, buyer checkout, invoice retrieval and webhook capability. Use before designing or changing PayPal payment architecture.
---

# PayPal Feasibility Skill

1. Read `docs/PAYPAL_FEASIBILITY_CHECKLIST.md` and current official PayPal docs before each test.
2. Inspect available MCP tools using `/mcp`; do not assume connected tools support all endpoints. Use direct REST/httpx when tools are missing or unreliable.
3. Fail closed unless environment and base URL are Sandbox. Never call Live APIs.
4. Use India Business provider REST credentials and US Personal buyer only. Credentials must be in local `.env`; never print or echo them.
5. Never use legacy NVP/SOAP credentials. They were exposed in an earlier screenshot and must be rotated/revoked.
6. Verify merchant identity from authoritative response fields, not an email string alone.
7. Do not assume INR, USD invoicing, `OTHER`, external payment recording, partial balance checkout, QR, webhooks, or idempotency work. Test and record exact outcomes.
8. Redact tokens, secrets, payer URLs, personal details and full payment references from all output.
9. Never mark payment successful from redirect or MCP text. GET the authoritative PayPal resource server-side.
10. Update the checklist with passed/failed/unverified status and a short decision. Do not silently change architecture based on speculation.
