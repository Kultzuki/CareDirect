"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import type { DashboardOut } from "@/lib/dashboard-types";
import styles from "./studio.module.css";

const StudioCanvas = dynamic(() => import("./StudioCanvas"), { ssr: false, loading: () => <p role="status">Opening the case table…</p> });

export function StudioView({dashboard,licenseKey}: {dashboard:DashboardOut; licenseKey?:string}) {
  const [view,setView] = useState("all");
  const cases = dashboard.cases.filter((item) => view === "questions" ? item.open_questions > 0 : view === "replies" ? item.pending_responses > 0 : view === "payments" ? !["NOT_STARTED","APPROVAL_REQUIRED"].includes(item.payment_state) : true);
  const needsReconciliation = dashboard.cases.some(item=>!item.buckets.consistent || !item.buckets.invariant_holds);
  return <div className={styles.view}><label htmlFor="studio-view">Case table view</label><select id="studio-view" value={view} onChange={(event)=>setView(event.target.value)}><option value="all">All authorized cases</option><option value="questions">Open billing questions</option><option value="replies">Provider replies to review</option><option value="payments">Payment attempts</option></select><p role="status">{cases.length} cases. Explore the family record. Review and approve payments in the case workspace.</p><div className={styles.canvas} aria-label="Read-only case analysis table"><StudioCanvas cases={cases} totals={dashboard.totals} needsReconciliation={needsReconciliation} licenseKey={licenseKey} /></div></div>;
}
