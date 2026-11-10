---
name: financial-reconciliation
description: Implement or review CareDirect money calculations, three-bucket ledger, UPI/external payment evidence matching, invoice reconciliation and financial invariants.
---

# Financial Reconciliation Skill

- Use Python `Decimal`; store money as Postgres `NUMERIC(14,2)`; expose money as decimal strings in JSON. Never use binary float for money.
- Buckets are `payable_now`, `queried`, `already_paid`.
- Core invariant: original bill total equals the sum of the three buckets, plus only explicitly modelled adjustments. Example: ₹25,000 = ₹19,000 + ₹2,000 + ₹4,000.
- A queried charge is held pending clarification; it is not silently removed from the original bill.
- External UPI payment evidence must be matched to available evidence such as amount, date, reference, and payee details. Do not claim authoritative bank verification unless a verified integration exists.
- Do not infer a receipt's authenticity from an image alone. Label status as submitted/reviewed/matched, with explicit basis.
- Keep an append-only ledger. Correct entries with reversal/adjustment events, never destructive overwrite.
- Recompute totals on the backend. Never trust client totals or LLM arithmetic.
- Add tests for rounding, missing values, overpayment, duplicate events, adjustments, state transitions and invariant preservation.
