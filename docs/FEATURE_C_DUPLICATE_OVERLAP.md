# Feature C — Intelligent Duplicate and Overlap Detection

All findings are questions for human review. Detection never edits a charge, holds
money, credits an account, or approves payment. Use the existing query, provider
response and payer decision workflow to agree any adjustment.

## Three levels

1. **Exact duplicates:** within one bill, normalized description and code, service
   date, quantity, unit price, total and currency agree. Missing dates, quantities
   or unit prices cannot establish an exact match. The bill supplies provider and
   billing context. Exact cross-bill repeats remain Level 3 questions.
2. **Near duplicates:** differently named services may mean the same thing. A small
   local alias table recognizes CBC, CBC Test, Complete Blood Count and
   Haemogram/Hemogram. This is explicitly labelled local matching. **Analyze episode
   with AI** also asks the configured text model for source-line pairs, covering
   names beyond that table. Only supplied line IDs are accepted; self-pairs and
   foreign IDs invalidate the model response. The backend requires reviewed BILL
   evidence, episode currency, no membership conflict, the same provider and known
   service date, equal positive quantities and no conflicting supplied service
   codes. Missing codes are disclosed. Prices may differ and are shown for review.
   Neither AI nor aliases establish that the services are duplicates.
3. **Cross-document overlaps:** exact repeated services across bills and package
   inclusion questions. A hospital package and diagnostic bill within 30 days can
   raise a coverage question even when the laboratory is a different provider.
   This window uses stated document dates; it is a broad review cue, not a verified
   treatment interval. The question explicitly says episode assignment does not
   prove patient identity or package coverage. Estimates, receipts, conflicting
   records and records awaiting field review are excluded.

## Review flow

Add and review the treatment's documents. Open **Duplicate and overlap review** on
the episode page to inspect both descriptions, dates, quantities, codes, amounts
and source references. Use **Analyze episode with AI** for additional semantic
suggestions, then **Refresh bill checks** to persist review questions. The Questions
section labels each level and supports querying charges or dismissing a finding
with a recorded reason after review. Unresolved current questions block approval
unless the affected charges are held through the existing workflow.

The AI call stays explicit and uses the existing minimized episode request. There
are no extra calls on page reads or bill-check refreshes, automatic retries, or
live calls in regression tests. Successful service suggestions are append-only
audit evidence tied to the current billing-evidence fingerprint. Evidence changes
invalidate their use; stale AI suggestions cannot generate new current questions.
Source-linked historical questions remain available in the audit record. Successful
episode analysis is reused for unchanged evidence/model settings.

Exposure amounts are review amounts, not savings. A line appearing in multiple
overlap questions is counted once in the episode exposure; package questions omit
lines already covered by exact or near-match questions. Recorded payable totals
continue to come exclusively from the ledger. Same-bill exact findings retain
their existing separate question cards.

## Local setup and validation

Migration **0010** adds `POSSIBLE_NEAR_DUPLICATE` to the allowed flag types. It does
not rewrite existing bills or ledger entries. Apply with the normal Alembic upgrade
before using the new flag type. Downgrade refuses incompatible retained questions
rather than deleting history.

`api/tests/test_feature_c.py` covers alias matching, model source-ID validation,
backend conflict gates, hospital/lab package questions, immutable accounting,
idempotence, human dismissal, cached advice and stale evidence. Existing duplicate,
episode, provider and payment regressions remain applicable. Model transport is
mocked; general semantic accuracy and live model availability are unverified.

Verified 9 November 2026: full backend suite **654 passed**. After final stable-order
and immediate-analysis-response refinements, all **52 focused duplicate/episode
tests passed** (including 20 Feature C cases). Targeted Ruff check/format, frontend
typecheck and production build passed. Frontend lint reports only the existing
SourcePreview image warning. Migration 0010 was applied locally without resetting
development data. Visual QA was attempted but the in-app browser connection was
unavailable; no browser acceptance is claimed. No live AI or payment calls occurred.
