"use client";

import { useActionState, useState } from "react";

import { ExtractionSheet } from "@/components/extraction/ExtractionSheet";
import { fieldDomId } from "@/components/extraction/FieldRow";
import { Button, FormField, Notice, type FieldControlProps } from "@/components/ui";
import { fieldInputError } from "@/lib/field-input";
import { PAYMENT_METHODS, PAYMENT_METHOD_LABEL } from "@/lib/format";
import type { FieldOut, ReviewViewData } from "@/lib/types";

import { promoteExtraction, saveReview } from "./actions";
import { INITIAL_REVIEW_STATE } from "./review-state";
import styles from "./review.module.css";

interface SourceDraft {
  page: string;
  snippet: string;
}

function initialDrafts(fields: FieldOut[]): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.path, field.value ?? ""]));
}

function ValueInput({
  field,
  control,
  value,
  onChange,
}: {
  field: FieldOut;
  control: FieldControlProps;
  value: string;
  onChange: (value: string) => void;
}) {
  const shared = {
    ...control,
    name: `value:${field.path}`,
    value,
  };
  switch (field.kind) {
    case "money":
    case "quantity":
      return (
        <input
          {...shared}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    case "date":
      return <input {...shared} type="date" onChange={(event) => onChange(event.target.value)} />;
    case "currency":
      return (
        <input
          {...shared}
          type="text"
          maxLength={3}
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    case "payment_method":
      return (
        <select {...shared} onChange={(event) => onChange(event.target.value)}>
          <option value="">Not found</option>
          {PAYMENT_METHODS.map((method) => (
            <option key={method} value={method}>
              {PAYMENT_METHOD_LABEL[method]}
            </option>
          ))}
        </select>
      );
    default:
      return (
        <input
          {...shared}
          type="text"
          maxLength={500}
          autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
        />
      );
  }
}

/**
 * The review screen for one extraction: every field with its evidence, an optional correction
 * or confirmation per field, the reason for the change, and the "Add to case" gate.
 * Controlled inputs keep what the payer typed if the API refuses a save.
 * `needs_review`, blockers and `can_promote` come from the API; nothing here recomputes them.
 */
export function ReviewWorkspace({
  caseId,
  documentId,
  view,
  currency,
}: {
  caseId: string;
  documentId: string;
  view: ReviewViewData;
  currency: string;
}) {
  const isInsurance = ["INSURANCE_PREAUTH", "INSURANCE_SETTLEMENT", "INSURER_PAYMENT"].includes(view.document_type);
  const [saveState, saveAction, savePending] = useActionState(
    saveReview.bind(null, caseId, documentId, view.id),
    INITIAL_REVIEW_STATE,
  );
  const [promoteState, promoteAction, promotePending] = useActionState(
    promoteExtraction.bind(null, caseId, documentId, view.id),
    INITIAL_REVIEW_STATE,
  );

  const [seenView, setSeenView] = useState(view);
  const [drafts, setDrafts] = useState(() => initialDrafts(view.fields));
  const [confirms, setConfirms] = useState<Record<string, boolean>>({});
  const [sources, setSources] = useState<Record<string, SourceDraft>>({});
  const [reason, setReason] = useState("");
  const [editAll, setEditAll] = useState(false);

  // New data from the server (after a save) replaces the drafts: the saved values are now the
  // current values, so nothing is pending.
  if (seenView !== view) {
    setSeenView(view);
    setDrafts(initialDrafts(view.fields));
    setConfirms({});
    setSources({});
    setReason("");
  }

  const changedPaths = view.fields
    .filter((field) => (drafts[field.path] ?? "") !== (field.value ?? ""))
    .map((field) => field.path);
  const confirmedPaths = Object.keys(confirms).filter((path) => confirms[path]);
  const dirty = changedPaths.length > 0 || confirmedPaths.length > 0;
  const hasInputErrors = view.fields.some(
    (field) => fieldInputError(field.kind, (drafts[field.path] ?? "").trim()) !== null,
  );

  const reviewCount = view.review_required.length;
  const blockers = view.promotion_blockers;

  const renderControls = (field: FieldOut) => {
    const id = fieldDomId(field.path);
    const draft = drafts[field.path] ?? "";
    const error = fieldInputError(field.kind, draft.trim());
    const needsSource =
      field.source === null && draft.trim() !== "" && draft !== (field.value ?? "");
    const source = sources[field.path] ?? { page: "", snippet: "" };
    // Flagged fields always show their controls. Others show them on request, and keep showing
    // them once the payer has typed or ticked something (so a pending change is never hidden).
    // Hidden inputs still submit, so nothing typed is dropped.
    const show =
      field.needs_review ||
      editAll ||
      draft !== (field.value ?? "") ||
      Boolean(confirms[field.path]);
    return (
      <>
        <div className={styles.controls} hidden={!show}>
          <label className={styles.confirm}>
            <input
              type="checkbox"
              name={`confirm:${field.path}`}
              checked={Boolean(confirms[field.path])}
              onChange={(event) =>
                setConfirms((current) => ({ ...current, [field.path]: event.target.checked }))
              }
            />
            <span>Confirm {field.label}</span>
          </label>
          <FormField
            id={`${id}-value`}
            label={`Corrected value for ${field.label}`}
            error={error ?? undefined}
          >
            {(control) => (
              <ValueInput
                field={field}
                control={control}
                value={draft}
                onChange={(value) => setDrafts((current) => ({ ...current, [field.path]: value }))}
              />
            )}
          </FormField>
          {needsSource ? (
            <fieldset className={styles.source}>
              <legend className="cd-visually-hidden">
                Where {field.label} appears on the document
              </legend>
              <FormField id={`${id}-page`} label="Page">
                {(control) => (
                  <input
                    {...control}
                    type="text"
                    inputMode="numeric"
                    name={`page:${field.path}`}
                    value={source.page}
                    required
                    maxLength={4}
                    autoComplete="off"
                    onChange={(event) =>
                      setSources((current) => ({
                        ...current,
                        [field.path]: { ...source, page: event.target.value },
                      }))
                    }
                  />
                )}
              </FormField>
              <FormField id={`${id}-snippet`} label="Text on the document">
                {(control) => (
                  <input
                    {...control}
                    type="text"
                    name={`snippet:${field.path}`}
                    value={source.snippet}
                    required
                    maxLength={500}
                    autoComplete="off"
                    onChange={(event) =>
                      setSources((current) => ({
                        ...current,
                        [field.path]: { ...source, snippet: event.target.value },
                      }))
                    }
                  />
                )}
              </FormField>
            </fieldset>
          ) : null}
        </div>
      </>
    );
  };

  const describedBy =
    [hasInputErrors ? "save-help" : null, !dirty ? "save-idle" : null]
      .filter(Boolean)
      .join(" ") || undefined;
  const promoteDescribedBy =
    [blockers.length > 0 ? "promotion-blockers" : null, dirty ? "unsaved-note" : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className={styles.workspace}>
      <div className={styles.main}>
        <Notice tone={reviewCount > 0 ? "warning" : "success"} testId="review-summary">
          <p>
            {reviewCount === 0
              ? "All low-confidence fields reviewed"
              : reviewCount === 1
                ? "1 field needs your review before this can be added to the case"
                : `${reviewCount} fields need your review before this can be added to the case`}
          </p>
          <p>
            <a href="#add-to-case">{isInsurance ? "Continue to Insurance" : "Jump to the Add to case panel"}</a>
          </p>
        </Notice>

        <form action={saveAction} className={styles.reviewForm} aria-label="Review extracted values">
          <label className={styles.editAll}>
            <input
              type="checkbox"
              checked={editAll}
              onChange={(event) => setEditAll(event.target.checked)}
            />
            <span>
              Show edit controls on every field
              <span className={styles.editAllHint}>
                Flagged fields always have them. Turn this on to correct a value the model read
                with high confidence but wrongly.
              </span>
            </span>
          </label>
          <ExtractionSheet fields={view.fields} currency={currency} renderControls={renderControls} />

          <div className={styles.saveBar}>
            <p className={styles.helper}>
              To fix a value, type the right one under it. To say a value is right, tick Confirm.
              Your changes are saved as a new entry in the review history; the original reading
              is kept.
            </p>
            <FormField id="review-reason" label="Reason for changes">
              {(control) => (
                <textarea
                  {...control}
                  name="reason"
                  required
                  maxLength={2000}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              )}
            </FormField>
            {hasInputErrors ? (
              <p id="save-help" className={styles.helper}>
                Fix the values marked above before saving.
              </p>
            ) : null}
            {!dirty ? (
              <p id="save-idle" className={styles.helper}>
                Change a value or confirm a field to save a review.
              </p>
            ) : null}
            <div className={styles.saveRow}>
              <Button
                type="submit"
                pending={savePending}
                disabled={!dirty || hasInputErrors}
                aria-describedby={describedBy}
              >
                Save review
              </Button>
            </div>
            {saveState.status === "success" ? (
              <Notice tone="success" title={saveState.message}>
                <p>The page now shows the saved values.</p>
              </Notice>
            ) : null}
            {saveState.status === "error" ? (
              <Notice tone="error" title="Review not saved">
                <p>{saveState.message}</p>
              </Notice>
            ) : null}
          </div>
        </form>
      </div>

      {isInsurance ? <section id="add-to-case" className={styles.panel} aria-labelledby="insurance-next-heading"><h2 id="insurance-next-heading">Insurance evidence review</h2><p>Save your field confirmations above, then compare the reviewed document with the hospital bill. Insurance documents never become bill charges or family payment credits.</p><a href={`/cases/${caseId}?tab=insurance`}>Open Insurance and family share</a>{dirty && <p>You have unsaved field reviews. Save before continuing.</p>}</section> : <section id="add-to-case" className={styles.panel} aria-labelledby="promote-heading">
        <h2 id="promote-heading">Add to case</h2>
        {blockers.length === 0 && !dirty ? (
          <p>
            Everything needed is in place. Each line will still need your review before anything is
            payable.
          </p>
        ) : null}
        {blockers.length > 0 ? (
          <>
            <p>Before this can be added:</p>
            <ul id="promotion-blockers" className={styles.blockers}>
              {blockers.map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          </>
        ) : null}
        {dirty ? (
          <p id="unsaved-note" className={styles.unsaved}>
            You have unsaved changes. Save your review first.
          </p>
        ) : null}
        <form action={promoteAction}>
          <Button
            type="submit"
            full
            pending={promotePending}
            disabled={!view.can_promote || dirty}
            aria-describedby={promoteDescribedBy}
          >
            Add to case
          </Button>
        </form>
        {promoteState.status === "error" ? (
          <Notice tone="error" title="Not added to the case">
            <p>{promoteState.message}</p>
          </Notice>
        ) : null}
      </section>}
    </div>
  );
}
