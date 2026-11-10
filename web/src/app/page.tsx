import { connection } from "next/server";
import { Suspense } from "react";

import { ButtonLink } from "@/components/ui";
import { apiBaseUrl } from "@/lib/config";

import styles from "./home.module.css";

async function apiIsHealthy(): Promise<boolean> {
  try {
    const res = await fetch(`${apiBaseUrl}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: unknown };
    return body.status === "ok";
  } catch {
    return false;
  }
}

async function ApiStatus() {
  // Render at request time so the status is never baked in at build time.
  await connection();
  const healthy = await apiIsHealthy();
  return <p data-testid="api-status">API: {healthy ? "ok" : "unavailable"}</p>;
}

export default function Home() {
  return (
    <div className={styles.home}>
      <h1>CareDirect</h1>
      <p className={styles.lead}>Review the bill. Resolve the questions. Approve the exact amount.</p>
      <p>
        Keep the source bill, provider replies and payment evidence together in one family
        record. Try it with sample documents only. Payments use test accounts, so no real money is sent.
      </p>
      <div className={styles.actions}>
        <ButtonLink href="/cases">Explore the demo</ButtonLink>
      </div>
      <section className={styles.path} aria-label="CareDirect review workflow">
        {[["Keep one care episode", "Connect the treatment timeline, bills and source documents."], ["Understand the costs", "Compare estimates, possible duplicates and insurance components."], ["Work as a family", "Track contributions and agree how to share expenses."], ["Approve deliberately", "Review the exact amount and verify the payment separately."]].map(([title, description], index) => <article key={title}><span aria-hidden="true">{index + 1}</span><h2>{title}</h2><p>{description}</p></article>)}
      </section>
      <Suspense fallback={<p data-testid="api-status-loading">API: checking</p>}>
        <ApiStatus />
      </Suspense>
    </div>
  );
}
