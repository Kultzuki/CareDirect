import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { EvidenceRef, MoneyText, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { ApiError, apiGet, seg } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { RESPONSE_LABELS, type ProviderPortalOut } from "@/lib/provider-types";
import { isUploadToken } from "@/lib/validation";

import { ProviderForm } from "./provider-form";
import styles from "./provider.module.css";

export const metadata: Metadata = { title: "Provider response", referrer: "no-referrer", robots: { index: false, follow: false } };

export default function ProviderPage({ params }: { params: Promise<{ token: string }> }) {
  return <Suspense fallback={<div className={styles.skeleton} aria-label="Loading provider question" />}><ProviderContent params={params} /></Suspense>;
}

function Unavailable() { return <div className={styles.page}><PageHeader title="This link can’t be used" /><Notice tone="warning"><p>This provider link is expired, revoked or unavailable. Ask the family payer for a new link.</p></Notice></div>; }

async function ProviderContent({ params }: { params: Promise<{ token: string }> }) {
  await connection();
  const { token } = await params;
  if (!isUploadToken(token)) return <Unavailable />;
  let portal: ProviderPortalOut;
  try { portal = await apiGet<ProviderPortalOut>(`/api/provider/respond/${seg(token)}`); }
  catch (error) {
    if (error instanceof ApiError && error.status !== 503) return <Unavailable />;
    return <div className={styles.page}><PageHeader title="The question is unavailable right now" /><Notice tone="error"><p>Try reloading in a moment. Your link has not been used.</p></Notice></div>;
  }
  return <div className={styles.page}>
    <PageHeader title="Clarify a bill charge" meta={<p>{portal.provider_name} billing team</p>} />
    <p>You have access to one billing question. Your response is a proposal; the family payer reviews any change.</p>
    <div className={styles.paper}>
      <section aria-labelledby="provider-question" className={styles.question}><h2 id="provider-question">The family’s question</h2><blockquote>{portal.question}</blockquote></section>
      <section aria-labelledby="provider-charge" className={styles.charge}>
        <h2 id="provider-charge">{portal.line.description_raw}</h2>
        <dl><dt>Original charge</dt><dd><MoneyText value={portal.line.line_total} currency={portal.currency} /></dd><dt>Currently recognized</dt><dd><MoneyText value={portal.line.recognized_amount} currency={portal.currency} /></dd></dl>
        <p>{portal.flag.explanation}</p>
        {portal.line.source_page ? <EvidenceRef page={portal.line.source_page} snippet={portal.line.source_text} /> : portal.line.source_text ? <blockquote>{portal.line.source_text}</blockquote> : <p className={styles.meta}>No source excerpt was supplied for this charge.</p>}
      </section>
      {portal.state === "RESPONDED" && portal.response ? <section className={styles.response} aria-labelledby="response-recorded"><StatusBadge tone="provider-confirmed">Response recorded</StatusBadge><h2 id="response-recorded">{RESPONSE_LABELS[portal.response.response_type]}</h2><p>{portal.response.response_text}</p><p className={styles.meta}>Recorded {formatDateTime(portal.response.responded_at)}. The payer will review it. This link cannot submit another response.</p></section> : <ProviderForm token={token} currentAmount={portal.line.recognized_amount} currency={portal.currency} />}
    </div>
    <p className={styles.meta}>Private link · expires {formatDateTime(portal.expires_at)}. Use sample documents and test payments only.</p>
  </div>;
}
