# CareDirect — user-operated deployment

Prepared9 November2026. No hosting, domain, publication, invitation, video upload,
commit or push has been performed by this implementation. The user chooses and
operates hosting. This guide is a preparation document until the final acceptance
matrix closes local release checks. Hosted/live outcomes remain unverified.

## Service topology

Run Next as a Node service, FastAPI as one Python3.11 service, PostgreSQL16 and
private persistent storage. Next uses Server Components/Actions and Route Handlers;
static export is unsupported. Use HTTPS for the browser and webhook endpoint.

Keep the API/database on a private network where possible. Expose only the narrowly
required signed PayPal webhook and scoped upload/provider capability routes through
the public gateway. Never rely on CORS or a case UUID for authorization. Use the
implemented public-demo trust/session controls before exposure; verify all negative
access tests against the hosted configuration.

Use one API instance with local persistent disk. Ephemeral filesystem storage loses
source documents on restart. Multi-instance operation requires a shared private
object-storage adapter, distributed limits/coordination and separate validation;
the current local storage backend does not provide that deployment capability.

## Build and start

Backend working directory api:

```text
python -m pip install .
python -m alembic upgrade head
python -m alembic check
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port <platform-port>
```

Run migrations once as a controlled release step before application traffic, not
concurrently in every worker. The seed is synthetic/idempotent and preserves existing
cases. Never run pytest or browser harness against deployment/development databases.
Avoid multiple workers while process-local demo request limits are in use.

Frontend working directory web:

```text
npm ci
npm run build
npm run start -- --hostname 0.0.0.0 --port <platform-port>
```

Replace platform-port using the host's supported environment substitution. These
are service commands, not commands this agent has run on a host. Build and dev must
never overlap against one .next directory. Preserve explicit turbopack.root=web.

## Configuration ownership

Use environment examples for exact implemented names. Enter values privately into
the host's secret settings. No .env file, token, database URL with real credentials,
private capability link or raw upload belongs in logs/repository/submission.

| Service | Names/purpose |
| --- | --- |
| API | APP_ENV, DATABASE_URL (postgresql+psycopg form), STORAGE_BACKEND=local, STORAGE_DIR (private mounted absolute path), CORS_ORIGINS |
| API intake | MAX_UPLOAD_MB, MAX_UPLOAD_PAGES, UPLOAD_TOKEN_TTL_MINUTES; implemented image/rate/demo bounds are documented in the phase9 report |
| API extraction | DOCUMENT_AI_PROVIDER=mock, DOCUMENT_AI_MODEL; real provider integration remains unchosen/unimplemented |
| API PayPal | PAYPAL_ENABLED=false initially, PAYPAL_ENVIRONMENT=sandbox, PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com |
| API PayPal secrets/context | PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_EXPECTED_MERCHANT_ID, PAYPAL_BINDING_CAPTURE_ID, PAYPAL_PROVIDER_EMAIL, PAYPAL_BUYER_EMAIL, PAYPAL_WEBHOOK_ID |
| Next server | API_BASE_URL points to API private origin; public-demo session/API trust names must match final environment examples |
| Optional Studio | AG_STUDIO_LICENSE_KEY supplied by user for deployment; STUDIO_LOCAL_EVALUATION is development-only and must remain false on hosts |

PayPal/model credentials never go into Next or NEXT_PUBLIC variables. Keep browser
source maps, private traces, source documents and export artifacts out of public
static directories. Configure host/proxy access logging to redact upload/provider
capability paths; app-level log redaction cannot sanitize an upstream proxy's logs.

## Database and release safety

Current Prompt8 schema head is0008. Follow the final phase9 head if it advances.
Back up the database and its private source storage consistently before release.
Migrations0006–0008 deliberately refuse downgrade that erases financial/history
records. Roll back application binaries only to a schema-compatible version or
restore a consistent backup after explicit operator review; never drop tables to
make a downgrade pass.

Fresh demo means a new synthetic case, not a database reset. Preserve invoices,
uncertain attempts, approvals, ledger, provider decisions and original sources.
After a failed attempt, use verification/manual recovery or another new case; never
delete history to re-enable invoice creation.

## Hosted smoke checks — user executes

1. Confirm both health endpoints and correct schema head. Restart the API and confirm
   readable source evidence survives on the private persistent volume.
2. Verify unauthenticated/expired demo session cannot read Cases, Studio, private
   source bytes, samples or exports, nor invoke payer Server Actions. Direct API
   identity-header impersonation without the trusted server credential must fail.
3. Sign into the bounded synthetic workspace, create a fresh run, upload/read sources,
   correct replay extraction, resolve the provider proposal and export HTML/JSON.
   Use no real patient records. Check all five viewports/keyboard/console.
4. Verify expired/revoked/upload-exhausted/provider-consumed capabilities show neutral
   errors and reveal no unrelated case. Confirm invalid images/oversized bodies
   cannot consume an upload slot or create private source records.
5. Test exact payment account/approval/one-attempt behavior only with new bounded human
   authorization, using STATUS.md. Buyer manually completes checkout.
   GET verification checks amount/currency/payee/composition and grants one credit.
6. Register public HTTPS443 webhook in the SAME Sandbox REST app and configure its
   returned webhook ID privately. Select only implemented documented invoice events.
   A real app-delivered notification is required for official postback verification;
   simulator mocks cannot prove this gate. Test valid, invalid, duplicate, delayed,
   retry/outage and sanitized timing. Payload/status alone never confirms payment.
7. Run the complete fresh demo twice with refresh and repeated-action attempts.
   Record hosted results separately from local mocked acceptance. The user records
   and uploads the video/submission after reviewing results.

## Pending human decisions

- Enter/rotate private REST credentials and revoke exposed legacy NVP/SOAP material
  according to preserved security history. The application never uses NVP/SOAP.
- Supply the expected receiving account and prior completed Sandbox capture for
  prepayment binding; this is configured Sandbox account context, not legal hospital
  identity verification. Verify the integrated new path live before claiming it.
- Select host/region/capacity/persistent disk/database and public endpoint. Check
  current service pricing, backup/expiry/sleep policies in the host's own console.
- Supply optional Studio deployment configuration. Core Cases/evidence remains usable.
- Choose a real extraction provider only after privacy/data handling and bounded
  synthetic testing are agreed. No available key authorizes external medical data use.

## Retention and shutdown

This is one bounded shared synthetic workspace, not production health-data hosting.
After judging, revoke public access and capabilities, stop public endpoints, rotate
shared credentials and preserve a private audited backup if needed. No automatic
financial-history deletion is implemented. Document/file deletion, real-user consent,
multi-tenant auth, bank verification and compliance certification are outside this
prototype. Never claim HIPAA compliance or production readiness from local tests.
