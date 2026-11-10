import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { PaymentApproval, PaymentCommand } from "@/components/case/PaymentControls";
import { ButtonLink, MoneyText, Notice, PageHeader, Section, StatusBadge } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { formatDateTime } from "@/lib/format";
import { attempt } from "@/lib/load";
import { PAYMENT_STATES, sandboxCheckoutUrl, type PaymentWorkspace } from "@/lib/payment-types";
import type { CaseDetailOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

import styles from "@/components/case/payments.module.css";

export const metadata: Metadata = { title: "Payments", robots: { index: false, follow: false }, referrer: "no-referrer" };

export default function PaymentsPage({ params }: { params: Promise<{ caseId: string }> }) {
  return <Suspense fallback={<div className={styles.skeleton} aria-label="Loading payment record" />}><Payments params={params} /></Suspense>;
}

async function Payments({ params }: { params: Promise<{ caseId: string }> }) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    const [detail, workspace] = await Promise.all([
      apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId: payer.id }),
      apiGet<PaymentWorkspace>(`/api/cases/${seg(caseId)}/payments`, { actorId: payer.id }),
    ]);
    return { payer, detail, workspace };
  });
  if (!loaded.ok) { if (loaded.error.status === 404) notFound(); return <ApiProblem error={loaded.error} />; }
  if (!loaded.value) return <NoDemoPayer />;
  const { payer, detail, workspace } = loaded.value;
  const { preview, approval, invoice, operation } = workspace;
  const composition = operation && approval ? approval.snapshot : preview;
  const state = PAYMENT_STATES[workspace.state] ?? { title: "Payment record requires review", explanation: "Refresh the record or ask the demo owner to review this attempt before proceeding." };
  const checkoutUrl = sandboxCheckoutUrl(invoice?.checkout_url);
  const uncertain = ["UNCERTAIN", "RECONCILIATION_REQUIRED"].includes(workspace.state);
  return <div className={styles.page}>
    <div className={styles.intro}>
    <PageHeader title="Payments" back={{ href: `/cases/${caseId}`, label: "Case overview" }} meta={<p>{detail.patient_alias} · {preview.provider_label}</p>} />
    <DemoIdentityNote name={payer.display_name} />{!workspace.can_approve && <p>Your episode role can view this record. Payment actions require the owner to grant payment approval permission.</p>}
    <ol className={styles.steps} aria-label="Payment review stages"><li><strong>Review the evidence</strong><small>{detail.buckets.pending_review === "0.00" ? "Charges reviewed; check open questions" : "Some charges await review"}</small></li><li><strong>Approve an exact amount</strong><small>{approval ? approval.current ? "Approval recorded for current evidence" : "Previous approval needs review" : "A permitted payer must approve"}</small></li><li><strong>Verify the payment</strong><small>{workspace.state === "PAID" ? "Verified against PayPal records" : "Only an authoritative check confirms payment"}</small></li></ol>
    <nav className={styles.nav} aria-label="Case"><Link href={`/cases/${caseId}`}>Overview</Link><Link href={`/cases/${caseId}?tab=documents`}>Bill &amp; evidence</Link><Link href={`/cases/${caseId}#questions`}>Questions</Link><Link href={`/cases/${caseId}?tab=payments`} aria-current="page">Payments</Link><Link href={`/cases/${caseId}#activity`}>Activity</Link></nav>
    </div>
    <div className={styles.columns}>
      <Section id="invoice-composition" title="What this invoice includes" description={operation ? "The amounts and account saved with this payment approval. Current payment status and amount due appear below." : "Prior evidence and the amount collected now are separate parts of the same invoice."}>
        <div className={styles.sheet}><dl className={styles.composition}>
          <div><dt>Invoice total<small>Accepted charges after agreed adjustments.</small></dt><dd><MoneyText value={composition.invoice_total} currency={composition.currency} /></dd></div>
          <div><dt>Linked prior payments<small>Earlier payments already recorded. They are not counted twice.</small></dt><dd><MoneyText value={composition.external_total} currency={composition.currency} /></dd></div>
          <div className={styles.collect}><dt>{operation ? "Approved collection" : "Collect now"}</dt><dd><MoneyText value={composition.collect_amount} currency={composition.currency} /></dd></div>
          <div><dt>Held for clarification<small>Excluded from collection while the question is open.</small></dt><dd><MoneyText value={composition.queried} currency={composition.currency} /></dd></div>
        </dl>
        {composition.external_payments.length ? <details><summary>Linked external payment evidence ({composition.external_payments.length})</summary><ul className={styles.list}>{composition.external_payments.map((payment) => <li key={payment.id}><MoneyText value={payment.amount} currency={payment.currency} /> · {payment.paid_on} · reference ending {payment.reference_suffix || "unavailable"}</li>)}</ul></details> : <p className={styles.muted}>No prior external payments linked.</p>}
        <details><summary>Details saved with this approval</summary><p className={`${styles.muted} ${styles.break}`}>{preview.state_fingerprint}</p></details></div>
      </Section>
      <Section id="receiving-account" title="Receiving account" description="Check which test account receives this invoice.">
        <div className={styles.sheet}><StatusBadge tone={preview.account_binding.status === "VERIFIED" ? "confirmed" : "needs-review"}>{preview.account_binding.status === "VERIFIED" ? "test account evidence checked" : "Account check required"}</StatusBadge><p>{preview.account_binding.basis}</p>
          {preview.account_binding.merchant_ref_suffix ? <p className={styles.muted}>Merchant reference ending {preview.account_binding.merchant_ref_suffix}</p> : null}
          {workspace.can_approve && !operation ? <PaymentCommand caseId={caseId} command="account-binding" label={preview.account_binding.status === "VERIFIED" ? "Recheck test account evidence" : "Check test account evidence"} /> : null}
        </div>
      </Section>
    </div>
    {workspace.blockers.length ? <div id="approval-blockers"><Notice tone="warning" title="Before payment can proceed"><ul className={styles.list}>{workspace.blockers.map((blocker, index) => <li key={`${index}-${blocker}`}>{blocker}</li>)}</ul><p><Link href={`/cases/${caseId}#attention`}>Review case attention queue</Link> · <Link href={`/cases/${caseId}?tab=documents`}>Review bill &amp; evidence</Link></p></Notice></div> : null}
    <Section id="payment-approval" title="Your payment approval" description="An approval binds the exact amount, currency, invoice composition, account evidence and case state.">
      <div className={styles.sheet}>
        {approval ? <><StatusBadge tone={approval.current ? "confirmed" : "needs-review"}>{approval.current ? "Current approval recorded" : operation ? "Approval preserved with this attempt" : "Earlier approval is stale"}</StatusBadge><dl className={styles.record}><dt>Approved collection</dt><dd><MoneyText value={approval.approved_amount} currency={approval.currency} /></dd><dt>Purpose</dt><dd>{approval.purpose}</dd><dt>Approved by</dt><dd>{approval.approved_by}</dd><dt>Approved at</dt><dd>{formatDateTime(approval.approved_at)}</dd></dl>
          <details><summary>Saved approved amounts and account</summary><dl className={styles.record}><dt>Invoice total</dt><dd><MoneyText value={approval.snapshot.invoice_total} currency={approval.snapshot.currency} /></dd><dt>Linked prior payments</dt><dd><MoneyText value={approval.snapshot.external_total} currency={approval.snapshot.currency} /></dd><dt>Approved collection</dt><dd><MoneyText value={approval.snapshot.collect_amount} currency={approval.snapshot.currency} /></dd><dt>Provider</dt><dd>{approval.snapshot.provider_label}</dd><dt>Account evidence</dt><dd>{approval.snapshot.account_binding.basis}</dd><dt>Merchant reference</dt><dd>Ending {approval.snapshot.account_binding.merchant_ref_suffix}</dd><dt>Bound case state</dt><dd>{approval.state_fingerprint}</dd></dl>{approval.snapshot.external_payments.length ? <ul className={styles.list}>{approval.snapshot.external_payments.map((payment) => <li key={payment.id}><MoneyText value={payment.amount} currency={payment.currency} /> · {payment.paid_on} · reference ending {payment.reference_suffix}</li>)}</ul> : null}</details>
          {!approval.current && !operation ? <p>Case details changed after this approval. Review the current composition and approve again before creating an invoice.</p> : null}</> : <p>No payment approval has been recorded.</p>}
        {workspace.can_approve && !operation && !approval?.current ? <PaymentApproval key={preview.state_fingerprint} caseId={caseId} workspace={workspace} /> : null}
        {workspace.can_approve && approval?.current && !operation && workspace.state === "APPROVED" ? <PaymentCommand caseId={caseId} command="invoice" approvalId={approval.id} label="Create approved test invoice"><p>This creates and prepares one invoice in the configured provider test account. The case’s financial inputs are then locked while this attempt is reconciled.</p></PaymentCommand> : null}
      </div>
    </Section>
    <Section id="payment-status" title="Payment status" description="Only an authoritative backend check can confirm payment.">
      <div className={styles.sheet}><StatusBadge tone={workspace.state === "PAID" ? "paypal-confirmed" : uncertain ? "needs-review" : "info"}>{state.title}</StatusBadge><p>{state.explanation}</p>
        {operation ? <p className={styles.muted}>Operation stage: {operation.stage.toLowerCase().replaceAll("_", " ")}. Financial changes are locked for this attempt.</p> : null}
        {operation?.paypal_invoice_id && !invoice ? <p className={styles.break}><strong>Existing test invoice:</strong> {operation.paypal_invoice_id}</p> : null}
        {operation?.stage === "RECOVERY_INCOMPLETE" ? <Notice tone="warning" title="Existing invoice needs checking"><p>The invoice was found, but its draft or linked external-payment records are incomplete. Ask the demo owner to review this existing invoice in the provider’s test account. Do not create another invoice. After checking the invoice, check its payment status here.</p></Notice> : null}
        {invoice ? <dl className={styles.record}><dt>Invoice reference</dt><dd>{invoice.paypal_invoice_id}</dd><dt>PayPal invoice state</dt><dd>{invoice.status}</dd><dt>Amount due</dt><dd><MoneyText value={invoice.amount_due} currency={invoice.currency} /></dd><dt>Last authoritative check</dt><dd>{invoice.last_verified_at ? formatDateTime(invoice.last_verified_at) : "Not verified yet"}</dd></dl> : null}
        {checkoutUrl && ["READY", "AWAITING_BUYER"].includes(workspace.state) ? <div className={styles.actions}><ButtonLink href={checkoutUrl} target="_blank" rel="noopener noreferrer">Open existing test invoice</ButtonLink><p className={styles.muted}>Opens PayPal test account in a new tab. Return here to verify after checkout.</p></div> : null}
        {workspace.can_approve && (operation || invoice) ? <PaymentCommand caseId={caseId} command="verify" label="Verify current PayPal state" /> : null}
        {workspace.can_approve && uncertain && !invoice && !operation?.paypal_invoice_id ? <PaymentCommand caseId={caseId} command="recover" label="Recover existing invoice" /> : null}
        <p><Link href={`/cases/${caseId}?tab=payments`}>Refresh payment record</Link></p>
      </div>
    </Section>
    {workspace.transactions.length ? <Section id="payment-transactions" title="Reconciled payment record" description="External evidence stays distinct from a PayPal-verified transaction."><ul className={styles.list}>{workspace.transactions.map((transaction) => <li key={transaction.id}><p><strong>{transaction.source === "PAYPAL" ? "PayPal transaction" : "Linked external evidence"}</strong> · <MoneyText value={transaction.amount} currency={transaction.currency} /></p><p>{transaction.status} · reference ending {transaction.reference_suffix}</p>{transaction.verified_at ? <p className={styles.muted}>{formatDateTime(transaction.verified_at)}</p> : null}</li>)}</ul></Section> : null}
  </div>;
}
