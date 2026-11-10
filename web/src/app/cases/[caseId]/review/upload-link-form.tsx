"use client";

import { useActionState, useState } from "react";

import { Button, Icon, Notice } from "@/components/ui";
import { documentTypeLabel, formatDateTime } from "@/lib/format";
import type { UploadableDocumentType } from "@/lib/types";

import { createUploadLink } from "./actions";
import { INITIAL_LINK_STATE } from "./case-state";
import styles from "./case-review.module.css";

const CHOICES: UploadableDocumentType[] = ["BILL", "ESTIMATE", "RECEIPT", "INSURANCE_PREAUTH", "INSURANCE_SETTLEMENT", "INSURER_PAYMENT"];

export function UploadLinkForm({ caseId }: { caseId: string }) {
  const [state, formAction, pending] = useActionState(
    createUploadLink.bind(null, caseId),
    INITIAL_LINK_STATE,
  );
  const [chosen, setChosen] = useState<Set<UploadableDocumentType>>(
    () => new Set<UploadableDocumentType>(["BILL", "RECEIPT"]),
  );
  const [copied, setCopied] = useState(false);

  function toggle(type: UploadableDocumentType, checked: boolean) {
    setChosen((current) => {
      const next = new Set(current);
      if (checked) next.add(type);
      else next.delete(type);
      return next;
    });
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className={styles.linkBox}>
      <form action={formAction} className={styles.linkForm}>
        <fieldset className={styles.choices}>
          <legend>Kinds of document this link can receive</legend>
          {CHOICES.map((type) => (
            <label key={type} className={styles.choice}>
              <input
                type="checkbox"
                name="document_types"
                value={type}
                checked={chosen.has(type)}
                onChange={(event) => toggle(type, event.target.checked)}
              />
              <span>{documentTypeLabel(type)}</span>
            </label>
          ))}
        </fieldset>
        <div>
          <Button type="submit" pending={pending} disabled={chosen.size === 0}>
            Create upload link
          </Button>
        </div>
      </form>

      {state.status === "error" ? (
        <Notice tone="error" title="Link not created">
          <p>{state.message}</p>
        </Notice>
      ) : null}

      {state.status === "success" ? (
        <Notice tone="success" title="Upload link created" testId="upload-link-result">
          <p>
            Send this to the person who has the{" "}
            {new Intl.ListFormat("en").format(
              state.documentTypes.map((type) => documentTypeLabel(type).toLowerCase()),
            )}
            . It is shown once. It lets them upload files to this case and nothing else.
          </p>
          <p>
            <a href={state.path} className={styles.linkAnchor}>
              Open upload page
            </a>
          </p>
          <div className={styles.copyRow}>
            <label className="cd-visually-hidden" htmlFor="upload-link-address">
              Upload link address
            </label>
            <input
              id="upload-link-address"
              className={styles.address}
              readOnly
              value={
                typeof window === "undefined" ? state.path : `${window.location.origin}${state.path}`
              }
              onFocus={(event) => event.currentTarget.select()}
            />
            <Button
              variant="secondary"
              onClick={() => copy(`${window.location.origin}${state.path}`)}
            >
              <Icon name="copy" size={16} />
              Copy link
            </Button>
          </div>
          <p aria-live="polite" className={styles.copied}>
            {copied ? "Link copied." : ""}
          </p>
          <p>
            Up to {state.maxUploads} uploads. Expires {formatDateTime(state.expiresAt)}.
          </p>
        </Notice>
      ) : null}
    </div>
  );
}
