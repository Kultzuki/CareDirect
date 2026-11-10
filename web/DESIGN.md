# CareDirect web design system

## App-wide evidence workspace overhaul

The A–E reference images inform layout patterns, not product claims or copied brands.
Use a slate navigation rail (#183248), cobalt action (#23408f), cool ground (#eef2f7),
white source sheets (#ffffff), teal ink (#12303a), and marigold only for review questions.
Keep Atkinson for the interface and Literata for quoted source values. Navigation
follows the episode: timeline, estimate variance, duplicate comparison, insurance,
family finances, documents, approval and evidence history. Capability portals retain
their separate task and do not expose the episode navigation.

Each feature has its own working surface: date lanes plus billing evidence (A), a
dense variance table with a change rail (B), paired original/source panes and review
queue (C), separate insurer/patient components with evidence status (D), and an
internal contribution record with member roles and allocation history (E). Funding
visuals do not resemble issued payment cards or imply bank balances. Chart ratios
are presentation only and calculated on the server from exact minor units.

The same system covers dashboard, extraction's original-versus-fields desk, upload,
provider responses, staged payment approval and grouped audit exports. Maintain
keyboard access, internal table/timeline scrolling, visible source links and honest
empty states. No treatment completion, claim eligibility or payment success is
inferred by a visual status treatment.

Built in Prompt 4 for the upload and extraction review screens. Later phases (estimate drift,
provider portal, the three-bucket ledger, PayPal status) reuse these tokens and components
instead of adding new ones. If something is missing, add it here first.

## The idea

A payer is checking what a machine read off a paper bill. So the interface behaves like a
marked-up sheet of paper:

- The ground is cool, pharmacy-glass grey-green. Sheets are white. Ink is deep teal, not black.
- **Marigold is the highlighter and means one thing: a person has to look at this.** It is never
  used for decoration, links or buttons. A value that needs review gets a marker swipe behind it,
  a marigold edge on its row, and the words "Needs review".
- **Sans speaks for the app. Serif is quoted from the paper.** Labels, buttons and help text are
  Atkinson Hyperlegible Next. Extracted values and the evidence snippets are Literata, because
  they are the document's own words and numbers.
- Atkinson Hyperlegible Next was designed for low-vision readers and tells similar characters
  apart (0/O, 1/l/I). That matters for a screen where one wrong digit is a wrong payment.
- Radius follows role (controls 6px, surfaces 10px, badges pill). There is one lifted surface:
  the decision panel that holds "Add to case".

Rejected as defaults: cream ground with terracotta accent, near-black with a neon accent,
identical rounded cards with the same soft shadow, tracked-out capital labels, monospace for
labels, a hero number with a gradient. The first screen of each page is the work itself.

## Files

| Path | What it holds |
| --- | --- |
| `src/styles/tokens.css` | Every custom property (`--cd-*`). The only place colours and sizes are defined. |
| `src/app/globals.css` | Reset, base type, link, focus and form-control styles (low specificity via `:where`), `.cd-visually-hidden`, `.cd-skip-link`, reduced motion. |
| `src/components/ui/*` | Generic components with co-located CSS Modules. Barrel: `@/components/ui`. |
| `src/components/extraction/*` | `FieldRow` and `ExtractionSheet`: one extracted field, and a whole document laid out in groups. |
| `src/components/PageProblems.tsx`, `CaseStatusBadge.tsx` | API-error notice, "no demo payer" notice, demo identity note, case status badge. |
| `src/lib/money.ts` | `formatMoney`, `formatConfidence`, `isMoneyString`, `isMoneyInput`, `isQuantityInput`. |
| `src/lib/format.ts` | Labels for document types, payment methods and case statuses; dates; byte sizes. |

Fonts come from the `@fontsource-variable/*` packages and are bundled by Next.js. The page makes
no request to a font CDN.

## Tokens

Colour is grouped by meaning. Use the semantic names; never a hex value in a component.

- Surfaces: `--cd-color-ground`, `-sheet`, `-sheet-sunk`, `-rule` (decorative lines only),
  `-edge` (borders of inputs and anything a user must perceive; at least 3:1).
- Text: `--cd-color-ink`, `-ink-muted`, `-ink-inverse`.
- Action and focus: `--cd-color-action`, `-action-hover`, `-action-wash`, `-focus`,
  `--cd-focus-ring`.
- Provenance (`--cd-prov-*-fg/-bg`): `extracted`, `review`, `confirmed`, `corrected`, `provider`
  (provider-confirmed), `paypal` (PayPal-confirmed). Also `--cd-prov-review-mark` (the highlighter)
  and `--cd-prov-review-rule` (its edge).
- Buckets (`--cd-bucket-*-fg/-bg`): `payable` (payable now), `queried`, `paid` (already paid).
- Feedback (`--cd-feedback-*-fg/-bg/-edge`): `info`, `success`, `warning`, `error`.
- Type: `--cd-font-sans`, `--cd-font-paper`, sizes `--cd-text-xs` to `-3xl`, weights, leading.
- Space `--cd-space-1` to `-8` (4px base), radii, `--cd-shadow-lift`, widths, motion durations.

### Contrast (WCAG 2.2 AA)

Checked numerically against the final hex values. Text pairs are at least 4.5:1, essential UI
(control edges, focus ring, marigold edge) at least 3:1.

| Pair | Ratio |
| --- | --- |
| ink on ground / sheet | 12.7 / 13.9 |
| ink-muted on ground / sheet | 7.0 / 7.7 |
| inverse on action | 9.5 |
| action on sheet | 9.5 |
| extracted, review, confirmed, corrected badges (fg on bg) | 7.3, 8.8, 7.1, 8.3 |
| provider, paypal badges | 6.9, 8.2 |
| payable, queried, paid | 7.1, 6.7, 7.8 |
| info, success, warning, error notices | 7.8, 7.1, 8.8, 7.3 |
| ink on the marker colour | 10.2 |
| control edge on sheet / ground | 4.8 / 4.4 |
| focus ring on ground / sheet / marigold wash | 5.4 / 5.9 / 5.2 |
| marigold edge on sheet | 3.8 |

`prefers-reduced-motion` shortens every duration to near zero. `forced-colors` has fallbacks for
badges, the confidence bar and the marker swipe.

## Components

| Component | Use |
| --- | --- |
| `Button`, `ButtonLink` | `variant`: `primary`, `secondary`, `quiet`. `pending` shows a spinner and disables. Disabled buttons are dashed and muted, and should be explained in text nearby (`aria-describedby`). |
| `StatusBadge` | `tone` picks colour and icon, `children` is the required text. Never colour alone. |
| `ConfidenceIndicator` | Takes the API's decimal string, shows "Model confidence 55.0%" and a small bar. `emphasis` comes from the API's `needs_review`. |
| `MoneyText` | Formats a decimal string. Shows the raw text if it is not a valid money string. |
| `FormField` | Label, hint and error wired with `aria-describedby`; the control is a render prop. |
| `Notice` | `info`, `success`, `warning`, `error`. Errors use `role="alert"`, the rest `role="status"`. |
| `EvidenceRef` | Page number plus the quoted snippet, in the paper face. |
| `PageHeader` | The page's single `h1`, a way back, a line of facts, actions. |
| `Section`, `EmptyState` | Titled region with an `h2`; dashed placeholder that invites the next action. |
| `SiteHeader` | App frame. The product name is a link, not a heading. Shows the sandbox label. |
| `FieldRow`, `ExtractionSheet` | One extracted field (value, state, confidence, evidence, optional controls); a document in groups. |

## Status vocabulary

Words are fixed so every screen says the same thing.

- Provenance: **Extracted**, **Needs review**, **Confirmed**, **Corrected**. Later:
  **Provider confirmed**, **PayPal confirmed**.
- Extraction: **Not extracted yet**, **Extracted**, **Extraction failed**.
- Buckets: **Payable now**, **Queried**, **Already paid**.
- Actions keep their name through a flow: "Extract", "Save review", "Add to case". The success
  message repeats the action: "Added to case".

## Rules that are not optional

1. **Money is a decimal string end to end.** No `Number()`, `parseFloat()` or arithmetic on money
   in `web/`. Display goes through `formatMoney` or `MoneyText`. Money inputs are text inputs with
   `inputMode="decimal"` and are sent as strings.
2. **The UI never decides what needs review.** It renders `needs_review`, `review_required`,
   `promotion_blockers` and `can_promote` from the API. A low-confidence field is visibly marked
   and blocks "Add to case" until a person confirms or corrects it.
3. **Null is not an error to hide.** A missing value reads "Not found in document". The confidence
   gate cannot flag it, so it stays visible as a plain gap.
4. **The browser never calls FastAPI.** Server Components fetch through `src/lib/api.ts`; every
   mutation is a Server Action that validates its input again.
5. **Demo identity is labelled.** Pages that act as the demo payer say "Demo identity, not
   authentication".
6. Every interactive element has a visible focus ring and a 44px target (28px minimum for inline
   links). Every status has text.

## Writing

Sentence case, plain verbs. Say what happened and what to do next. Errors do not apologise.
Name things as the person does: "bill", "receipt", "line total", not "payload" or "extraction
schema".

## Prompt 6 — charge, source and resolution

The workspace extends the same pharmacy-glass palette without new colours or fonts. The
financial summary is one joined ledger strip: original bill, signed agreed adjustments and
net recognized total above Payable now, Queried and Already paid. A pending-review amount
is described explicitly; a bucket is never presented as a payment approval.

The plan was reviewed against the UI brief before implementation. Repeated statistic cards
were rejected in favour of the joined strip and a charge/source/question relationship. The
provider portal is a narrow one-question sheet. It exposes source excerpts, not the full
bill or patient identity. Its actions use ordinary-language labels: Credit the charge,
Propose a corrected amount and Explain the existing charge. Every response has a reason
and a preview explaining that payer review is still required.

Payer review uses an inline before/after comparison with the exact proposed charge,
payable/queried/net totals, signed adjustment and written reason. Accepting a resolution
requires a separate confirmation. Keep question open and Reject response keep the current
charge held. Original figures and earlier responses remain visible. Rule dismissal is a
separate, reasoned action and does not release a financial hold.

Interaction rules added in this phase:

- Questions preview the provider's limited view before a private link is created. Link
  creation and delivery remain distinct; the UI provides Copy link and Open provider view.
- Provider and payer drafts stay in controlled inputs after errors. Native navigation and
  unload protection warns about unsaved text without putting drafts in browser storage.
- Inline preview headings receive focus; Escape closes the preview and returns focus after
  the controls are rendered. Completion is announced with status text. Client form components
  remain mounted over the server refresh so one-time links and success focus are retained.
- Upload and provider capability pages omit payer navigation. Payer source files use a
  private Next route, with case/document authorization, no-store and no-referrer headers.
  The initial source panel offers a private preview and text excerpts; synchronized
  selection/highlighting remains further work.
- Link state, recognized line amounts and financial comparisons come from the backend.
  No browser clock or arithmetic decides financial state.

Actual desktop (1440px) and mobile (390px) screenshot review found excessive stacked spacing
above the mobile balance and a shared Section sibling margin shifting the right desktop
column. The workspace now owns its spacing, uses a 16px mobile gap, hides the repeated
mobile Bill & evidence button, and keeps navigation targets at 44px. Bucket explanation text
is a second definition-list description, preserving correct semantics and mobile alignment.
The lead owns the final five-viewport screenshots, axe/keyboard execution and phase report.

The local Next guide and Context7 official documentation were consulted for Server Actions,
useActionState and Turbopack root configuration. Explicitly bounding Turbopack to `web/`
resolved the reproduced cold-route development reload loop in the two-spec retry; no cache
feature was disabled and no unrelated home lockfile was changed.

## Prompt 7 — exact approval and payment record

Design preparation: preserve pharmacy glass `#f1f5f4`, paper `#ffffff`, deep teal
`#12303a`, muted ink `#3f5760`, blue action `#23408f` and review marigold `#ffd966`.
Components continue to use semantic tokens, not these literal values. Atkinson carries
application language; Literata and tabular figures carry source amounts.

The payment page is a readable payment instruction beside its supporting account evidence:

```text
Case identity / Payments                         Back to case
Invoice composition                              Receiving-account basis
  invoice total                                  Current blockers / resolution links
  linked external evidence
  exact amount to collect
Explicit approval / immutable approved snapshot
Invoice status / safe next action / verified receipt
```

Everything is left aligned except the aligned amount column. On narrow screens the
composition precedes account evidence, approval and status. No summary number is detached
from its currency or labelled as approved before the backend has recorded approval.

Plan critique rejected a pay-now hero and repeated statistic cards: the composition itself
is the important object. Approval and invoice creation are separate actions. The exact
amount, prior evidence, account binding and business-state fingerprint stay visible in the
approved record. Account evidence means configured Sandbox receiving-account evidence;
it does not establish legal hospital identity.

State vocabulary distinguishes approval required, invoice preparation, awaiting buyer,
verification pending, verified paid, cancelled, failed and uncertain/reconciliation required.
Unknown creation never offers another create action. Verification and manual invoice-ID
recovery are explicit actions; a return URL never produces a paid badge. Controlled drafts,
pending buttons, focused inline feedback, Escape and focus restoration support deliberate
keyboard decisions. Actual screenshot/keyboard/axe acceptance remains pending until the
integrating lead executes and records it.

Implementation keeps an existing attempt's main composition bound to its immutable
approval snapshot; a later paid ledger credit cannot turn `230 − 40 = 190` into a
misleading `230 − 40 = 0` composition. The separate invoice status shows its current
authoritative amount due. An approval attached to an attempt is preserved as history,
whereas an approval made stale before creation requires fresh review. The full snapshot
discloses approver, time, purpose, account basis and linked evidence without private links.
Transport failures use neutral result-needs-review language, since the server may have
committed before the response was lost. The create control remains disabled after submit
until the payment record is explicitly refreshed.

Independent static review found the shared Section sibling margin shifting the receiving
account column. The payment layout now owns direct section spacing. Initial typecheck
found missing Section IDs; these were added. Lint/typecheck passed after the first fixes;
actual browser acceptance remains the lead's serialized verification task.

Prompt7 mocked-flow screenshot review inspected actual 1440px and 390px renders.
The heading, demo identity and case navigation had compounded grid gaps and shared
bottom margins; the payment page now groups them with an 8px gap, removes duplicate
top padding and uses zero row gap between 44px navigation targets. The approval trigger
uses its natural width on desktop. Receiving-account copy states the legal-identity
limitation once in the backend-provided basis rather than repeating it in the heading.
These are visual corrections to the local mocked integration; they do not establish a
new live PayPal checkout or hosted acceptance.

Final Prompt7 local acceptance: all20 Chromium tests passed55.0s, including explicit
approval, retained purpose after Escape, focus restoration, axe, refresh and repeated
verification.20 payment-state captures at1440/1280/768/390/360 live outside web under
ignored output/playwright/prompt07-mocked. Lead inspected updated desktop, tablet and
mobile images after the spacing/copy corrections. Approved230/prior40/collection190
stays immutable while current invoice due becomes0; known incomplete remote reference
stays visible for manual reconciliation. These tests use deterministic HTTP responses,
not live PayPal. Error/refund/uncertain states have backend coverage and implemented
UI, but not an exhaustive screenshot suite or screen-reader audit. Full report and
next phase: docs/STATUS.md. No Prompt8/9
design implementation was started in this chat.

## Prompt 8 — the family record and its provenance

Design plan, reviewed against the UI brief before implementation: retain pharmacy-glass
ground `#f1f5f4`, paper `#ffffff`, teal ink `#12303a`, muted ink `#3f5760`, blue actions
`#23408f` and review-only marigold `#ffd966`. Components use the existing semantic tokens.
Atkinson carries navigation and decisions; Literata carries evidence and exact amounts.
The page is left aligned, with monetary comparisons aligned on the right of each ledger row.

```text
Cases / Family Studio                         start a fresh demo
One joined family balance sheet, separated by currency
All cases | Needs attention | Provider replies | Payment attempts
Case / provider / stage     Exact buckets      next safe action / activity
Fresh synthetic run controls + readable bill, estimate and receipt downloads

Activity & evidence
Case navigation / exact financial strip
Chronological actors + events     Private export preview / HTML + JSON
Original source / model / human / provider / approval / verified record sections
```

The critique removed a generic wall of statistic cards and invented trend charts. A joined
balance sheet and concrete next action better serve a family checking actual charges.
An empty case gives a working demo entry, rather than a database command. Preset views
filter the authorized case records, not financial values. The dashboard discloses inconsistent
accounting before a balance can look ready for approval. Money is never summed in the browser.

The evidence page keeps actor, timestamp and provenance explicit. Expandable source sections
preserve original extraction, human revisions, provider proposals, payer decisions, approval
snapshots and append-only ledger entries. Readable HTML and structured JSON are private
attachment downloads through an authorized server route; capability URLs are not included.
The export preview explains both contents and exclusions before download. Nested records
wrap on narrow screens rather than forcing a page-wide table scroll.

Fresh runs are additions to history. A browser-tab operation identifier (only an opaque UUID
and EMPTY/PREPARED mode, no case evidence) recovers the same request after refresh or a lost
response. A separate “Prepare another fresh run” action starts another case. Prepared runs
do not confirm extraction, accept charges, resolve questions, approve payments or move funds.
Receipt review is an explicit source-aware action; ambiguous evidence requires a separate
reasoned human confirmation, never an invisible automatic credit.

Family Studio is a client-only optional read-only analysis table with useful initial case
and currency views. Its monetary fields are exact formatted text and its currency totals
come from the backend. No AI harness, model endpoint, approval or payment tool is installed.
The core case dashboard/evidence flow works independently. AG Studio3.1.0 package peers and
current official compatibility/licence pages were checked; local evaluation requires an
explicit development-only flag, and deployment requires a valid licence. No starter code
was copied. Installation and browser checks are owned by the integrating lead.

Implementation is ready for the lead’s serialized five-viewport screenshots, keyboard,
axe, console and repeated-action checks. No Prompt8 visual acceptance is claimed here
until those actual rendered captures have been inspected and any defects corrected.

Prompt8 actual screenshot critique inspected family-dashboard desktop1440/mobile390 and
family-studio desktop1440/mobile360 in `output/playwright/prompt08`. Dashboard balances
and rows were readable without page overflow. The fresh-run controls needed a top anchor
and bounded history: the header now links directly to the demo, and six-case pages retain
access to all history. UUID-shaped references use a shorter visual label while preserving
the exact reference in the link's accessible name/title. Studio's narrow-grid header was
unnecessarily tall and its second currency clipped inside the initial widget height.
Headers now stay on one line with content-sized columns/internal horizontal scrolling,
and the currency widget has additional height. The actual axe failure also prompted a
correct h2/h3 hierarchy and a labelled keyboard-focusable scroll region. These are fixes
awaiting the lead's rerun, not a claim that the earlier failing run passed.
