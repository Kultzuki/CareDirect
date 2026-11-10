---
name: payment-security
description: Review CareDirect authentication, PayPal REST credentials, payment approval, merchant verification, idempotency, webhook validation, audit logging and privacy boundaries.
---

# Payment Security Skill

- REST credentials only; server-side in FastAPI. Never expose secrets to browser bundles, prompts, logs, screenshots or Git.
- Use Sandbox host only during development. Reject Live base URLs in dev/test configuration.
- Legacy NVP/SOAP password/signature were exposed in an earlier screenshot; rotate/revoke and never use them.
- Every payment needs a server-side immutable approval snapshot tied to case version, provider merchant ID, amount, currency, approver and timestamp.
- Revalidate case version and payee immediately before creating the payment resource.
- Use documented idempotency and internal duplicate-operation guards. Do not invent endpoint support.
- Payee verification must use authoritative merchant identifiers/account context. Email-string matching is insufficient.
- Webhook: verify signature, deduplicate event ID, treat payload as notification, then fetch current PayPal resource.
- Browser return URLs never prove payment. Backend GET determines status.
- Do not give any AI agent direct money-moving tools. Keep AI tools read-only and use explicit user approval.
- Log operation IDs and sanitized status; never log credentials, tokens, full payer URLs, patient details, UPI IDs or full payment payloads.
