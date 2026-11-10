# CareDirect handoff — Features A–E and app-wide UI overhaul

For the new developer assignment, start with [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md).
It covers optimisation of the whole end-user experience and supersedes this document's
next-step priorities. The integration details and earlier verification below remain historical reference.

## Latest user request — single-page tabs and simpler words

Completed 10 November 2026. Open `/cases/34cbe21a-586b-4a29-aa1d-1781f3b081cd?tab=overview`.
Nine tabs share one care-record page; each explains what it does and the next step.
Sample records/test payments replaces technical demo terminology. Insurance terms
have inline definitions. Read the latest section in UI_OVERHAUL.md for validation.
Production preview is running at localhost:3000 (session 21072), API unchanged on 8100.
Do not reset test DB while the user is viewing. Production build, lint (one existing
image warning), TypeScript and desktop/mobile navigation checks passed. Three
loaded financial screens passed automated accessibility checks. Backend checkpoint
remains 694 passed; no backend retest/reset was needed for UI copy/navigation.

## Latest work

Feature E is implemented; read `FEATURE_E_FAMILY_COLLABORATION.md`. Migration head
is **0012**, applied locally; schema drift check passes. Full backend **694 passed**.
Case-scoped family roles now separate bill review and payment approval. Contributions
and expense plans use a separate immutable internal ledger/history, with no hospital
or PayPal credits. Invitations are recipient-bound links; notifications are in-app.
Local demo identity switching is not production sign-in or external email delivery.

The user then requested an overhaul inspired by the A–E screenshots, and explicitly
expanded it to **all existing features**. Read `UI_OVERHAUL.md` for scope, new routes,
current validation and preview details. The user is inspecting the running preview
at **localhost:3000**, backed by the isolated synthetic API on 8100. Do not reset the
test DB or stop that preview casually. Model keys are disabled and payments mocked.
Finish the responsive/browser checks and final frontend validation, then update the
working UI guide. No deployment, commit, push, real payment or external message is
authorized by this handoff.

## Feature D update

Insurance and TPA reconciliation is implemented. Read
`docs/FEATURE_D_INSURANCE_TPA.md` before further insurance work. Migration head is
`0011`. New insurance upload types support Gemini PDF/image extraction and explicit
review of every populated field. Compare one hospital bill, pre-authorisation,
final settlement, separate insurer remittances and matched family payment evidence.
Decimal components and source facts stay separate; pending/rejected amounts are
not assigned automatically to the family. Missing amounts stay unknown. Reviews
and evidence-selected explanations are fingerprinted, append-only audit events.

AI can select existing cited reason facts only; the server renders amounts and
source text. No eligibility, legal-denial or invented rationale generation is
accepted. Model failures are labelled local evidence; successful unchanged calls
are reused. No model call occurs on GET. Regression model transport is mocked.

Insurance evidence does not alter the hospital ledger. **Gross-bill checkout is
blocked on insurance episodes**, and its preview never offers the entire hospital
balance for family collection. Patient-only/mixed-payer checkout is not implemented
by Feature D. Dashboard/Studio/episode labels now distinguish unallocated hospital
balances from the family's responsibility. Current insurance comparisons are
included in private evidence exports; source review links back to reconciliation.

Earlier C/A/B verification below is historical; Feature D verification is recorded
in its feature guide after the final checks.

Feature D checks: full backend **678 passed**; final focused **64 passed** after
the pending-family-payment safeguard. Ruff check/format, frontend typecheck and
production build passed. Lint retains one existing SourcePreview image warning.
No live provider/payment calls or browser visual acceptance were performed.
Local migration 0011 is applied and Alembic schema drift check passes; development
data was preserved.

## Feature C update

Intelligent duplicate/overlap review is implemented. Read
`docs/FEATURE_C_DUPLICATE_OVERLAP.md` for rules and limits. Migration head is now
`0010`. Exact duplicates retain the existing rule; missing quantity/unit price no
longer establishes exactness. Near duplicates use transparent local CBC aliases
plus source-line pairs from the explicit existing episode AI analysis. Backend
gates determine whether a pair becomes a human review question. Hospital-package
versus laboratory-invoice scope questions now support different providers.
No findings deduct money or establish package inclusion. Refresh bill checks
persists questions; existing provider responses and payer decisions handle review.
Model pairs are saved in `DUPLICATE_SERVICES_ANALYZED` audit events, fingerprinted
to billing evidence and ignored when stale. Regression tests use mocked transport;
no new live provider acceptance or payment calls were performed for Feature C.

Feature C verification: full backend 654 passed; final focused suite 52 passed;
Ruff check/format, frontend typecheck and production build passed. Lint retains
the existing SourcePreview image warning. Local development migration 0010 is
applied, with existing data retained. Visual QA could not run because the in-app
browser connection was unavailable. The older A/B evidence below remains historical.

Earlier scope: treatment episodes (A), estimate/final comparison (B),
and connection of Gemini document extraction to both, with DeepSeek episode advice.
Other features are intentionally left for the next chat.

## Run and configuration

Use the root README to run PostgreSQL, API and web locally. Apply Alembic migrations
through `0011`. Preserve the user's private root `.env`; never print, commit or replace keys.
The configured providers are:

- `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.8-flash`: PNG/JPEG/PDF extraction.
- `DOCUMENT_AI_PROVIDER=auto` (default): Gemini when its key is present, mock otherwise.
  `gemini` and `mock` can be selected explicitly. No silent mock fallback after a live error.
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL=https://api.goedelmachines.com/v1`,
  `DEEPSEEK_MODEL=deepseek/deepseek-v4.1-flash`: explicit episode analysis.
  Thinking defaults off. User has set `DEEPSEEK_MAX_TOKENS=6000`.

Gemini's configured account allowance is 5 RPM, 250,000 input TPM, 20 RPD.
`GEMINI_RPM/TPM/RPD` can lower these ceilings. The durable local SQLite limiter lives at
`storage/gemini-quota.sqlite3`, keyed by a hash of the API key. It reserves calls before
dispatch, checks input token count before generation, and never retries automatically.
Both countTokens and generation are conservatively counted toward local request budgets,
so a successful document normally consumes two local reservations (up to ten per rolling
24-hour window at the default budget). Failed calls keep their reservations. External calls
made outside this app also consume provider quota; provider 429 is reported without retry.
Do not erase the quota ledger to bypass limits. Multiple distributed hosts would need a shared
quota store before deployment; the SQLite guard covers local processes in this checkout.

Free/student provider requests may be stored. Use synthetic demo documents. Live outputs
are source-linked and schema-validated; every non-null Gemini field requires human review
independently of confidence, so confirmation/correction is required before promotion.
Confidence is not an accuracy measurement. No automatic provider call occurs on page reads.

## Workflow

1. Cases → Start a treatment episode. Use one episode for all records of a treatment.
2. Add documents through that episode's review/upload flow. Press Extract per document.
3. Review every extracted value against source pages. Corrections are append-only.
4. Feature A inventory/timeline includes pending and unpromoted documents, receipts and
   recorded bills. Membership can be consistent/conflicting/unknown. AI grouping suggestions
   are advisory, do not move documents, and cannot override deterministic conflicts.
5. Refresh bill checks to persist overlap questions. Possible overlaps never deduct money;
   use the existing payer/provider response and decision workflow for real adjustments.
6. Feature B → Compare estimate vs final bill. Select one of each if ambiguous. It uses
   revised values, exact decimal arithmetic, all contributing source lines, and separately
   displays stated-total versus itemized differences. Estimates never become payable bills.
7. Analyze episode with AI is explicit. Successful advice is audited and cached by evidence
   and model fingerprint; changes mark it stale. Model/provider failures are visibly local
   fallback, not proof of matching records.

## Key implementation pointers

- `api/app/extraction/gemini.py`, `quota.py`, `adapter.py`, `service.py`.
- `api/app/episode/{records,overlap,timeline,deepseek,service}.py`.
- `api/app/reconciliation/{checks,estimate_comparison}.py`.
- Episode endpoints in `api/app/api/cases.py`; comparison in `api/app/api/estimate_comparison.py`.
- Frontend episode components under `web/src/components/episode/` and server actions in
  `web/src/app/cases/episode-actions.ts`. Comparison route: `/cases/[caseId]/comparison`.
- Feature guides: `docs/FEATURE_A_CARE_EPISODES.md`, `docs/FEATURE_B_ESTIMATE_COMPARISON.md`.

## Verification and limits

Full backend suite: 634 passed with one known Starlette/httpx deprecation warning.
After adding the pair-budget preflight regression, all 11 adapter/quota unit tests also passed.
Production build passed. Frontend lint has no errors and one existing SourcePreview img warning.
Final adapter/quota tests also pass independently. Tests use the separate `caredirect_test`
database; its root test harness resets that database. Never run DB tests and browser/live
acceptance concurrently. Development data is not reset by the test harness.

Test isolation correction: earlier full-suite runs could inherit the configured DeepSeek key
in an episode-endpoint test (synthetic inputs only). `tests/conftest.py` now clears both model
keys before application imports. Tests that need configured providers supply fake keys and
mock their transport; future regression runs must not consume live allowance.

Live synthetic checks (9 November 2026): Gemini `countTokens` succeeded, but image and PDF
generation did not return within the 90-second and then 180-second read windows. Three bounded
attempts were made (two image, one PDF); each failed before an extraction was accepted.
DeepSeek episode analysis returned an HTTP error and the service correctly exposed
`provider_unavailable` with a labelled local fallback. No live A/B accuracy claim is supported.
No automatic retry or model substitution was performed. The generated summary is in ignored
`output/playwright/connected-live-summary.json`; the synthetic cases were created only in the
test database and may be removed by subsequent test resets. Local quota reservations remain
in the private storage quota ledger. Do not keep retrying without checking provider availability.

The code-level integration is covered by mocked adapter tests and
`tests/test_gemini_pipeline.py`, which verifies human review before promotion, saved extraction
reuse, episode inventory/timeline consumption, and exact estimate/final differences.
No payment calls, deployment, commits or pushes were performed. Human acceptance and general
OCR/model accuracy are not established by a small synthetic check.
