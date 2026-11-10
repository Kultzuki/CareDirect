# Feature A — Care Episode Intelligence

From **Cases**, create a treatment episode with a title such as
**Knee Replacement — November 2026**, a patient alias, currency, and optional treatment
context. The existing case is the episode container; upload every estimate, bill, receipt,
and supporting record through its document-review flow. No separate case is created per bill.
Existing cases can be named using **Edit episode details**. These edits are audited.

The episode inventory includes unextracted uploads, extracted documents awaiting promotion,
recorded bills, receipts, and manual payment evidence. A promoted source appears once.
Human extraction corrections are reflected in the episode. Missing/invalid extraction is
shown as needing review. Open a document or source line to inspect its page and source text.

Membership checks distinguish matching provider/patient-reference evidence, conflicting
references at one provider, conflicting currencies, and insufficient evidence. Provider-local
patient references are not compared as globally unique identifiers. Uploading a record assigns
it to an episode; it does not verify clinical membership. AI grouping suggestions are advisory
and do not move documents between episodes or override deterministic conflicts.

The timeline distinguishes upload/recording dates from stated document/payment/service dates.
Unknown service dates remain unknown. A billed service is not labeled completed treatment.
Provider responses, billing questions and payer decisions are included in chronology.

## Financial rules

- Estimates and receipts are excluded from the sum of bill evidence.
- The evidence sum can contain summary/component overlap and incomplete amounts.
- Exact cross-document candidates require matching provider, currency, service date,
  description, code, quantity, unit price and amount. Different-date visits are not duplicates.
- Nearby diagnostic bills and a same-provider package can generate a package-scope question;
  package inclusion is not assumed. Exact/package exposure is not counted twice.
- Potential overlaps never deduct money. Recorded net charges and payable buckets come
  solely from the existing ledger and reconciled payments. Confirmed adjustments are separate.
- **Refresh bill checks** persists questions for recorded lines as `CROSS_DOCUMENT_OVERLAP`
  flags. The payer uses the existing query/provider-response/decision workflow. Unresolved
  questions must be held or resolved before approval. Running checks itself moves no money.

## Model integration

`DEEPSEEK_BASE_URL=https://api.goedelmachines.com/v1`
and `DEEPSEEK_MODEL=deepseek/deepseek-v4.1-flash` are supported.
Set `DEEPSEEK_API_KEY` in the private `.env`; keep keys out of `.env.example`.
Thinking defaults off and output is bounded by `DEEPSEEK_MAX_TOKENS` (default 3,000,
hard upper bound 8,000). No model request runs during GET/page rendering.

**Analyze episode with AI** explicitly submits minimized extracted evidence. Source snippets,
document bytes and source file URLs are omitted. Student/free prompts may be stored by the
provider; use synthetic documents for demo validation. Results are schema-validated, including
one valid document assessment per supplied document. Invalid/truncated/provider-error output
falls back to an explicitly labeled local review with no invented membership confirmation.

Analysis is saved in append-only audit events with an evidence/model fingerprint. Repeated
requests for unchanged successful analysis reuse the result. Changed evidence marks advice
stale; a stale form cannot silently analyze newly uploaded evidence. Retries after a provider
failure remain explicit. AI never changes episode titles, charges, flags or payment decisions.

DeepSeek's published model metadata lists text input only. Gemini handles image/PDF extraction
using `GEMINI_API_KEY` and `GEMINI_MODEL` (default `gemini-3.8-flash`). Auto mode selects Gemini
when its key is configured and mock otherwise. All live extracted values require human review,
independently of model confidence. See `NEXT_CHAT_HANDOFF.md` for quotas and connected workflow.

## Verification

`tests/test_episode_intelligence.py` exercises the reported consultation and double-deduction
regressions, complete inventory, revised estimates, promotion deduplication, evidence dates,
approval blocking, access controls, metadata auditing, JSON validation, output bounds,
explicit AI dispatch, request caching and stale-evidence checks. Model requests are mocked.
The existing episode, comparison, payment, extraction and reconciliation tests also apply.
Live model quality and real OCR accuracy require separate acceptance with suitable input data.

Verified 9 November 2026: full backend suite **623 passed**; targeted Ruff check/format,
frontend typecheck, and production build passed. Frontend lint has no errors and one existing
`SourcePreview.tsx` image warning. Synthetic browser QA covered episode creation and upload-flow
redirect, source-line expansion, explicit mocked AI analysis, saved metadata/stale-advice handling,
timeline rendering, and desktop/mobile layout. At 390px the page stayed 390px wide while the
document table scrolled within its container. No live model calls or real medical files were used.
