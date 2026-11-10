import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CaseStatusBadge } from "@/components/CaseStatusBadge";
import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import {
  ButtonLink,
  EmptyState,
  MoneyText,
  PageHeader,
  Section,
  StatusBadge,
} from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import {
  documentTypeLabel,
  formatBytes,
  mimeLabel,
  pageCountLabel,
} from "@/lib/format";
import { attempt } from "@/lib/load";
import type { CaseDetailOut, DocumentOut, ExtractionStatus } from "@/lib/types";
import { isUuid } from "@/lib/validation";

import { ExtractButton } from "./extract-button";
import { UploadLinkForm } from "./upload-link-form";
import styles from "./case-review.module.css";

export const metadata: Metadata = { title: "Review documents" };

export default function CaseReviewPage(props: PageProps<"/cases/[caseId]/review">) {
  return (
    <Suspense fallback={<div className={styles.skeleton} aria-hidden="true" />}>
      <CaseReview params={props.params} />
    </Suspense>
  );
}

const STATUS_BADGE: Record<ExtractionStatus, { tone: "neutral" | "extracted" | "error"; text: string }> = {
  NOT_STARTED: { tone: "neutral", text: "Not extracted yet" },
  EXTRACTED: { tone: "extracted", text: "Extracted" },
  FAILED: { tone: "error", text: "Extraction failed" },
};

function DocumentRow({ doc, canReview }: { doc: DocumentOut; canReview: boolean }) {
  const typeLabel = documentTypeLabel(doc.document_type);
  const short = doc.sha256.slice(0, 8);
  const badge = STATUS_BADGE[doc.extraction_status];
  return (
    <li className={styles.document} data-testid={`document-${doc.id}`}>
      <div className={styles.docMain}>
        <div className={styles.docTitle}>
          <h3>{typeLabel}</h3>
          <StatusBadge tone={badge.tone} icon={doc.extraction_status === "FAILED" ? "alert" : null}>
            {badge.text}
          </StatusBadge>
        </div>
        <dl className={styles.docFacts}>
          <div>
            <dt>File</dt>
            <dd>{mimeLabel(doc.mime_type)}</dd>
          </div>
          <div>
            <dt>Pages</dt>
            <dd>{pageCountLabel(doc.page_count)}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>{formatBytes(doc.file_size)}</dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>{doc.sha256.slice(0, 12)}</dd>
          </div>
        </dl>
      </div>
      <div className={styles.docActions}>
        {doc.extraction_status === "EXTRACTED" ? (
          <ButtonLink
            variant="secondary"
            href={`/cases/${seg(doc.case_id)}/review/${seg(doc.id)}`}
          >
            Check document details
            <span className="cd-visually-hidden">
              {" "}
              of {typeLabel} {short}
            </span>
          </ButtonLink>
        ) : canReview ? (
          <ExtractButton
            caseId={doc.case_id}
            documentId={doc.id}
            failed={doc.extraction_status === "FAILED"}
            label={`${typeLabel} ${short}`}
          />
        ) : <p>An authorized reviewer can extract this document.</p>}
      </div>
    </li>
  );
}

async function CaseReview({ params }: { params: PageProps<"/cases/[caseId]/review">["params"] }) {
  await connection();
  const { caseId } = await params;
  if (!isUuid(caseId)) notFound();

  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    const [detail, documents] = await Promise.all([
      apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId: payer.id }),
      apiGet<DocumentOut[]>(`/api/cases/${seg(caseId)}/documents`, { actorId: payer.id }),
    ]);
    return { payer, detail, documents };
  });
  if (!loaded.ok) {
    if (loaded.error.status === 404) notFound();
    return <ApiProblem error={loaded.error} />;
  }
  if (loaded.value === null) return <NoDemoPayer />;

  const { payer, detail, documents } = loaded.value;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Documents"
        back={{ href: `/cases/${caseId}`, label: "Case workspace" }}
        meta={
          <div className={styles.caseMeta}>
            <p>{detail.patient_alias}</p>
            <CaseStatusBadge status={detail.status} />
            <p>
              Bill total{" "}
              <MoneyText value={detail.buckets.bill_total} currency={detail.currency} />
            </p>
          </div>
        }
      />
      <DemoIdentityNote name={payer.display_name} />
      <ButtonLink variant="secondary" href={`/cases/${caseId}?tab=comparison`}>
        Compare estimate vs final bill
      </ButtonLink>

      <Section
        id="upload-link"
        title="Upload link"
        description="Ask a relative or the hospital to send documents without signing in. A link only lets them add files to this case."
      >
        {detail.family_permissions.can_review ? <UploadLinkForm caseId={detail.id} /> : <p>Your role can view documents. An authorized reviewer can create upload links and extract documents.</p>}
      </Section>

      <Section
        id="documents"
        title="Documents"
        description="Extract a document to read its values, then check each one against the page."
      >
        {documents.length === 0 ? (
          <EmptyState title="No documents yet">
            <p>Create an upload link above and share it. Files appear here once they arrive.</p>
          </EmptyState>
        ) : (
          <ul className={styles.documents} data-testid="document-list">
            {documents.map((doc) => (
              <DocumentRow key={doc.id} doc={doc} canReview={detail.family_permissions.can_review} />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
