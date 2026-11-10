"use client";



import Link from "next/link";

import { useState } from "react";

import { CaseStatusBadge } from "@/components/CaseStatusBadge";

import { EmptyState, MoneyText, Notice } from "@/components/ui";

import type { DashboardOut } from "@/lib/dashboard-types";

import { paymentStateLabel } from "@/lib/dashboard-types";

import { formatDateTime } from "@/lib/format";

import styles from "./dashboard.module.css";



const VIEWS = ["All cases", "Needs attention", "Provider replies", "Payment attempts"] as const;

type View = typeof VIEWS[number];



export function Dashboard({ dashboard }: { dashboard: DashboardOut }) {

  const [view, setView] = useState<View>("All cases");

  const [page,setPage] = useState(0);

  const inconsistent = dashboard.cases.filter(item=>!item.buckets.consistent || !item.buckets.invariant_holds);

  const shown = dashboard.cases.filter((item) => view === "Needs attention" ? item.attention_count > 0 : view === "Provider replies" ? item.pending_responses > 0 : view === "Payment attempts" ? item.payment_state !== "NOT_STARTED" && item.payment_state !== "APPROVAL_REQUIRED" : true);

  const pages = Math.max(1,Math.ceil(shown.length/6));

  const currentPage = Math.min(page,pages-1);

  const visible = shown.slice(currentPage*6,currentPage*6+6);

  return <div className={styles.dashboard}>

    <section aria-labelledby="balances-heading" className={styles.balances}>

      <div className={styles.sectionHead}><h2 id="balances-heading">The family record</h2><p>These are hospital bill totals, grouped by currency. They include amounts insurance may cover. Open a care record’s Insurance tab to see the family’s share.</p></div>

      {inconsistent.length ? <Notice tone="warning" title="Some records need checking"><p>These aggregate figures include cases with unresolved accounting checks. Review each case’s issues before treating any balance as ready for approval.</p></Notice> : null}

      {dashboard.totals.length ? dashboard.totals.map((total) => <div className={styles.currency} key={total.currency}>

        <h3>{total.currency}</h3><dl className={styles.buckets}>

          <div><dt>Unpaid bill balance</dt><dd><MoneyText value={total.payable_now} currency={total.currency} /></dd></div>

          <div><dt>Queried</dt><dd><MoneyText value={total.queried} currency={total.currency} /></dd></div>

          <div><dt>Already paid</dt><dd><MoneyText value={total.already_paid} currency={total.currency} /></dd></div>

        </dl><p className={styles.review}>Within payable now, <MoneyText value={total.pending_review} currency={total.currency} /> still needs charge review.</p>

      </div>) : <p>No charges have been added yet.</p>}

    </section>

    <section aria-labelledby="cases-heading">

      <div className={styles.sectionHead}><h2 id="cases-heading">Your cases</h2><p>Open the source, resolve a question, or check a payment.</p></div>

      <div className={styles.filters} aria-label="Case views">{VIEWS.map((label) => <button key={label} type="button" aria-pressed={view === label} onClick={() => {setView(label);setPage(0);}}>{label}</button>)}</div>

      <p className={styles.result} role="status">{shown.length} {shown.length === 1 ? "case" : "cases"} in {view.toLowerCase()}</p>

      {shown.length ? <ul className={styles.caseList} data-testid="case-list">{visible.map((item) => <li key={item.id} className={styles.caseRow}>

        <div className={styles.identity}>
          <h3>
            <Link
              href={`/cases/${item.id}`}
              aria-label={`${item.episode_title ? `${item.episode_title} (${item.case_reference})` : item.case_reference}`}
              title={item.episode_title || item.case_reference}
            >
              {item.episode_title || (/^DEMO-[EP]-[a-f0-9]{32}$/i.test(item.case_reference) ? `${item.case_reference.slice(0, 15)}…` : item.case_reference)}
            </Link>
          </h3>
          <p>{item.patient_alias}</p>
          {item.episode_title ? <p className={styles.muted}>{item.case_reference}</p> : null}
          <p className={styles.muted}>{item.provider_name || item.provider_names.join(", ") || "Provider not supplied yet"}</p>
          <CaseStatusBadge status={item.status} />
          {!item.buckets.consistent || !item.buckets.invariant_holds ? <p>These amounts need checking. <Link href={`/cases/${item.id}`}>Check the amounts</Link></p> : null}
        </div>

        <dl className={styles.caseAmounts}><div><dt>{item.buckets.insurance_present ? "Unallocated hospital balance" : "Payable now"}</dt><dd><MoneyText value={item.buckets.payable_now} currency={item.currency} /></dd></div><div><dt>Queried</dt><dd><MoneyText value={item.buckets.queried} currency={item.currency} /></dd></div><div><dt>Already paid</dt><dd><MoneyText value={item.buckets.already_paid} currency={item.currency} /></dd></div></dl>
        {item.buckets.insurance_present && <p><Link href={`/cases/${item.id}?tab=insurance`}>Review insurer and family responsibility</Link></p>}

        <div className={styles.next}><p>{item.pending_responses > 0 ? <Link href={`/cases/${item.id}#questions`}>{item.pending_responses} provider {item.pending_responses === 1 ? "reply" : "replies"} to review</Link> : item.open_questions > 0 ? <Link href={`/cases/${item.id}#questions`}>{item.open_questions} open {item.open_questions === 1 ? "question" : "questions"}</Link> : "No open billing questions"}</p>{item.documents_to_review > 0 ? <Link href={`/cases/${item.id}?tab=documents`}>{item.documents_to_review} source {item.documents_to_review===1?"document":"documents"} to review</Link> : null}<Link href={`/cases/${item.id}?tab=payments`}>{paymentStateLabel(item.payment_state)}</Link>{item.latest_activity_at ? <p className={styles.muted}>Updated {formatDateTime(item.latest_activity_at)}</p> : null}<Link href={`/cases/${item.id}?tab=history`}>Activity &amp; evidence</Link></div>

      </li>)}</ul> : <EmptyState title={dashboard.cases.length ? "No cases in this view" : "Start a sample care record"}><p>{dashboard.cases.length ? "Choose another view to see the rest of the family record." : "Choose a demo run below to begin with readable sample documents."}</p></EmptyState>}

      {pages>1 ? <nav className={styles.pagination} aria-label="Case history pages"><button type="button" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous cases</button><p role="status">Showing {currentPage*6+1}–{Math.min(currentPage*6+6,shown.length)} of {shown.length}</p><button type="button" disabled={currentPage===pages-1} onClick={()=>setPage(currentPage+1)}>Next cases</button></nav> : null}

    </section>

  </div>;

}

