import type { Metadata } from "next";
import { randomUUID } from "node:crypto";
import { connection } from "next/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ApiProblem, NoDemoPayer } from "@/components/PageProblems";
import { MoneyText, PageHeader, Section } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { activityLabel } from "@/lib/dashboard-types";
import type { FamilyWorkspace } from "@/lib/family-types";
import { formatDateTime } from "@/lib/format";
import { attempt } from "@/lib/load";
import { isUuid } from "@/lib/validation";
import { FamilyForm } from "./FamilyForm";
import styles from "./family.module.css";
import { FamilyFundingOverview } from "@/components/workspace/FinancialOverviews";

export const metadata: Metadata = { title: "Family collaboration", referrer: "no-referrer", robots: { index: false, follow: false } };

export default function FamilyPage({ params }: { params: Promise<{ caseId: string }> }) {
  return <Suspense fallback={<p>Loading family record…</p>}><Family params={params} /></Suspense>;
}

function RoleFields({ role = "VIEWER", review = false, approve = false }: { role?: string; review?: boolean; approve?: boolean }) {
  return <><label>Episode role<select name="role" defaultValue={role}><option value="PAYER">Payer — may record contributions</option><option value="VIEWER">Viewer — read only</option><option value="PATIENT">Patient — read only</option></select></label><label><input type="checkbox" name="can_review" defaultChecked={review} />Can review bills and evidence (payer role only)</label><label><input type="checkbox" name="can_approve" defaultChecked={approve} />Can approve and manage payments (payer role only)</label></>;
}

async function Family({ params }: { params: Promise<{ caseId: string }> }) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => { const actor = await getDemoPayer(); return actor ? apiGet<FamilyWorkspace>(`/api/cases/${seg(caseId)}/family`, { actorId: actor.id }) : null; });
  if (!loaded.ok) return <ApiProblem error={loaded.error} />;
  if (!loaded.value) return <NoDemoPayer />;
  const family = loaded.value;
  const name = (id: string) => family.members.find((member) => member.user_id === id)?.display_name ?? "Recorded family member";
  const activePayers = family.members.filter((member) => member.active && member.role === "PAYER");
  const reversed = new Set(family.ledger.map((entry) => entry.reverses_id).filter(Boolean));
  return <div className={styles.page}>
    <PageHeader title="Family money" back={{ href: `/cases/${caseId}`, label: "Episode overview" }} />
    <FamilyFundingOverview family={family} />
    <p>Your role: {family.access.role?.toLowerCase()} · Bill review: {family.access.can_review ? "allowed" : "not allowed"} · Payment approval: {family.access.can_approve ? "allowed" : "not allowed"}.</p>
    <p>This page keeps track of what each person contributed. It does not check a bank account or send money to the hospital. All amounts use the same currency as this care record.</p>
    <Section id="family-balances" title="Who contributed what">
      <p className={styles.total}>Contributions after corrections: <MoneyText value={family.total_contributions} currency={family.currency} /></p>
      <div className={styles.scroll} role="region" tabIndex={0} aria-label="Scrollable family contributions"><table className={styles.table}><caption>Each person’s contributions and agreed share of costs — not a bank balance</caption><thead><tr><th scope="col">Member</th><th scope="col">Role and permissions</th><th scope="col">Contributed</th><th scope="col">Agreed share of costs</th><th scope="col">Contribution minus agreed share</th></tr></thead><tbody>{family.members.map((member) => <tr key={member.user_id}><th scope="row">{member.display_name}{member.is_owner ? " · owner" : ""}{!member.active ? " · access removed" : ""}</th><td>{member.role.toLowerCase()}<p>Review: {member.can_review ? "yes" : "no"} · Approve: {member.can_approve ? "yes" : "no"}</p></td><td><MoneyText value={member.contributions} currency={family.currency} /></td><td><MoneyText value={member.allocated_expenses} currency={family.currency} /></td><td><MoneyText value={member.contribution_minus_allocation} currency={family.currency} /></td></tr>)}</tbody></table></div>
    </Section>
    {family.access.can_manage && <Section id="family-invitations" title="Invite and manage family members" description="Invite the person's existing account email. A new member gets access only after accepting. No invitation email is sent by this prototype.">
      <FamilyForm caseId={caseId} command="invite" requestId={randomUUID()} label="Create family invitation"><label>Recipient email<input name="recipient_email" type="email" required maxLength={254} /></label><RoleFields /></FamilyForm>
      <details><summary>Demo: add a sample family member</summary><p>Use a made-up email ending in .invalid, such as daughter@example.invalid. Then create an invitation and use “Try the demo as” above to accept it as that person.</p><FamilyForm caseId={caseId} command="demo" requestId={randomUUID()} label="Add sample family member"><label>Display name<input name="display_name" required maxLength={120} placeholder="Daughter in USA" /></label><label>Sample email<input type="email" name="email" required placeholder="daughter@example.invalid" /></label></FamilyForm></details>
      {family.invitations.map((invite) => <div className={styles.entry} key={invite.id}><p>{invite.recipient_email} · {invite.role.toLowerCase()} · {invite.accepted_at ? "Accepted" : invite.revoked_at ? "Revoked" : invite.expired ? "Expired" : "Pending"} · expires {formatDateTime(invite.expires_at)}</p>{!invite.accepted_at && !invite.revoked_at && !invite.expired && <FamilyForm caseId={caseId} command="revoke" targetId={invite.id} requestId={randomUUID()} label="Revoke invitation" />}</div>)}
      <h3>Who can do what</h3><p>The record owner chooses who can join. Someone can check bills without being allowed to approve payment. If permissions change, payment approval may need to be checked again. Removing a person keeps their earlier contributions in the history.</p>
      {family.members.map((member) => <details key={member.user_id}><summary>{member.display_name} · change role or permissions</summary><FamilyForm caseId={caseId} command="member" targetId={member.user_id} requestId={randomUUID()} label="Save member permissions"><RoleFields role={member.role} review={member.can_review} approve={member.can_approve} /><label><input type="checkbox" name="active" defaultChecked={member.active} />Active episode access</label><label>Reason<textarea name="note" required maxLength={2000} rows={2} /></label></FamilyForm></details>)}
    </Section>}
    {family.access.can_contribute && <Section id="family-contribute" title="Record a family contribution" description="Keep a note of money a family member contributed. This does not count as a hospital payment or reduce the bill."><FamilyForm caseId={caseId} command="contribution" requestId={randomUUID()} label="Save contribution"><label>Family member<select name="user_id" defaultValue={family.actor_id}>{activePayers.filter((member) => family.access.can_manage || member.user_id === family.actor_id).map((member) => <option value={member.user_id} key={member.user_id}>{member.display_name}</option>)}</select></label><input name="currency" type="hidden" value={family.currency} /><label>Amount ({family.currency})<input name="amount" inputMode="decimal" required placeholder="30000.00" /></label><label>Date<input name="contributed_on" type="date" required /></label><label>Transfer or record reference (optional)<input name="reference" maxLength={120} /></label><label>Note<textarea name="note" required maxLength={2000} rows={2} /></label></FamilyForm></Section>}
    <Section id="family-allocations" title="Share expenses" description="Agree how much each person will cover for a checked bill charge. This is a family plan only: it does not charge anyone, pay the hospital or decide what insurance covers.">
      {!family.expenses.length && <p>No recorded charges yet. Review and accept bill charges first.</p>}
      {family.expenses.map((expense) => <details className={styles.entry} key={expense.id}><summary>{expense.description} · <MoneyText value={expense.amount} currency={family.currency} /></summary><p>Unallocated: <MoneyText value={expense.unallocated} currency={family.currency} /> · {expense.status.toLowerCase().replaceAll("_", " ")}</p>{expense.allocation_stale && <p>Previous allocation is stale because the charge changed. Its history is preserved; review a replacement allocation.</p>}{expense.shares.map((share) => <p key={share.user_id}>{name(share.user_id)}: <MoneyText value={share.amount} currency={family.currency} /></p>)}{family.access.can_review && expense.status === "ACCEPTED" && <FamilyForm caseId={caseId} command="allocate" targetId={expense.id} requestId={randomUUID()} label="Save cost split"><input type="hidden" name="source_fingerprint" value={expense.source_fingerprint} /><fieldset><legend>Shares in {family.currency}; leave blank for no allocation</legend>{activePayers.map((member) => <label key={member.user_id}>{member.display_name}<input name={`share:${member.user_id}`} inputMode="decimal" defaultValue={expense.shares.find((share) => share.user_id === member.user_id)?.amount ?? ""} /></label>)}</fieldset><label>Allocation note<textarea name="note" required maxLength={2000} rows={2} /></label></FamilyForm>}</details>)}
      {!!family.allocation_history.length && <details><summary>Previous cost splits</summary>{family.allocation_history.map((plan) => <div className={styles.entry} key={plan.id}><p>Version {plan.version} · {formatDateTime(plan.created_at)} · {plan.note}</p>{plan.shares.map((share) => <p key={share.user_id}>{name(share.user_id)}: <MoneyText value={share.amount} currency={family.currency} /></p>)}</div>)}</details>}
    </Section>
    <Section id="family-notifications" title="Important changes for you" description="Important updates appear here. No email or phone message is sent.">{!family.notifications.length && <p>No notifications yet.</p>}{family.notifications.map((notice) => <div className={styles.entry} key={notice.id}><p>{activityLabel(notice.event_type)} · {notice.actor_label} · {formatDateTime(notice.created_at)}</p>{notice.read_at ? <p className={styles.muted}>Read</p> : <FamilyForm caseId={caseId} command="read" targetId={notice.id} requestId={randomUUID()} label="Mark as read" />}</div>)}</Section>
    <Section id="family-history" title="Shared financial history"><details open><summary>Contribution history ({family.ledger.length})</summary>{family.ledger.map((entry) => <div className={styles.entry} key={entry.id}><p>{name(entry.user_id)} · {entry.entry_type === "REVERSAL" ? "Correction" : "Contribution"} · <MoneyText value={entry.amount} currency={entry.currency} /> · {entry.contributed_on}</p><p>{entry.note}{entry.reference ? ` · Reference: ${entry.reference}` : ""}</p>{family.access.can_manage && entry.entry_type === "CONTRIBUTION" && !reversed.has(entry.id) && <details><summary>Correct this contribution</summary><FamilyForm caseId={caseId} command="reverse" targetId={entry.id} requestId={randomUUID()} label="Save correction"><label>Correction reason<textarea name="note" required maxLength={2000} rows={2} /></label></FamilyForm></details>}</div>)}</details><details><summary>Shared episode activity ({family.history.length})</summary><ol>{[...family.history].reverse().map((event) => <li key={event.id}>{activityLabel(event.event_type)} · {event.actor_label} · {formatDateTime(event.created_at)}</li>)}</ol></details></Section>
  </div>;
}
