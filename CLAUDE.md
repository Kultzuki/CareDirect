# CareDirect project rules

Read README.md, docs/ARCHITECTURE.md, docs/STATUS.md and applicable AGENTS.md before changes. Use docs/PAYPAL_FEASIBILITY_CHECKLIST.md and current official PayPal docs for API behavior. UI follows web/DESIGN.md; read installed Next guides before edits.

Preserve existing uncommitted source; there is no committed baseline. Never print .env, credentials or private capability URLs. Sandbox/synthetic only. No medical judgments or invented extraction fields. Recorded replay is not OCR accuracy.

Keep Decimal accounting, immutable source/revisions/approvals, explicit human payment approval, configured account binding, state checks, durable operation reservations, single invoice attempt, unique capture credit and GET-only uncertain recovery. Never automatically retry unknown money mutations or double-credit external evidence.

Lead serializes database resets/migrations/E2E. Tests use only caredirect_test. Do not erase development data without explicit user instruction. Never run Next build/dev together; keep artifacts outside web and preserve bounded turbopack.root. Local skills/reviewer roles are under .claude. Do not modify MCP configuration. User owns hosting/submission; no deploy, purchase, publish, invitations, video upload, commit or push without instruction.
