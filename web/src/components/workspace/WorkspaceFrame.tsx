"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import styles from "./WorkspaceFrame.module.css";

const tabs = [
  { key: "overview", route: "", label: "Overview", description: "See the bill, amounts already paid and questions that need an answer.", next: "Start with any open bill questions before approving a payment." },
  { key: "timeline", route: "episode", label: "Care timeline", description: "See visits, tests and bills in date order for one treatment.", next: "Choose a date or document to see what happened and check its details." },
  { key: "comparison", route: "comparison", label: "Bill comparison", description: "Compare the hospital’s first estimate with its final bill to see what changed.", next: "Look at added charges and price changes. Open the original document if something looks wrong." },
  { key: "duplicates", route: "duplicates", label: "Repeated charges", description: "Find services that may have been charged twice, even under different names or on different bills.", next: "Compare both entries and ask the hospital to explain. A possible match does not remove a charge." },
  { key: "insurance", route: "insurance", label: "Insurance", description: "See what insurance approved, what it actually paid and what the family may still need to pay.", next: "Compare the bill with the insurance documents. Pending or rejected claims are not automatically the family’s debt." },
  { key: "family", route: "family", label: "Family money", description: "Record each person’s contribution, share costs and choose who can review bills or approve payments.", next: "These are shared records only. Adding a contribution here does not send money or pay the hospital." },
  { key: "documents", route: "review", label: "Documents", description: "Keep bills, receipts and insurance papers together. Check the details read from each document.", next: "Add a sample document, check its details against the original and save your review." },
  { key: "payments", route: "payments", label: "Payments", description: "Check the exact amount before approving a payment, then check whether it went through.", next: "This demo uses test payments. A family member with payment permission must approve the amount first." },
  { key: "history", route: "evidence", label: "History", description: "See who changed what, when it happened and which documents support each decision.", next: "Open an entry to see its details, or download the full record." },
];

export function WorkspaceFrame({ children }: { children: ReactNode }) {
  const path = usePathname();
  const search = useSearchParams();
  const match = path.match(/^\/cases\/([a-f0-9-]{36})(?:\/|$)/);
  const caseId = match?.[1];
  const portal = path.startsWith("/upload/") || path.startsWith("/provider/") || path.startsWith("/family/join/");
  const section = caseId ? path.slice(`/cases/${caseId}`.length).split("/")[1] : undefined;
  const active = tabs.find(tab => section ? tab.route === section : tab.key === (search.get("tab") ?? "overview")) ?? tabs[0];
  return <div className={portal ? styles.portal : styles.frame}>
    {!portal && <aside className={styles.sidebar} aria-label="Workspace navigation">
      <div className={styles.identity}><span className={styles.symbol} aria-hidden="true">＋</span><div><strong>Your care record</strong><small>Bills and family, together.</small></div></div>
      <nav aria-label="Your workspace"><Link className={styles.navItem} href="/cases" aria-current={path === "/cases" ? "page" : undefined}>All care records</Link><Link className={styles.navItem} href="/cases/studio" aria-current={path === "/cases/studio" ? "page" : undefined}>Family overview</Link></nav>
      <div className={styles.sidebarHelp}><strong>{caseId ? "One treatment, one place" : "Start a care record"}</strong><p>{caseId ? "Use the tabs to check bills, understand insurance and work together as a family." : "Keep all the bills and documents for one treatment together."}</p>{!caseId && <Link href="/cases#new-episode">Start a care record</Link>}</div>
      <p className={styles.footer}>Demo with sample records.<br />Payments are for testing only.</p>
    </aside>}
    <main id="main" className={styles.content}>
      {caseId && <div className={styles.workspace}>
        <div className={styles.workspaceTitle}><strong>Your care workspace</strong><span>Choose what you want to check</span></div>
        <nav className={styles.tabs} aria-label="Care record sections">{tabs.map(tab => <Link key={tab.key} href={`/cases/${caseId}?tab=${tab.key}`} aria-current={active.key === tab.key ? "page" : undefined}>{tab.label}</Link>)}</nav>
        <section className={styles.guide} aria-label={`About ${active.label.toLowerCase()}`}><strong>What you can do here</strong><p>{active.description}</p><p><b>Next step:</b> {active.next}</p></section>
      </div>}
      {children}
    </main>
  </div>;
}
