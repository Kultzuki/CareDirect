# CareDirect synthetic demo runbook

Prepared9 November2026. Local acceptance is being executed; consult the current
phase reports and final acceptance matrix for actual results. Hosted operation,
real app-delivered webhook verification and new integrated checkout remain unverified.
The user handles hosting, recording and submission.

## Start locally

Use Python3.11, Node with the repository lockfile, Docker/PostgreSQL16 and private
storage. Preserve existing .env files; supply secret values privately. Never copy
secrets into browser-public variables, screenshots, exports or terminal output.

From root: `docker compose up -d db`. From api:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a separate terminal from web:

```powershell
npm ci
npm run dev -- --hostname 127.0.0.1
```

Set server-only API_BASE_URL to the local API. `/health` on both services should
report healthy; API readiness depends on its configured database. Do not run a
production build while dev/E2E servers are running. Preserve bounded turbopack.root.

## Fresh run and exact narrative

1. Open Cases and Start a fresh demo. Download the readable USD bill, estimate and
   prior receipt. Use EMPTY to demonstrate uploads or PREPARED to begin document
   review with three already uploaded, replay-extracted sources.
2. Create the fresh synthetic case. Open its review page. EMPTY: select all three
   document types, create an upload link and open the relative upload page. Upload
   the bill/estimate/receipt. Link creation is not delivery; no invitation is sent.
3. Return to Bill & evidence and extract each document. The visible label says
   recorded synthetic replay; no real OCR/model call occurs. Compare the readable
   source registration SYN-REG-0001 with the deliberate low-confidence OOO1 misread.
   Correct it to SYN-REG-0001, give a reason and Save review. Add the bill/receipt
   to the case explicitly; estimate remains comparison evidence.
4. In Overview review and accept the three charges, then Review prior payment
   evidence. The USD40 receipt matches supplied evidence, not an authoritative bank
   record. Refresh bill checks. Original USD250 remains unchanged.
5. Question the repeated USD20 laboratory panel. Preview limited provider disclosure,
   then Hold charge and create provider link. Open it in a separate provider tab.
   Propose full credit with a reason; record the proposal for payer review.
6. Return as payer, refresh, Review financial effect, review the source and exact
   effect, give a reason/check confirmation and accept the USD0 recognized charge.
   Original250 + agreed adjustment(-20) = net230. Prior40 leaves190 to collect.
   Provider submission alone never changes the ledger.
7. Payments: inspect the configured receiving-account basis. Check Sandbox account
   evidence, review composition230/40/190 and explicitly approve exactly USD190
   with purpose/confirmation. Invoice creation is a separate deliberate action.
   Follow the separate human live gate below for actual PayPal operations.
8. After buyer return, use Verify current PayPal state explicitly. Browser return
   is not proof of payment. When authoritative invoice/capture validation succeeds,
   expect net230 = paid230 + payable0 + queried0, with one new USD190 capture credit.
   Repeat verification/refresh; the immutable approved230/40/190 stays unchanged.
9. Open Activity & evidence. Inspect separate model/human/provider/payer/PayPal
   records. Download HTML and JSON. These are private case evidence; access tokens,
   private source links and secrets are excluded. Dashboard updates from the API.

The INR seed is separate. Never relabel it USD, invent FX, subtract prior40 twice,
or describe receipt matching as bank verification.

## Under three minutes

| Time | Show |
| --- | --- |
| 0:00–0:20 | Family problem, readable sources and exact three buckets |
| 0:20–0:50 | Upload/replay label, source comparison and human correction |
| 0:50–1:20 | Question, scoped provider proposal, separate payer acceptance |
| 1:20–2:20 | Net230/prior40/collect190, account basis, approval, invoice and verification |
| 2:20–2:50 | Updated dashboard, immutable history and private export |

Rehearse actual timings. A local no-network test transport is explicitly mocked;
do not represent its simulated completion as buyer checkout or live signature delivery.
If external services are slow, show the real pending/reconciliation state and explain
the limit. A separately labelled recording/replay cannot establish live acceptance.

## Interruption and recovery

- Refresh during fresh-run creation: invoke the same run again. An opaque browser-tab
  request ID recovers the same case; it contains no evidence/secrets. To intentionally
  start another case, use Prepare another fresh run. Never truncate prior cases.
- Unsaved provider/review drafts: follow navigation warnings; save before leaving.
- Provider link expired/revoked: ask payer for a fresh scoped link. Original proposals
  remain immutable; a consumed link cannot submit twice.
- Unknown invoice creation/send/external recording: never click a replacement create
  action or automatically repeat POST. Keep the single attempt; use manual invoice-ID
  GET-only recovery and current verification. An incomplete draft may require the
  human provider-account operator to reconcile it manually, or a fresh synthetic case.
- Pending capture, wrong account/currency/amount, refund or contradictory remote state:
  remain pending/manual reconciliation. No automatic refund/reversal or new invoice.
- Export/download unavailable: remain in the case and retry the read after service
  recovery. Never publish a private capability link as a workaround.

## Separate human live gates

The detailed new integrated payment gate is STATUS.md. Privately
configure backend-only Sandbox REST credentials, expected merchant, previously completed
binding capture, provider/buyer emails and enable PayPal. Human reviews the configured
account basis and exact amount, authorizes one bounded invoice preparation, opens the
existing Sandbox invoice and completes buyer checkout manually. No automated login or
checkout is authorized. Repeated authoritative verification must create one credit.

Hosted webhooks require the user to supply a public HTTPS endpoint and register it in
the same Sandbox REST app, then privately configure PAYPAL_WEBHOOK_ID. Use a real
app-delivered event to test the chosen official postback verification. PayPal simulator
mock events do not support that postback gate. Verify invalid signature rejection,
valid event/refetch, duplicate delivery, delayed ordering and outages; retain sanitized
outcomes and elapsed times only. Do not expose raw event bodies or payment URLs.

Real OCR/provider choice remains open. Choose a provider/model only after privacy,
data handling and synthetic-input scope are agreed; configure/test separately. Existing
98.4% historical replay comparison is not OCR accuracy.

## Reproducible checks

Lead only, sequentially from api:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q --tb=short
.\.venv\Scripts\python.exe -m tests.run_browser
```

The first resets only validated caredirect_test public schema. Never overlap it with
E2E; never reset development DB or use financial migration downgrade to erase history.
Browser runner seeds synthetic data, uses explicit no-network HTTP payment transport
and stores private artifacts under ignored output/playwright outside web. Retained
traces may contain capability URLs; do not publish them. The fresh-demo browser spec
performs two UI journeys with interruption/repeat checks and export assertions.

Viewport targets:1440×900,1280×800,768×1024,390×844,360×800. Inspect actual screenshots,
keyboard focus/Escape and axe/console results. Axe is not a full screen-reader audit.
After a build, a cold Next reload loop previously cleared only after stopping servers,
verifying and removing generated web/.next. Preserve sources and home lockfiles.
