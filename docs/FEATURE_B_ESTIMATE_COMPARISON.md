# Feature B — Estimate vs Final Bill Intelligence

Open a case → **Review documents** → **Compare estimate vs final bill**.
Upload an `ESTIMATE` and a `BILL` through the existing upload flow and extract both.
When there is exactly one of each, comparison loads automatically. With several documents,
select the original estimate and the final bill explicitly. No ledger promotion is required.

The comparison shows every matched service, estimated and final amounts, signed differences,
and a plain-language summary. Expand a service to inspect contributing line numbers,
quantities, unit prices, field provenance, source snippets, and authorized source-page links.
It identifies new/removed services, increases in quantities and comparable unit prices,
repeated services, and changes requiring an itemized explanation. It does not assert that a
provider supplied no explanation: explanation adjudication is outside this comparison.

`GET /api/cases/{case_id}/estimate-comparison` uses the existing case-membership check.
Optional UUID query parameters: `estimate_document_id`, `final_document_id`.
Selection is restricted to the correct document types within that case. The endpoint is
read-only, uses current extraction revisions, and does not alter charges, flags, or payments.

Arithmetic uses exact decimals. The net difference is final minus estimate, including
decreases; it is distinct from the existing estimate-drift flag's absolute-difference metric.
The page separately shows the stated-total difference and the difference traced to items.
Additive tax is included once when source arithmetic supports it. Missing values,
unreconciled totals, or low-confidence extraction produce review warnings. Currency,
provider, or document-type mismatches block comparison. Renamed services and changed codes
may appear as removed/new because matching requires normalized description and code.
Repeated services are candidates for review, not proof of duplicate billing.

No API key is required for comparison. The existing extraction adapter controls whether
input values are real or synthetic; mock results are explicitly labeled in the page.
Gemini image/PDF extraction is connected through the same reviewed extraction pipeline.
Never put API keys in frontend code; see `NEXT_CHAT_HANDOFF.md` for configuration and quotas.

Verification: `tests/test_estimate_comparison.py` and
`tests/test_estimate_comparison_api.py` cover the ₹5,500 example, offsets, source references,
quantity/price signals, tax, missing values, selection ambiguity, and access control.
HTTP tests use an isolated fake store and do not reset the shared test database.
