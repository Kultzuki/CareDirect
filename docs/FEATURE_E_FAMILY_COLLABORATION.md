# Feature E — Family financial collaboration

An episode now has its owner plus accepted family memberships. Open **Family
finances** to invite people, manage roles and permissions, record contributions,
allocate accepted expenses, read notifications and inspect shared history.

## Membership and permissions

- The owner manages invitations and membership. Existing owners retain their
  permissions without a data backfill. An owner can delegate payment approval and
  remove their own approval permission while retaining access management.
- **Payer** may record their own contributions. Bill-review and payment-approval
  permissions are independent explicit grants. New grants default off.
- **Viewer** and **Patient** can read the shared episode and evidence, but cannot
  review charges, dispatch extraction/AI, record contributions or approve payments.
  Members can acknowledge their own in-app notifications.
- Reviewers can review extraction, charges, provider proposals and insurance
  evidence. Payment approvers can approve an exact amount and operate the existing
  payment flow. Reviewing does not grant payment authority.

Invitations use hashed, expiring, revocable tokens and are bound to the invited
account email. Acceptance requires that identity; a link alone does not grant case
access. Consumed invitations cannot restore subsequently revoked membership or
overwrite changed permissions. Removal preserves historical contributions and plans.
No invitation emails or external messages are sent: the owner shares the link.

This remains the existing **local synthetic prototype**. Its trusted demo identity
header and local identity switcher are not production authentication or verified
email sign-in. The owner can create .invalid synthetic identities for a walkthrough,
invite them, then switch identities to accept. Public deployment still requires the
authentication/trust-boundary work in STATUS.md.

## Separate internal ledger

`family_ledger_entries` records positive contributions and exact linked reversals,
with person, episode currency, date, reference, author and note. Original entries
are immutable at ORM and database levels. Corrections append a reversal; one entry
cannot be reversed twice. Request identifiers make repeated submissions idempotent
and reject reuse with different evidence. Only the owner records for another person
or reverses a record. Currency conversion is not inferred.

The three-sibling example records 30,000 + 20,000 + 10,000 = 60,000 in INR. These
records do **not** credit the hospital ledger, prove a bank deposit, reduce patient
liability, create a wallet or record a PayPal capture. No multi-person payment into
one PayPal invoice is enabled or assumed. That capability remains separately
unvalidated. Existing single-attempt, configured-buyer Sandbox behavior is retained.

## Expense allocation and history

Reviewers allocate exact shares of accepted, currently recognized charge amounts
to active family payers. Shares cannot exceed the source expense. Each replacement
plan is append-only and versioned; changed amounts/statuses make old plans stale
rather than silently reallocating them. A cost-sharing plan does not adjudicate
insurance liability, charge anyone or authorize payment. Contribution-minus-plan
figures are internal planning differences, not cash balances or refund authority.

Notifications are durable per-member **in-app** records generated with case audit
events. Reads are scoped to their recipient and current case access. The latest
100 are shown; the shared audit history is retained separately. Shared dashboards,
source downloads, provider workflow reads and private evidence exports enforce case
membership. Exports include family records but omit invitation capabilities/hashes.

Membership changes invalidate exact payment snapshots. Revocation remains possible
during an invoice attempt. Before every further remote mutation, the payment flow
rechecks its approved state fingerprint; changed authority stops preparation for
manual reconciliation. It does not retry an unknown operation or pretend to undo
an in-flight request. GET-only recovery and unique authoritative credits remain.

## Implementation and verification

Migration **0012** adds membership, invitation, family ledger, allocation-plan and
notification tables with constraints and mutation-protection triggers. It preserves
development records. Alembic upgrade and schema drift check passed locally.

Code: `api/app/family.py`, `api/app/api/family.py`, case authorization helpers,
payment fingerprints/mutation guards, and `/cases/[caseId]/family`. The local demo
identity switcher refreshes after setting its cookie so its identity and role agree.

Verified 9–10 November 2026: **694 backend tests passed**, including the new family
tests and existing financial/extraction/provider regressions. Targeted family/payment/
API run: **52 passed**. Ruff check/format and frontend checks/build passed at the
Feature E checkpoint. Browser checks covered the 60,000 total, member allocations,
patient read-only access, notification acknowledgement, separate reviewer/approver
identities and a 390px page with no page-width overflow. The final switcher reload
fix was verified in the browser. Live authentication, email delivery and multi-payer
PayPal acceptance were not performed. The subsequent app-wide UI overhaul has its
own validation scope.
