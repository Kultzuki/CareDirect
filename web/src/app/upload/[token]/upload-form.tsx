"use client";

import { useActionState, useState } from "react";

import { Button, FormField, Icon, Notice } from "@/components/ui";
import { documentTypeLabel, formatBytes, formatLimitMb, pageCountLabel } from "@/lib/format";
import type { UploadableDocumentType } from "@/lib/types";

import { uploadDocument } from "./actions";
import { INITIAL_UPLOAD_STATE } from "./upload-state";
import styles from "./upload.module.css";

export function UploadForm({
  token,
  allowedTypes,
  acceptedMime,
  maxBytes,
  initialRemaining,
}: {
  token: string;
  allowedTypes: UploadableDocumentType[];
  acceptedMime: string[];
  maxBytes: number;
  initialRemaining: number;
}) {
  const [state, formAction, pending] = useActionState(uploadDocument, INITIAL_UPLOAD_STATE);
  const [documentType, setDocumentType] = useState<UploadableDocumentType>(allowedTypes[0]);
  const [tooLarge, setTooLarge] = useState(false);

  const remaining = state.status === "success" ? state.uploadsRemaining : initialRemaining;
  const exhausted = remaining <= 0;

  return (
    <form action={formAction} className={styles.form} data-testid="upload-form">
      <input type="hidden" name="token" value={token} />

      <p className={styles.remaining} data-testid="uploads-remaining">
        {exhausted
          ? "No uploads left on this link."
          : `${remaining} ${remaining === 1 ? "upload" : "uploads"} left on this link.`}
      </p>

      <FormField id="document-type" label="Document type">
        {(control) => (
          <select
            {...control}
            name="document_type"
            value={documentType}
            onChange={(event) => setDocumentType(event.target.value as UploadableDocumentType)}
          >
            {allowedTypes.map((type) => (
              <option key={type} value={type}>
                {documentTypeLabel(type)}
              </option>
            ))}
          </select>
        )}
      </FormField>

      <FormField
        id="upload-file"
        label="File"
        hint={`PDF, JPG or PNG, up to ${formatLimitMb(maxBytes)}.`}
        error={tooLarge ? `That file is larger than ${formatLimitMb(maxBytes)}.` : undefined}
      >
        {(control) => (
          <input
            {...control}
            className={styles.file}
            type="file"
            name="file"
            accept={acceptedMime.join(",")}
            required
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              setTooLarge(Boolean(chosen && chosen.size > maxBytes));
            }}
          />
        )}
      </FormField>

      <div className={styles.submitRow}>
        <Button type="submit" pending={pending} disabled={exhausted || tooLarge}>
          <Icon name="upload" size={18} />
          Upload
        </Button>
      </div>

      <div className={styles.feedback}>
        {state.status === "success" ? (
          <Notice tone="success" title="Uploaded">
            <p>
              {documentTypeLabel(state.documentType)}: {pageCountLabel(state.pageCount)},{" "}
              {formatBytes(state.fileSize)}. Reference {state.reference}.
            </p>
            {exhausted ? (
              <p>That was the last upload on this link. Ask for a new link to add more.</p>
            ) : (
              <p>You can choose another file and upload it now.</p>
            )}
          </Notice>
        ) : null}
        {state.status === "error" ? (
          <Notice tone="error" title="This file was not uploaded">
            <p>{state.message}</p>
            {state.hint ? <p>{state.hint}</p> : null}
          </Notice>
        ) : null}
      </div>
    </form>
  );
}
