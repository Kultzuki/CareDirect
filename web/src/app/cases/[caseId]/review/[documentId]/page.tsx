import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { ExtractionSheet } from "@/components/extraction/ExtractionSheet";
import { SourcePreview } from "@/components/extraction/SourcePreview";
import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { ButtonLink, EmptyState, MoneyText, Notice, PageHeader } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import {
  documentTypeLabel,
  formatDateTime,
  lineCountLabel,
  mimeLabel,
  pageCountLabel,
} from "@/lib/format";
import { attempt } from "@/lib/load";
import { displayCurrency, toReviewView } from "@/lib/review-view";
import type { CaseDetailOut, DocumentOut, ExtractionViewOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

import { ReviewWorkspace } from "./review-form";
import styles from "./review.module.css";

export const metadata: Metadata = { title: "Check document details" };

export default function DocumentReviewPage(
  props: PageProps<"/cases/[caseId]/review/[documentId]">,
) {
  return (
    <Suspense fallback={<div className={styles.skeleton} aria-hidden="true" />}>
      <DocumentReview params={props.params} />
    </Suspense>
  );
}

function PromotedNotice({ view, detail }: { view: ExtractionViewOut; detail: CaseDetailOut }) {
  const billId = view.promoted_to?.bill_id ?? null;
  const paymentId = view.promoted_to?.external_payment_id ?? null;
  const bill = billId ? detail.bills.find((b) => b.id === billId) : undefined;
  const payment = paymentId ? detail.external_payments.find((p) => p.id === paymentId) : undefined;
  return (
    <Notice tone="success" title="Added to case" testId="promoted-notice">
      {bill ? (
        <p>
          {lineCountLabel(bill.line_items.length)} added
          {bill.printed_total !== null ? (
            <>
              {" "}
              with a printed total of <MoneyText value={bill.printed_total} currency={bill.currency} />
            </>
          ) : null}
          .
        </p>
      ) : null}
      {payment ? (
        <p>
          A payment of <MoneyText value={payment.amount} currency={payment.currency} /> was recorded
          for the case.
        </p>
      ) : null}
      <p>Each line still needs your review before anything is payable.</p>
    </Notice>
  );
}

function RevisionHistory({ view }: { view: ExtractionViewOut }) {
  if (view.revisions.length === 0) return null;
  const labels = new Map(view.fields.map((field) => [field.path, field.label]));
  const label = (path: string) => labels.get(path) ?? path;
  return (
    <details className={styles.history} data-testid="review-history">
      <summary>Review history ({view.revisions.length})</summary>
      <ol className={styles.revisions}>
        {view.revisions.map((revision) => (
          <li key={revision.revision_number}>
            <p>
              <strong>Review {revision.revision_number}</strong> by {revision.actor_label}
            </p>
            <p className={styles.meta}>{formatDateTime(revision.created_at)}</p>
            <p>{revision.reason}</p>
            {revision.corrections.length > 0 ? (
              <p className={styles.meta}>
                Corrected: {revision.corrections.map((c) => label(c.path)).join(", ")}
              </p>
            ) : null}
            {revision.confirmed_paths.length > 0 ? (
              <p className={styles.meta}>
                Confirmed: {revision.confirmed_paths.map(label).join(", ")}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

async function DocumentReview({
  params,
}: {
  params: PageProps<"/cases/[caseId]/review/[documentId]">["params"];
}) {
  await connection();
  const { caseId, documentId } = await params;
  if (!isUuid(caseId) || !isUuid(documentId)) notFound();

  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    const doc = await apiGet<DocumentOut>(`/api/documents/${seg(documentId)}`, {
      actorId: payer.id,
    });
    return { payer, doc };
  });
  if (!loaded.ok) {
    if (loaded.error.status === 404) notFound();
    return <ApiProblem error={loaded.error} />;
  }
  if (loaded.value === null) return <NoDemoPayer />;
  const { payer, doc } = loaded.value;
  if (doc.case_id !== caseId) notFound();

  const second = await attempt(async () => {
    const [detail, view] = await Promise.all([
      apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId: payer.id }),
      doc.extraction_status === "EXTRACTED"
        ? apiGet<ExtractionViewOut>(`/api/documents/${seg(documentId)}/extraction`, {
            actorId: payer.id,
          })
        : Promise.resolve(null),
    ]);
    return { detail, view };
  });
  if (!second.ok) return <ApiProblem error={second.error} />;
  const { detail, view } = second.value;

  const typeLabel = documentTypeLabel(doc.document_type);
  const back = { href: `/cases/${seg(caseId)}?tab=documents`, label: `Case ${detail.case_reference}` };

  if (view === null) {
    return (
      <div className={styles.promotedMain}>
        <PageHeader title={`Review ${typeLabel.toLowerCase()} extraction`} back={back} />
        <EmptyState title="This document has not been extracted yet">
          <p>Go back to the case and choose Extract to read its values.</p>
          <p>
            <ButtonLink href={back.href} variant="secondary">
              Back to the case
            </ButtonLink>
          </p>
        </EmptyState>
      </div>
    );
  }

  const currency = displayCurrency(view, detail.currency);
  const promoted = view.promoted_to !== null;

  return (
    <div className={styles.promotedMain}>
      <PageHeader
        title={`Review ${typeLabel.toLowerCase()} extraction`}
        back={back}
        meta={
          <>
            <p>
              {mimeLabel(doc.mime_type)}, {pageCountLabel(doc.page_count)}
            </p>
            <p>
              Read by {view.provider} ({view.model})
            </p>
          </>
        }
      />
      <DemoIdentityNote name={payer.display_name} />
      <div className={styles.evidenceDesk}><SourcePreview document={doc} /><div className={styles.reviewStack}>

      {view.is_mock ? (
        <Notice tone="info" testId="mock-label">
          <p>Prepared sample results — this document was not read by AI in this demo</p>
        </Notice>
      ) : null}
      {view.provider === "gemini" && <Notice tone="info"><p>Gemini extraction: review every value against the source. Model confidence is not a verified accuracy score.</p></Notice>}

      {promoted || !detail.family_permissions.can_review ? (
        <>
          {promoted ? <PromotedNotice view={view} detail={detail} /> : <p>Your episode role can view this extraction. An authorized reviewer can confirm or correct its values.</p>}
          <ExtractionSheet fields={view.fields} currency={currency} />
        </>
      ) : (
        <ReviewWorkspace
          caseId={caseId}
          documentId={documentId}
          view={toReviewView(view)}
          currency={currency}
        />
      )}

      </div></div><RevisionHistory view={view} />
    </div>
  );
}
