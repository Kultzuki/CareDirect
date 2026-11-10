# PayPal Sandbox Feasibility Checklist — CareDirect

Run before implementing payment architecture. Never paste secrets, tokens, full payer URLs, NVP/SOAP credentials or real personal data here. Record sanitized status codes and error names only.

Status: ☐ not tested · ✅ passed · ❌ failed · ⚠ partial · ⏸ deferred (reason given) · N/A

Minimal disclosure: Sandbox app IDs, merchant IDs and invoice IDs are shown by their last 4 characters only (`...XXXX`). PayPal debug IDs and the random `PayPal-Request-Id` UUIDs the spike generated are recorded in full because they identify only a single Sandbox request.

## A. Accounts and credentials

| ID | Check | Current status | Notes |
|---|---|---|---|
| A1 | India-country Sandbox Business provider exists and is verified | ✅ | Screenshot inspected; business account country IN and status Verified |
| A2 | REST application belongs to the India Business Sandbox account | ✅ | OAuth 200 (app_id `...762U`); captures on invoices created by this app have payee merchant ID `...TAEU`, the provider account (see B3) |
| A3 | US-country Sandbox Personal buyer exists and is verified | ✅ | Screenshot inspected; personal account country US and status Verified |
| A4 | REST Client ID and Secret stored only in local `.env` | ⚠ open | Stored in `.env` (gitignored, values never printed). The secret was pasted into chat, so it must be rotated. **Rotation deferred by the user until the project is done (user decision, 2026-11-08).** Row stays open until rotated |
| A5 | Legacy NVP/SOAP password/signature from exposed screenshot revoked/rotated | ☐ open | **Deferred by the user until the project is done (user decision, 2026-11-08).** Not used anywhere in code; never use these legacy credentials |
| A6 | All tests use Sandbox base URL | ✅ | `spike.py` exits unless `PAYPAL_ENVIRONMENT` is exactly `sandbox` and `PAYPAL_BASE_URL` is set to exactly `https://api-m.sandbox.paypal.com` (no default). Offline demo: 8 bad configs refused, exit 1 (see log) |

## B. REST authentication and provider identity

| ID | Test | Expected | Status |
|---|---|---|---|
| B1 | OAuth client-credentials token from India Business REST app | Access token returned; never logged | ✅ 200, Bearer, expires_in 32400s, invoicing scope present (re-run debug `ca574e028dcf3`) |
| B2 | Token expiry/cache behaviour | Refresh safely before expiry | ⏸ Deferred to Slice 5 client design: the spike fetches a fresh token per command; expires_in 32400s observed |
| B3 | Verify provider account identity using authoritative PayPal response | Merchant identifiers match intended Sandbox provider | ✅ `PAYPAL_EXPECTED_MERCHANT_ID` added to `.env` with user approval; `spike.py capture-payee` → `matches_expected: true` (capture GET debug `f59005116fc40`). Earlier detail: PayPal-assigned field: `GET /v2/payments/captures/{id}` for the PAYPAL transaction on the accepted invoice returns `payee.merchant_id` `...TAEU` (debug `ca574e05cbcac`), which matches the merchant ID seen in the payer-page SDK URL. `GET /v1/identity/oauth2/userinfo` with the app token returns only `sub`/`user_id`, no merchant ID (debug `ca574e041bd1a`). Invoice GET has no merchant-ID field; `invoicer.email_address` is an echo of the request and is not used. Limit: the capture-based check works only after a PayPal payment exists; there is no pre-payment REST merchant-ID check for this app |
| B4 | Confirm REST application and token are Sandbox, not Live | Sandbox environment only | ✅ Token only issued by sandbox host |

## C. Invoice and payment workflow

| ID | Test | Expected / decision | Status |
|---|---|---|---|
| C1 | Create minimal USD draft invoice from India Business provider | Record exact response; unknown until tested | ✅ POST /v2/invoicing/invoices → **201** (re-run, debug `ca574e16b6e44`); DRAFT, USD 230.00 |
| C2 | Create INR invoice from India provider | Docs indicate India PayPal users cannot receive INR; record actual result | ⏸ Deferred: not needed for the chosen USD flow; not tested |
| C3 | Send USD invoice to US Personal Sandbox buyer | SENT/UNPAID and buyer payment URL; verify actual response | ✅ POST .../send → 200, SENT. The send response body contained **no links** (`links: []`, re-run debug `ca574e187dfb2`). The payer-view URL comes from GET `detail.metadata.recipient_view_url` (present already in DRAFT). The payer URL that was in `.state.json` after the first run had been copied there manually from that GET field, not from the send response; the spike no longer stores payer URLs |
| C4 | Record external payment using documented method value for UPI-equivalent evidence | Try only documented enum values; do not assume `OTHER` or `BANK_TRANSFER` works | ✅ `OTHER` is in the official `payment_method` enum; POST .../payments → 200 with payment_id, USD 40.00 (re-run debug `ca574e1a5ebb4`) |
| C5 | GET invoice after external payment | Inspect payment entries and due amount | ✅ PARTIALLY_PAID, paid 40.00, due 190.00, transaction type EXTERNAL / method OTHER |
| C6 | Buyer opens invoice and attempts checkout | Checkout amount and behaviour recorded | ✅ Payer page and checkout showed $190.00 (remaining balance only); US buyer completed the purchase. **This checkout was automated with Playwright by the earlier agent run, logged in as the US Sandbox buyer, without the user's prior explicit approval; the user was informed afterwards.** The user has confirmed the result and accepts it as evidence (Sandbox funds only) |
| C7 | GET invoice after checkout | PayPal-confirmed paid/unpaid state and transaction reference | ✅ PAID, due 0.00, paid 230.00; transactions EXTERNAL/OTHER 40.00 + PAYPAL 190.00 (re-checked by GET, debug `ca574e3163ae2`) |
| C8 | QR generation | Record response/error; optional | ✅ POST .../generate-qr-code on a SENT invoice → 200, `multipart/form-data` body (1004 bytes) containing a base64 PNG (debug `ca574e1ceaceb`). The image encodes a payer link, so it was not decoded, saved or scanned; scanning on a phone is untested |
| C9 | Cancel invoice and verify cancelled state | No payment falsely recorded | ✅ SENT invoice `...TAMV`: POST .../cancel → 204 (debug `ca574e27048dd`); GET after → CANCELLED, no payments. A later POST .../payments on it → 422 `UNPROCESSABLE_ENTITY` / `CANNOT_PROCESS_PAYMENTS` (debug `ca574e28b2804`) |
| C10 | Idempotency behaviour | Use only if the endpoint officially documents `PayPal-Request-Id`; test duplicate request | ❌ The official Invoicing v2 OpenAPI spec does not document `PayPal-Request-Id`. Two identical creates with the same `PayPal-Request-Id` both returned 201 and created **two different** invoices (`...WCYM`, `...ZDDX`). CareDirect must guard duplicate invoice creation itself |
| C11 | `allow_partial_payment=true` for the India provider | Record actual result | ❌ Create with `configuration.partial_payment.allow_partial_payment=true` → 400 `INVALID_REQUEST`, "Partial payments are not available in your country" (debug `ca574e2b10a8d`). Matches the official spec note (not available for India). The original spike sent the flag at the wrong path (`configuration.allow_partial_payment`), which PayPal ignored |
| C12 | External payment and remaining-balance checkout with partial payments disabled | Record actual result | ✅ Invoice `...HZYG` created with `partial_payment.allow_partial_payment=false`, sent, `OTHER` 40.00 recorded → PARTIALLY_PAID, due 190.00. The user then paid it **manually** as the US Sandbox buyer (not automated). Checkout amount shown: not reported by the user. REST GET after (debug `f6138712a6ada`): PAID, due 0.00, paid 230.00, transactions EXTERNAL/OTHER 40.00 + PAYPAL 190.00, so PayPal collected 190.00. Capture payee `...TAEU`, `matches_expected: true` (debug `f638792a9cb01`). Because C11 shows partial payments cannot be enabled for India, the C6 checkout also ran with partial payments off |

### Accounting rule

Never double-count the external UPI amount. The case ledger must reconcile:

`Original bill = payable now + queried + already paid`

Seed example:

`₹25,000 = ₹19,000 payable + ₹2,000 queried + ₹4,000 already paid`

If external-payment recording and remaining-balance checkout both work, document the exact invoice and amount sequence. If they do not, keep UPI payment evidence only in CareDirect's ledger and create a PayPal invoice only for the amount that is actually to be collected through PayPal. Clearly show the distinction.

## D. Webhooks

| ID | Test | Expected | Status |
|---|---|---|---|
| D1 | Public HTTPS endpoint available | Required for remote Sandbox delivery | ⏸ Deferred: no public HTTPS endpoint exists yet (planned for Slice 7 deployment) |
| D2 | Register webhook and inspect available invoice event types | Use only event types returned by PayPal docs/account | ⚠ Event types inspected: GET /v1/notifications/webhooks-event-types → 200 (debug `ca574e074fc1e`), 205 types, including `INVOICING.INVOICE.CREATED/SENT/UPDATED/PAID/CANCELLED/REFUNDED/UNPAID/SCHEDULED/AUTOMATIC-REMINDER-SENT` and `INVOICING.RECURRING-INVOICES.EXPIRED`. GET /v1/notifications/webhooks → 200, 0 registered (debug `ca574e083ebb3`). Registration deferred: needs D1 |
| D3 | Verify webhook signature server-side | Reject invalid/tampered signatures | ⏸ Deferred: needs a registered webhook (D1/D2) and a real delivered event |
| D4 | Duplicate event ID | Process once | ⏸ Deferred: needs D1–D3; application-side behaviour to test in Slice 6 |
| D5 | Out-of-order event | Re-fetch authoritative invoice/order state | ⏸ Deferred: needs D1–D3 |
| D6 | Measure Sandbox delay | Do not rely on a webhook arriving instantly during demo | ⏸ Deferred: needs D1–D3 |

## E. MCP inspection

2026-11-09 Prompt7 implementation checkpoint: production-shaped server-only client,
cached OAuth, immutable composition/account-bound approval, durable per-stage internal
reservation, GET-only uncertain recovery and authoritative capture reconciliation
are locally implemented. Full backend556 and Chromium20 tests pass; payment HTTP
responses in this new acceptance are mocked. **No new PayPal request/checkout was
performed**, so historical live rows above remain historical and are not superseded
with new live passes. Configured prior-completed-capture prepayment binding and
send-with-notifications-suppressed/external-note-date roundtrip need actual Sandbox
acceptance. Public webhook/signature delivery remains unimplemented/unverified.
See STATUS.md, STATUS.md and STATUS.md. Historical
credential rotation deferrals and account limitations remain unchanged.

2026-11-09 Prompt 5 documentation check: Context7 official REST context and current PayPal record-payment, invoice-GET and webhook-event references were read. Recorded external payments can leave an invoice partially paid; the invoice-paid event can also describe partial/pending payment, so it is not sufficient confirmation. This was documentation-only: no OAuth, invoice mutation, checkout or live Sandbox retest was performed, and previous results remain unchanged. See `STATUS.md`.

- Inspected 2026-11-08 by the Kiro workflow agent that ran the Phase 0 gap fixes. That agent session exposes **no MCP servers and no PayPal MCP tools**; its Powers registry reports none installed. The `/mcp` slash command belongs to Claude Code and cannot be run from that agent.
- Project configuration: no `.mcp.json` in the repo. `.claude/settings.local.json` enables the Claude Code plugin `paypal@paypal-ai-toolkit`; its tool list could not be inspected from this agent.
- Still open: run `/mcp` in a Claude Code session and record the server names and exact PayPal tools.
- Historical assessment: PayPal Sandbox MCP connected, but `list_invoices` failed client-side due to a tool output-schema regex error and no tools were exposed for external-payment recording, invoice GET, QR generation or webhook operations.
- All Phase 0 evidence came from direct REST calls (`spike.py`). MCP tool success is not a substitute for backend verification.

## Validation log

| Date/time | ID | Endpoint/tool | Sanitized status/error | Actual result | Decision | Remaining uncertainty |
|---|---|---|---|---|---|---|
| 2026-11-08 | B1 | POST /v1/oauth2/token | 401 invalid_client | `.env` had placeholder values | Replaced with real REST creds | — |
| 2026-11-08 | B1 | POST /v1/oauth2/token | 200 | Token issued, invoicing scope present | Pass | — |
| 2026-11-08 | C1 | POST /v2/invoicing/invoices (USD, item 230.00) | 2xx (exact code not captured in first run; re-run below shows 201) | DRAFT `...HNE8` | IN merchant can invoice USD | Flag sent as `configuration.allow_partial_payment` (wrong path, ignored; see C11) |
| 2026-11-08 | C3 | POST .../send | 200 | SENT, due 230.00 | Pass | Buyer email delivery not checked (sandbox) |
| 2026-11-08 | C4/C5 | POST .../payments {method: OTHER, 40.00} then GET | 200 | PARTIALLY_PAID, due 190.00 | External UPI amount can be recorded on the PayPal invoice | — |
| 2026-11-08 | C6 | Payer view + checkout, **automated with Playwright** as the US buyer (no prior explicit approval; user informed afterwards and accepts the result) | n/a | Checkout amount $190.00 | Remaining-balance checkout works | — |
| 2026-11-08 | C7 | GET invoice | 200 | PAID, due 0.00, txns EXTERNAL/OTHER 40.00 + PAYPAL 190.00 | Backend GET is the confirmation source. User confirms the full flow passed | — |
| 2026-11-08 18:4x IST | A6 | `spike.py --help` with temp env files (offline) | exit 1 ×8, exit 0 ×1 | Refused: ENVIRONMENT unset / `live` / `Sandbox`; BASE_URL unset / live host / look-alike suffix / `http://`; env file missing. Valid config reached argparse only | Fail-closed works | — |
| 2026-11-08 | B1 | POST /v1/oauth2/token | 200, debug `ca574e028dcf3` | Bearer, 32400s, app_id `...762U` | Pass | — |
| 2026-11-08 | B3 | GET /v1/identity/oauth2/userinfo?schema=paypalv1.1 | 200, debug `ca574e041bd1a` | Only `sub`, `user_id` returned | Not a merchant-ID source | — |
| 2026-11-08 | B3 | GET invoice `...HNE8` → GET /v2/payments/captures/{PAYPAL txn id} | 200 (debug `ca574e05508d1`) → 200 (debug `ca574e05cbcac`) | Capture COMPLETED, payee.merchant_id `...TAEU` | PayPal-assigned identity matches the provider | Expected ID not yet in `.env` |
| 2026-11-08 | C1 | POST /v2/invoicing/invoices, request-id `ad22c445-531a-486f-bfe1-7a84fa3f7608` | **201**, debug `ca574e16b6e44`; GET after 200, debug `ca574e1707d48` | DRAFT `...HZYG`, USD 230.00 | Pass | — |
| 2026-11-08 | C3 | GET before (200, `ca574e1848b01`, DRAFT) → POST .../send, request-id `f5796731-d310-4e00-8a1a-4c8cfa536eff` → GET after (200, `ca574e193f8f5`) | 200, debug `ca574e187dfb2` | SENT; send body `links: []`; payer link only in GET metadata | Pass | — |
| 2026-11-08 | C4/C5/C12 | GET before (200, `ca574e1a2dec6`, SENT) → POST .../payments OTHER 40.00, request-id `8cda12b7-32db-4271-8fbe-5dcb2fba1498` → GET after (200, `ca574e1aa39c9`) | 200, debug `ca574e1a5ebb4` | PARTIALLY_PAID, paid 40.00, due 190.00, EXTERNAL/OTHER | Works with partial payments off | — |
| 2026-11-08 | C12 | Manual checkout by the user as the US Sandbox buyer, then GET invoice `...HZYG` and GET /v2/payments/captures/{PAYPAL txn id} | GET 200 (`f6138712a6ada`); invoice GET 200 (`f540160e74266`) → capture 200 (`f638792a9cb01`) | PAID, due 0.00, EXTERNAL/OTHER 40.00 + PAYPAL 190.00; capture COMPLETED, payee `...TAEU` matches expected | Remaining-balance checkout works with partial payments off; reproduced a second time | Checkout amount shown on the page not reported by user (REST shows 190.00 collected) |
| 2026-11-08 | C8 | POST .../generate-qr-code {300×300, pay}, request-id `90a8efab-28eb-4924-9ce2-d032bddc4fd2` | 200, debug `ca574e1ceaceb` | multipart body with base64 PNG, 1004 bytes | QR available | Not scanned |
| 2026-11-08 | C9 | Create `...TAMV` (201, `ca574e230cde6`) → send (200, `ca574e252a85e`) → GET before (200, `ca574e2688dba`, SENT) → POST .../cancel, request-id `06d987b8-9235-426d-ae79-98d321ad947e` → GET after (200, `ca574e27a1d8f`) | 204, debug `ca574e27048dd` | CANCELLED, no payments | Pass | — |
| 2026-11-08 | C9 | POST .../payments on CANCELLED invoice, request-id `79c755e5-4a18-4130-92d5-1203127c1e3b` | 422 UNPROCESSABLE_ENTITY / CANNOT_PROCESS_PAYMENTS, debug `ca574e28b2804` | Still CANCELLED, no payments (GET 200, `ca574e28e29ae`) | Cancelled invoice cannot take payments | — |
| 2026-11-08 | C10 | 2× POST /v2/invoicing/invoices, same request-id `ad5e2906-4946-4be7-95d0-a0a44fa57a31` | 201 (`ca574e29c0816`), 201 (`ca574e2a08e6e`) | Two different drafts `...WCYM`, `...ZDDX` | Not idempotent; header undocumented for Invoicing v2 | — |
| 2026-11-08 | C11 | POST /v2/invoicing/invoices with `partial_payment.allow_partial_payment=true`, request-id `4ac06cfa-6629-4418-8afc-6706f2aed6f4` | 400 INVALID_REQUEST, debug `ca574e2b10a8d` | "Partial payments are not available in your country" | India provider cannot enable partial payments | — |
| 2026-11-08 | D2 | GET /v1/notifications/webhooks-event-types; GET /v1/notifications/webhooks | 200 (`ca574e074fc1e`); 200 (`ca574e083ebb3`) | 10 INVOICING.* types; 0 webhooks registered | Registration needs public HTTPS (D1) | D3–D6 deferred |
| 2026-11-08 | B3 | GET invoice → GET /v2/payments/captures/{id} with `PAYPAL_EXPECTED_MERCHANT_ID` set (added with user approval) | 200 (`f3904487cc462`) → 200 (`f59005116fc40`); userinfo 200 (`f158821706d60`) | payee.merchant_id `...TAEU`, `matches_expected: true` | Provider identity verified from a PayPal-assigned field | Only possible after a payment exists |
| 2026-11-08 | C7 | GET invoice `...HNE8` | 200, debug `ca574e3163ae2` | PAID, due 0.00, EXTERNAL/OTHER 40.00 + PAYPAL 190.00 | Accepted run still PAID | — |
