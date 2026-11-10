import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { Icon, Notice, PageHeader } from "@/components/ui";
import { ApiError, apiGet, seg } from "@/lib/api";
import { documentTypeLabel, formatDateTime, formatLimitMb } from "@/lib/format";
import type { UploadLinkInfoOut } from "@/lib/types";
import { isUploadToken } from "@/lib/validation";

import { UploadForm } from "./upload-form";
import styles from "./upload.module.css";

// The upload token is the only credential in this URL: keep it out of Referer headers and
// search indexes.
export const metadata: Metadata = {
  title: "Upload documents",
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default function UploadPage(props: PageProps<"/upload/[token]">) {
  return (
    <Suspense fallback={<div className={styles.skeleton} aria-hidden="true" />}>
      <UploadContent params={props.params} />
    </Suspense>
  );
}

function InvalidLink() {
  return (
    <div className={styles.page}>
      <PageHeader title="This link can’t be used" />
      <Notice tone="warning">
        <p>
          This upload link is invalid or has expired. Ask the person who sent it for a new link.
        </p>
      </Notice>
    </div>
  );
}

async function UploadContent({ params }: { params: PageProps<"/upload/[token]">["params"] }) {
  await connection();
  const { token } = await params;
  if (!isUploadToken(token)) return <InvalidLink />;

  let info: UploadLinkInfoOut;
  try {
    info = await apiGet<UploadLinkInfoOut>(`/api/uploads/${seg(token)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status !== 503) return <InvalidLink />;
    return (
      <div className={styles.page}>
        <PageHeader title="Upload is not available right now" />
        <Notice tone="error">
          <p>The upload service is not reachable. Try again in a moment.</p>
        </Notice>
      </div>
    );
  }

  if (info.document_types.length === 0) return <InvalidLink />;

  return (
    <div className={styles.page}>
      <PageHeader title="Upload documents" />
      <p className={styles.lead}>
        Add the hospital bills, estimates or receipts you were asked for. The person who sent this
        link will check them before anything is added to the case.
      </p>
      <dl className={styles.facts}>
        <dt>You can upload</dt>
        <dd>{info.document_types.map(documentTypeLabel).join(", ")}</dd>
        <dt>File types</dt>
        <dd>
          PDF, JPG or PNG, up to {formatLimitMb(info.max_upload_bytes)} and {info.max_pages} pages
        </dd>
        <dt>Link expires</dt>
        <dd>{formatDateTime(info.expires_at)}</dd>
      </dl>
      <UploadForm
        token={token}
        allowedTypes={info.document_types}
        acceptedMime={info.allowed_mime_types}
        maxBytes={info.max_upload_bytes}
        initialRemaining={info.uploads_remaining}
      />
      <p className={styles.privacy}>
        <Icon name="lock" size={18} />
        <span>
          Files are stored privately and are only visible to the people on this case. This demo
          accepts sample documents only. Do not upload real medical records.
        </span>
      </p>
    </div>
  );
}
