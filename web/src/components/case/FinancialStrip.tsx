import { MoneyText } from "@/components/ui";
import type { BucketsOut } from "@/lib/types";

import styles from "./workspace.module.css";

export function FinancialStrip({ buckets }: { buckets: BucketsOut }) {
  return (
    <section className={styles.financial} aria-label="Case financial summary" data-testid="financial-summary">
      <dl className={styles.original}>
        <div><dt>Original bill</dt><dd><MoneyText value={buckets.original_bill_total} currency={buckets.currency} /></dd></div>
        <div><dt>Agreed adjustments</dt><dd><MoneyText value={buckets.adjustments} currency={buckets.currency} /></dd></div>
        <div><dt>Net recognized total</dt><dd><MoneyText value={buckets.net_bill_total} currency={buckets.currency} /></dd></div>
      </dl>
      <dl className={styles.buckets}>
        <div><dt>{buckets.insurance_present ? "Hospital balance before insurance is split" : "Payable now"}</dt><dd><MoneyText value={buckets.payable_now} currency={buckets.currency} /></dd><dd className={styles.bucketDescription}><p>{buckets.insurance_present ? "Includes insurer responsibility; not the family's payable amount. Open Insurance and family share." : "Unpaid and outside open questions"}</p></dd></div>
        <div><dt>Queried</dt><dd><MoneyText value={buckets.queried} currency={buckets.currency} /></dd><dd className={styles.bucketDescription}><p>Held while the family asks for clarity</p></dd></div>
        <div><dt>Already paid</dt><dd><MoneyText value={buckets.already_paid} currency={buckets.currency} /></dd><dd className={styles.bucketDescription}><p>Matched external or verified payments</p></dd></div>
      </dl>
      {buckets.pending_review !== "0.00" ? <p className={styles.pending}>Includes <MoneyText value={buckets.pending_review} currency={buckets.currency} /> still awaiting your review. These totals are not a payment approval.</p> : <p className={styles.pending}>Payment always requires a separate approval of the exact amount.</p>}
    </section>
  );
}
