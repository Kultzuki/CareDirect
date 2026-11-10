# Current status

10 November 2026: Feature E and the app-wide UI overhaul are implemented. The care
record now has nine tabs on one page with plain explanations and next steps.
Production build, TypeScript, desktop/mobile tab checks and selected-screen
automated accessibility checks pass; lint retains one existing image warning.
Backend Feature E checkpoint: 694 passed, migration head 0012. See UI_OVERHAUL.md
and FEATURE_E_FAMILY_COLLABORATION.md for details and limits.


Feature D (9 November 2026): insurance/TPA document comparison, reviewed components,
insurer remittance versus family payment evidence, and source-selected explanations
are implemented. Full backend 678 passed, final focused 64 passed; Ruff, frontend
typecheck/build pass, with one existing lint image warning. See
`FEATURE_D_INSURANCE_TPA.md` and `NEXT_CHAT_HANDOFF.md` for exact scope and limits.
Insurance episodes block gross-bill checkout; patient-only/mixed-payer checkout is
outside this feature. No live model/payment or visual browser acceptance is claimed.
The older release evidence below remains historical.

9 November2026. Core implementation through dashboard/webhooks/evidence (formerly Prompt8) exists. Acceptance is incomplete; do not claim release readiness.

- Latest full backend:586 passed, one known Starlette warning,77.28s.
- Migration0008 applied; schema drift check passed. Ruff passed. Frontend lint/typecheck passed; production build passed before the last visual fixes.
- New full UI demo twice has NOT passed. Latest focused journey reached bill correction/promotion and estimate extraction, then timed out at receipt extraction. Its upload wait reused an earlier success notice; tightened to current document type, not rerun.
- Studio screenshot/axe review found and fixed heading, scroll focus, grid spacing and accessible label defects; final passing rerun remains due. Dashboard UTF8 source encoding repaired.
- Cold Next render loops required stopping project servers and clearing only verified generated web/.next. Preserve bounded turbopack.root and unrelated home lockfiles.
- New payment HTTP/signature tests are mocked. Historical real Sandbox feasibility is recorded separately in PAYPAL_FEASIBILITY_CHECKLIST.md. New integrated account binding/checkout and hosted webhook acceptance remain unverified. No new automated checkout is authorized.

## Remaining release work (formerly Prompt9)

Bounded public-demo session/API trust boundary; full image decode/pixel limits; upload revocation/rate/storage controls; final security/dependency review; five viewport keyboard/axe/console checks; two complete fresh UI journeys; final build and acceptance matrix. Deployment/demo guides are drafts. Real extraction provider remains unchosen. User handles hosting/submission. No deploy/publish/purchase/commit/push without instruction.

## Cleanup

At the user's request both expected local databases were cleared of verified synthetic/demo/historical E2E records, retaining schema/migration versions. Development had53 cases/40 source records and no payment operations; test had8 synthetic cases including mocked payment records. Both now have zero cases and zero users. Generated files and old phase prompts/reports were removed. Normal seed CLI now initializes identity only; example records require --with-example. Running tests intentionally repopulates the isolated test DB.
