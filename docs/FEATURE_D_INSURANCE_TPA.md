# Feature D — Insurance and TPA reconciliation

Open **Insurance and TPA reconciliation** from an episode. The hospital ledger is
not the family's liability: insurer approval, actual insurer remittance, stated
patient components, pending claims and rejected claims are separate facts.
CareDirect does not adjudicate eligibility, medical necessity or denial legality.

## Workflow

1. Upload the hospital bill and insurance evidence through the existing scoped
   upload link. New types are **Insurance pre-authorisation**, **Insurance settlement
   statement**, and **Insurer payment evidence**. PDF, PNG and JPEG use the existing
   Gemini extraction adapter, quotas, failure handling and source validator.
2. Extract explicitly. Review every populated insurance field, regardless of
   confidence. Confirm/correct using the existing append-only field review. Each
   non-null AI value requires its own document/page/snippet or bounding-box source.
   Insurance evidence is never promoted to a bill charge or family payment credit.
3. Record/review the hospital bill, then choose one bill, one final settlement,
   optional pre-authorisation, and the remittances for this claim. Ambiguous bills
   or statements require selection. References and currencies are checked; missing
   references are disclosed for the payer to verify, not inferred from filenames.
4. Compare the separate components and source evidence. Confirm document/claim
   membership and that the component amounts are separate, with a review note.
   The confirmation is an immutable audit event tied to current evidence. Changed
   source facts, receipt inventory or reconciled payments invalidate it.
5. **Explain coverage with AI** explicitly requests relevant reasons from the final
   settlement. The model selects only existing fact IDs. CareDirect renders their
   source text plus exact server-calculated amounts; unsupported generated
   narratives, foreign IDs, duplicates, empty selections and truncated responses
   fall back to labelled local evidence. Successful unchanged requests are cached.
   No network request occurs on page reads, bill checks or review confirmation.

## Amounts and missing evidence

All arithmetic uses Decimal. Approval is not cash paid. Pre-authorisation is not
final approval. Settlement-stated payment amounts do not substitute for separate
remittance evidence. Each insurer remittance needs amount, date, unique transaction
reference and the selected hospital as recipient; conflicting or incomplete
remittances require review. Duplicate references and references also appearing as
direct-payment evidence cannot establish a reconciled patient balance.

Matched direct payments associated with the bill and authoritative PayPal ledger
credits are shown separately as family payment evidence. They are not credited
again. Unassigned payments on multiple-bill episodes are excluded and disclosed.
Unreviewed receipts and submitted/unreconciled payment evidence prevent a patient
balance from being presented as reconciled. This comparison does not bank-verify
remittances or receipts.

The six settlement allocations are approved insurance, patient co-pay, deductible,
non-covered expense, pending claim and rejected claim. Components must reconcile
to the selected hospital bill after agreed adjustments. Missing fields remain
unknown; the app never silently inserts zero. The known patient-components subtotal
is available when some patient categories are unstated, but a reconciled patient
balance remains unknown until component evidence is complete. Overlapping categories
or a nonzero allocation difference require clarification. A rejected or pending
amount is not automatically added to patient liability.

For the supplied example, when the statement explicitly shows approved 55,000,
co-pay 5,000, non-covered 10,000, pending 10,000, deductible 0 and rejected 0:

| Component | INR |
| --- | ---: |
| Hospital bill | 80,000 |
| Approved insurance, not yet proof of payment | 55,000 |
| Stated patient share | 15,000 |
| Pending insurance claim, not patient debt | 10,000 |
| Bill minus approval | 25,000 |

If the family has a reconciled 5,000 payment, its remaining stated share is 10,000.
If separate insurer remittances evidence 40,000, approved funding not yet evidenced
as paid is 15,000. Neither calculation changes hospital charges or the ledger.
An omitted deductible/rejected field stays unknown even if the visible rows sum
to the bill; the known subtotal and exact document reasons are still inspectable.

## Collection and provenance

Hospital totals remain intact. Case and episode summaries label insurance balances
as unallocated hospital balances; dashboard/Studio totals describe ledger balances
before insurance allocation. The payment preview does not propose collecting the
gross hospital bill from the family. **Existing gross-bill approval/checkout is
blocked for any episode containing insurance evidence.** This feature provides
reconciliation, not a new mixed-payer or patient-only checkout. Insurer approval,
review confirmation and AI explanation never issue an invoice, create a ledger
credit or authorize a payment. Existing uncertain-payment GET recovery is retained.

Insurance comparisons are included in the existing private evidence export, using
the existing link/credential redaction. Reviewed insurance documents stop appearing
as permanently awaiting ledger promotion on the dashboard. The generic source
review links back to insurance reconciliation after field review.

## Implementation and verification

Migration **0011** expands the evidence-document type constraint without rewriting
financial records. Insurance facts extend the optional extraction schema; existing
payloads remain readable. Gemini prompt provenance is `caredirect-gemini-v2-insurance`.
Code: `api/app/insurance.py`, `insurance_explanation.py`, `api/insurance.py`,
and `/cases/[caseId]/insurance` in the web app. Reviews and explanations use
append-only `INSURANCE_REVIEWED` and `INSURANCE_EXPLAINED` audit events.

`api/tests/test_insurance.py` covers the example, missing/overlapping components,
pending/rejected claims, partial insurer/family payments, remittance references and
recipient checks, extraction review, stale forms, case access, model source
validation and caching, export, dashboard review state and collection safeguards.
Provider transport is mocked and inputs are synthetic. Live OCR/semantic quality,
actual insurer/bank settlement and human usability acceptance require separate
validation; no live provider calls or real patient data are needed for regressions.

Verified 9 November 2026: full backend suite **678 passed**. After the final pending
family-payment safeguard, **64 focused insurance/API/Gemini-pipeline/duplicate tests
passed**, including **24 insurance cases**. Targeted Ruff check/format, frontend
typecheck and production build passed. Lint has no errors and retains the existing
SourcePreview image warning. No live AI, insurance, banking or payment requests were
made. Browser visual QA was not run for this feature; the earlier in-app browser
connection was unavailable. The test harness reset only `caredirect_test`.
Migration 0011 was applied to the local development database without resetting its
data; Alembic reports no schema drift.
