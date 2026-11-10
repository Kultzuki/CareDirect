"use client";

import { useActionState } from "react";

import { Button, Notice } from "@/components/ui";

import { extractDocument } from "./actions";
import { INITIAL_EXTRACT_STATE } from "./case-state";
import styles from "./case-review.module.css";

export function ExtractButton({
  caseId,
  documentId,
  failed,
  label,
}: {
  caseId: string;
  documentId: string;
  failed: boolean;
  /** Names the document for screen reader users, such as "Bill 3fa85f64". */
  label: string;
}) {
  const [state, formAction, pending] = useActionState(
    extractDocument.bind(null, caseId, documentId),
    INITIAL_EXTRACT_STATE,
  );
  return (
    <form action={formAction} className={styles.extract}>
      <p>AI may read this document through an outside service that may keep a copy. Use sample documents only.</p>
      <Button type="submit" pending={pending} variant={failed ? "secondary" : "primary"}>
        {failed ? "Extract again" : "Extract"}
        <span className="cd-visually-hidden"> {label}</span>
      </Button>
      {state.status === "error" ? (
        <Notice tone="error" title="Extraction failed">
          <p>{state.message}</p>
          <p>Check the error before retrying. Saved extractions are reused; each new attempt can consume provider quota.</p>
        </Notice>
      ) : null}
    </form>
  );
}
