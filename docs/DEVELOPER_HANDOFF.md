# Developer handoff: make CareDirect easier for end users

Prepared: 10 November 2026.

## Assignment

Optimise the entire product for patients and family members dealing with medical bills. Cover UI, UX, plain language, accessibility, mobile use, responsiveness, reliability and perceived performance. Improve complete user journeys, not just colours or individual screens. Keep financial and document evidence trustworthy.

The existing UI is a starting point. Review it with fresh eyes, identify friction, implement improvements and verify the resulting experience. Preserve the current one-page care record with separate tabs unless user research supports a change. Do not add features merely to fill space.

## Product and current baseline

CareDirect is a local synthetic medical-bill review prototype. It groups documents for one treatment, compares estimates and bills, raises possible repeated-charge questions, explains insurance evidence, supports family roles and internal contribution records, and provides an approval/reconciliation workflow for test payments.

The care-record page uses `/cases/[caseId]?tab=...` with nine sections: Overview, Care timeline, Bill comparison, Repeated charges, Insurance, Family money, Documents, Payments and History. Individual source-review and older section URLs also exist. The shared navigation already includes purpose and next-step explanations. Improve their usefulness and reduce repetition where appropriate.

Stack: Next.js/React/TypeScript frontend, FastAPI/Python backend, PostgreSQL, private local document storage, Alembic migrations, Gemini extraction and explicit DeepSeek analysis. Provider integrations are implemented; successful live extraction and general model accuracy remain unverified. Local identity switching is a demo facility, not production authentication.

Read first:

- [README](../README.md): setup and check commands.
- [UI working record](UI_OVERHAUL.md): implemented layout and historical browser coverage.
- [Feature A](FEATURE_A_CARE_EPISODES.md), [B](FEATURE_B_ESTIMATE_COMPARISON.md), [C](FEATURE_C_DUPLICATE_OVERLAP.md), [D](FEATURE_D_INSURANCE_TPA.md), [E](FEATURE_E_FAMILY_COLLABORATION.md): behaviour and constraints.
- [Previous technical handoff](NEXT_CHAT_HANDOFF.md): provider configuration, quotas and integration history.
- [Status](STATUS.md), [security notes](SECURITY_NOTES.md), [architecture](ARCHITECTURE.md) and [design guide](../web/DESIGN.md).

Older documents contain superseded checkpoints. Migration files currently extend to 0012. Architecture references to head 0008 and mock-only extraction, and the previous handoff's instruction to migrate only through 0011, are historical. Apply the current migration head after checking the target database. Do not assume any documented preview process, fixture ID or database population still exists.

## Priority 1: understand and simplify the main journey

Walk through a fresh care record and a populated synthetic record on desktop and phone. Produce a short audit with screenshots, affected routes, observed problems, severity and proposed fixes. Separate observed defects from design hypotheses. Then implement the highest-impact fixes.

The primary journey is: start a care record → add a document → review extracted details against the original → understand changes/questions → ask for clarification → review the exact payment proposal → check confirmed status/history.

Make these questions easy to answer on every screen:

1. Which treatment and document am I looking at?
2. What is known, uncertain, waiting for review or already confirmed?
3. What should I do next, and why?
4. Will this action only save information, or can it initiate a test payment?
5. Did the action succeed, and how can I recover if it failed?

Use a clear primary action per task. Prioritise unresolved work over decorative charts. Keep advanced details available through progressive disclosure. Use consistent everyday terms for care records, bills, questions and payments. Define unavoidable insurance terms near their values. Preserve user input after recoverable failures and make validation specific to the field.

## Priority 2: improve every existing area

| Area | Required UX outcome |
| --- | --- |
| Home, all records, family overview/Studio | Explain the product, distinguish sample data and test payments, support a clear start/return journey, and make record status and next action scannable. |
| Overview and care details | Show the treatment identity, meaningful progress and unresolved actions. Explain each financial total and its evidence; never invent a single payable total from incompatible balances. |
| Timeline | Make dates, missing dates, document membership and conflicts understandable. Allow movement from an event to its source and back without losing context. |
| Documents and extraction | Explain accepted formats/limits before upload; show loading, failure and retry states; make original-versus-extracted review usable on phones; distinguish extracted, corrected, confirmed and promoted values. |
| Bill comparison | Make estimate/final selection obvious; distinguish stated totals from itemised differences; explain additions and price changes; retain source links and unknown values. |
| Repeated charges | Present possible matches as review questions. Compare both entries clearly, expose the reason and evidence, and show how to ask for clarification or record a decision. |
| Insurance | Separate hospital charges, approval, actual insurer payment, patient components and pending amounts. Explain missing evidence and avoid suggesting that pending/rejected claims automatically become family debt. |
| Family money | Explain review/payment permissions before invitations. Make contribution entry, cost allocation and history understandable. State clearly that recording a contribution does not transfer money. |
| Payments | Explain eligibility, blocked states, exact approval and test-payment stages. Keep uncertain outcomes visible and provide safe status checking. Prevent duplicate actions and false success messages. |
| History and exports | Make changes, actors, dates and supporting evidence readable. Explain what a private export contains and give clear download/failure feedback. |
| Upload, provider and invitation links | Give focused task instructions; explain expiry, invalid links and insufficient permissions without exposing private information. Show a clear completion state. |
| Shared states | Design useful empty, loading, validation, unavailable, forbidden, expired-link and unexpected-error states, including the next safe action. |

## Priority 3: mobile, accessibility and performance

- Check narrow phones, larger phones, tablets, laptops and wide desktops. Suggested widths: 360, 390, 768, 1280 and 1440 pixels. Avoid page overflow; allow labelled scrolling for genuinely wide evidence tables.
- Make navigation, source previews, dense financial tables, dialogs and forms work with touch and keyboard. Preserve back/forward navigation, deep links and selected-document context.
- Verify visible focus, logical focus order, accessible names, semantic headings, contrast, error announcements, zoom and reduced motion. Do not communicate status through colour alone. Target WCAG 2.2 AA and document remaining gaps.
- Measure before optimising. Identify slow initial views, navigation, source loading and repeated server/API work with synthetic records of realistic size. Record baseline and after-change results with the same device/network conditions.
- Reduce unnecessary fetching, rendering and large assets where evidence shows a benefit. Provide immediate progress feedback for long operations. Do not silently repeat extraction, analysis or payment mutations to make the interface appear faster.

## Non-negotiable behaviour

- Money remains server-calculated Decimal/NUMERIC and decimal strings. Do not introduce browser accounting or alter currency labels.
- Original documents and append-only audit/history remain intact. Extracted fields require human review before promotion. AI output stays advisory, source-linked and visibly stale when its evidence changes.
- Possible duplicate/overlap findings never deduct money automatically. Estimates are not payable bills.
- Family contribution records do not credit the hospital ledger. Invitations do not send email; notifications are in-app. Do not imply that several relatives can pay one PayPal invoice.
- Insurance evidence does not change the hospital ledger. Gross-bill checkout remains blocked for insurance episodes; patient-only/mixed-payer checkout is not implemented.
- Approval stays bound to exact amount, currency, purpose, state and configured receiving account. Account binding does not verify hospital identity.
- Preserve durable reservations and deduplication. Unknown payment outcomes use authoritative GET reconciliation; never automatically retry a remote mutation. Redirects and webhook event names do not prove payment.
- Preserve role checks, private source access and scoped expiring links. Real-user authentication, public-demo trust boundaries, upload abuse controls and privacy/retention work remain release gates.

## Implementation map

| Work | Starting points |
| --- | --- |
| Navigation and overall layout | `web/src/components/workspace/WorkspaceFrame.tsx`, its CSS module, `web/src/app/layout.tsx`, `web/src/app/globals.css` |
| Single-page care record | `web/src/app/cases/[caseId]/page.tsx`, adjacent section routes and server actions |
| Timeline, summaries, repeated charges | `web/src/components/workspace/`, `web/src/components/episode/` |
| Upload and source review | `web/src/components/extraction/`, document routes, `api/app/documents/`, `api/app/extraction/` |
| Dashboard and Studio | `web/src/components/dashboard/`, `web/src/app/cases/` |
| Shared controls and API access | `web/src/components/ui/`, `web/src/lib/api.ts` |
| Financial and collaboration rules | `api/app/reconciliation/`, `insurance.py`, `family.py`, `payments.py`, `providers.py`, `evidence.py` |
| Regression coverage | `api/tests/`, `web/e2e/` |

Read applicable repository instructions before editing. Keep changes coherent and reviewable, reuse existing components and tokens where suitable, and add meaningful regression coverage for changed behaviour.

## Run and verify safely

Use the root README for environment setup and commands. Preserve private `.env` files. Use synthetic documents and mock provider/payment transport for routine UI work. Do not consume live model quotas for ordinary page testing; never erase the quota ledger to bypass limits.

Before running checks, inspect active servers, environment selection and database targets. Earlier previews used frontend port 3000 and an isolated synthetic API on 8100; confirm current state rather than relying on old session IDs. The backend harness resets `caredirect_test`. Never run database tests concurrently with a preview/browser journey using that database. Do not overlap a frontend build with its dev server.

Historical evidence from existing project records, not rerun for this documentation handoff:

- Feature E backend checkpoint: 694 tests passed; migration 0012 and schema drift check passed locally.
- Latest recorded frontend build and TypeScript check passed; lint had one existing SourcePreview image warning.
- Nine tabs were checked at 1440×1000 and 390×844 without page overflow. Selected comparison, insurance and family screens passed automated accessibility checks at phone width.
- These results do not establish full accessibility, independent usability acceptance, live provider accuracy, integrated PayPal Sandbox checkout, hosted webhook acceptance or production readiness.

For implementation, run frontend lint, typecheck and build. Run relevant backend checks if behaviour changes. Verify keyboard and browser interactions after the final change. Test a fresh-record journey and a populated-record journey end to end, including at least one recoverable error and permission restriction. Do not replace user testing with automated accessibility results.

## Completion criteria and deliverables

Deliver an implemented improvement pass across all existing areas, with explicit disposition of each audited issue. Include before/after screenshots, a concise change log, measured performance results, verification commands/results and remaining limitations. Update this handoff, STATUS.md and UI_OVERHAUL.md so the next developer can distinguish current facts from historical checks.

Ask representative first-time users to start a record, review a document, interpret a repeated-charge question, explain the insurance breakdown and distinguish a family contribution from a hospital payment. Record task completion, assistance needed, misunderstandings and feedback. If participants are unavailable, mark human acceptance pending and leave a ready-to-run script; do not claim success on their behalf.

The pass is ready for review when the primary journeys work at the target sizes, users can identify the next action and explain what the displayed amounts mean, changed financial/permission behaviour has regression coverage, final checks pass or have documented blockers, and unresolved release gates are explicit. Hosting and real-money/provider activation require their own verified readiness work.
