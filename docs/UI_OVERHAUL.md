# App-wide UI overhaul — working record

Scope: the user's five reference images guide the A–E layouts, and the later
instruction explicitly extends the overhaul to every existing screen. References
are inspiration, not instructions to copy brands, financial claims or sample data.

## Implemented

- Shared slate/cobalt episode navigation, with separate intelligence and operational
  areas. Upload/provider/invitation capability pages retain a focused portal layout.
- A: dedicated `/episode` date-lane timeline, event filters, evidence selection,
  billing summary, pending record review and the existing complete inventory.
- B: server-calculated presentation bars, exact estimate/final/difference summary,
  dense service comparison and preserved contributing-source disclosures.
- C: dedicated `/duplicates` workbench, level filter, review queue, source-line
  selectors, original document panes and links to matching billing questions.
- D: separate hospital/approved/patient components, actual payment evidence, review
  status and pending claim panel; existing confirmation/explanation/source controls.
- E: internal contribution overview, proportional presentation bar, member roles,
  allocations and financial history; all original permissions and forms retained.
- Dashboard and Studio in the shared workspace; compact case summaries, upload
  presentation, original-versus-fields extraction desk, provider question/source
  presentation, explicit payment stages, grouped evidence disclosures, home workflow
  and error/empty-state surfaces.

Money displayed comes directly from backend decimal strings. Visual financial
ratios use integer minor units on the server, never browser accounting. Statuses do
not imply clinical completion, insurance adjudication or a payment without evidence.

## Current preview

Frontend: `http://localhost:3000`. It points to the isolated synthetic API on 8100,
with model keys disabled and payment transport mocked. Do not reset `caredirect_test`
while the user is inspecting this preview. Development data is not replaced.

Populated showcase: case `34cbe21a-586b-4a29-aa1d-1781f3b081cd`.
It has readable generated synthetic PDFs: 75,000 estimate / 80,000 bill, exact/near
CBC questions, pre-authorisation, 55,000 final approval, 40,000 insurer remittance,
5,000 reconciled direct family evidence, 10,000 pending claim, and 60,000 internal
family contributions. These are generator-checked fixtures, not human OCR acceptance.

Reproduction helpers `tests.family_browser_setup` and `tests.ui_showcase_setup`
are restricted to caredirect_test and print no capability links. They append
synthetic fixtures without resetting other data. Do not run them against development.

## Validation so far

Backend Feature E checkpoint: 694 passed; migration 0012 and schema drift check pass.
The first app-wide production build passed. Subsequent presentation refinements
are being verified with lint/typecheck and browser review; record final checks here.
Desktop browser review has covered timeline, duplicates, estimate comparison,
insurance dashboard and source extraction. The current user-facing preview must
remain available while final responsive and interaction checks are completed.


## Single-page tabs and plain language — 10 November 2026

The care record now uses `/cases/[caseId]?tab=...` for nine sections: Overview,
Care timeline, Bill comparison, Repeated charges, Insurance, Family money,
Documents, Payments and History. Only the selected section is rendered; existing
URLs and individual document review/source links remain available. Navigation is
ordinary accessible links with a current-section indicator, preserving keyboard,
back/forward and deep-link behavior. The document selectors retain their tab on GET.

Each tab explains its purpose and next step. User-facing copy now calls the demo
sample records and test payments, describes family contribution history without
accounting jargon, and explains insurance terms beside the breakdown. Original
source quotations and saved financial records are retained. Harness-only sample
users are hidden from the demo person selector unless currently selected. The
showcase treatment was renamed through the existing audited Save details form.
Future generated showcase titles and contribution notes use plain names too.

Final checks for this update: production build and TypeScript passed; ESLint has
zero errors and the existing SourcePreview image optimization warning. Browser
checks loaded all nine tabs at 1440×1000 and 390×844, with no page overflow.
Comparison and insurance document selection both stayed in their tab. Automated
WCAG 2 A/AA, 2.1 AA and 2.2 AA checks on loaded comparison, insurance and family
screens at phone width reported no violations. Screenshots were reviewed. These
checks do not constitute a full accessibility or independent usability audit.
The production browser run had no application errors; CSS preload timing warnings
were observed during navigation. No backend tests or database resets were run
for this presentation-only change; the earlier 694-test backend checkpoint stands.

The current preview is a production Next server on port 3000 (tool session 21072),
with the existing isolated API on 8100. It remains available for the user. No real
payments, external messages, deployment, commit or push were performed.
