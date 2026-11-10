"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { createDemoRun } from "@/app/cases/demo-actions";
import { Button, Notice } from "@/components/ui";
import styles from "./demo.module.css";

export function DemoRuns() {
  const [mode, setMode] = useState("EMPTY");
  const [result, setResult] = useState<{caseId?: string; caseReference?: string; error?: string}>({});
  const [pending, startTransition] = useTransition();
  const [started,setStarted] = useState(false);
  const [request,setRequest] = useState<{id:string;mode:string}|null>(null);
  function start() {
    if (pending || result.caseId) return;
    let current = request;
    if (!current) {
      try {
        const saved = JSON.parse(sessionStorage.getItem("caredirect-demo-run") ?? "null");
        if (saved && typeof saved.id === "string" && ["EMPTY","PREPARED"].includes(saved.mode)) current = {id:saved.id,mode:saved.mode};
      } catch { /* Browser storage may be unavailable; in-memory recovery still works. */ }
      current ??= {id:crypto.randomUUID(),mode};
      try { sessionStorage.setItem("caredirect-demo-run",JSON.stringify(current)); } catch { /* No private evidence is stored. */ }
      setRequest(current);
    }
    setStarted(true);
    const submitted = current;
    startTransition(async () => setResult(await createDemoRun(submitted.mode, submitted.id)));
  }
  return <section id="demo" className={styles.demo} aria-labelledby="demo-heading">
    <div><h2 id="demo-heading">Start a fresh demo</h2><p>Create a new sample care record in US dollars. Your earlier records stay saved.</p><p className={styles.muted}>Prepared sample details. No real medical records or money.</p></div>
    <div className={styles.run}>
      <label htmlFor="demo-mode">Start with</label><select id="demo-mode" value={mode} disabled={pending || started} onChange={(event) => setMode(event.target.value)}><option value="EMPTY">Empty case — upload the samples yourself</option><option value="PREPARED">Samples uploaded — begin human review</option></select>
      <p className={styles.muted}>Prepared runs add a bill, estimate and receipt with labelled recorded extraction. Review, corrections, provider decisions and payment approval remain yours.</p>
      {result.caseId ? <Notice tone="success" title="Fresh case created"><p><Link href={`/cases/${result.caseId}?tab=documents`}>Open {result.caseReference} to review the evidence</Link></p><Button variant="quiet" onClick={() => { setRequest(null); setStarted(false); setResult({}); try {sessionStorage.removeItem("caredirect-demo-run");} catch {} }}>Prepare another fresh run</Button></Notice> : <Button onClick={start} pending={pending}>{result.error ? "Recover this demo run" : "Create sample care record"}</Button>}
      {result.error ? <Notice tone="warning" title="Check the demo run"><p>{result.error}</p></Notice> : null}
    </div>
    <div className={styles.samples}><h3>Sample documents to try</h3><p>Original bill USD250, prior receipt USD40. A questioned USD20 charge can become an agreed credit: net USD230, then USD190 to collect.</p><ul><li><a href="/demo/samples/usd_bill.pdf" download>Bill PDF — USD250</a></li><li><a href="/demo/samples/usd_estimate.pdf" download>Estimate PDF — USD250</a></li><li><a href="/demo/samples/usd_receipt.pdf" download>Prior receipt PDF — USD40</a></li><li><a href="/demo/samples/usd_bill.png" download>Readable bill image</a></li></ul></div>
  </section>;
}
