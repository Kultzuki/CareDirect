# Architecture

Browser -> Next.js server components/actions/authorized download proxies -> FastAPI -> PostgreSQL and private file storage. PayPal REST calls run only in FastAPI against Sandbox. Stack: Next16/React19/TypeScript, Python3.11/FastAPI, SQLAlchemy/Alembic, PostgreSQL16.

## Code map

- `api/app/models.py`, `states.py`, `schemas.py`: persistence, transitions and API contracts.
- `services.py`, `reconciliation/`: deterministic review, Decimal money, append-only ledger and checks.
- `documents/`, `extraction/`: private uploads, strict extraction schema, immutable originals, human revisions and explicit promotion. Only the recorded-output mock adapter exists.
- `providers.py`: hashed/scoped/expiring provider links, proposals and separate payer decisions.
- `payments.py`, `paypal_client.py`: immutable exact approval, configured receiving-account binding, durable single-attempt payment workflow and authoritative GET reconciliation.
- `webhooks.py`, `evidence.py`: signature-verified notification dedupe/refetch, personal dashboard and private allowlisted HTML/JSON export.
- `api/app/api/`: routes. Browser never calls these directly; `web/src/lib/api.ts` is server-only.
- `web/src/app/`: Cases, Studio, upload, source review, provider portal, payments and evidence pages.
- `web/src/components/`, `web/src/styles/`, `web/DESIGN.md`: shared UI, tokens and visual conventions.
- `api/alembic/versions/`: migrations; head0008. `api/tests/`, `web/e2e/`: regression coverage.
- `api/app/demo_samples.py`, `seed.py`: explicitly synthetic samples and optional example setup. `spikes/`: historical PayPal feasibility tooling.

## Invariants

Money is Python Decimal/Postgres NUMERIC and decimal strings in JSON/UI; no browser financial arithmetic. Original bill + accepted adjustments = net bill = payable now + queried + already paid. A provider proposal changes nothing until the payer accepts its current exact preview.

Approval binds exact amount/currency/purpose, immutable composition, current state fingerprint and configured receiving account. Example: original250 minus agreed20 = invoice230; prior40 leaves190 to collect. Do not relabel INR as USD or credit the prior40 again.

One invoice attempt per case. Reserve durably before every remote mutation. Unknown creation/send/external recording never automatically retries POST; recovery is GET-only. Capture references receive one unique ledger credit after authoritative validation. Browser returns and webhook names never prove payment. Refund/manual reconciliation survives later outages/stale responses.

Private source storage stays outside web/public/static. Tokens are hashed/scoped/expiring. Exports omit credentials, access URLs, storage keys and raw webhook bodies. Use only synthetic data. Public-demo session/API trust and image decoding limits remain unfinished; see STATUS.md.
