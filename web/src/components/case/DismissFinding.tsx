"use client";

import { useActionState, useState } from "react";

import { dismissFinding } from "@/app/cases/[caseId]/actions";
import { INITIAL_WORKSPACE_STATE } from "@/app/cases/[caseId]/workspace-state";
import { Button, FormField, Notice } from "@/components/ui";

import styles from "./forms.module.css";
import { useUnsavedChanges } from "./useUnsavedChanges";

export function DismissFinding({ caseId, flagId }: { caseId: string; flagId: string }) {
  const [note, setNote] = useState("");
  const [state, action, pending] = useActionState(dismissFinding.bind(null, caseId, flagId), INITIAL_WORKSPACE_STATE);
  useUnsavedChanges(note.length > 0 && state.status !== "success");
  return <details className={styles.details}><summary>Review and dismiss this finding</summary><form className={styles.form} action={action}><p>This marks the rule finding as reviewed. It does not remove a charge, release a queried amount or approve payment. Active provider questions must be resolved first.</p><FormField id={`dismiss-${flagId}`} label="What evidence resolves this finding?">{(control) => <textarea {...control} name="note" value={note} onChange={(event) => setNote(event.target.value)} required maxLength={2000} rows={3} />}</FormField><Button type="submit" variant="secondary" pending={pending}>Dismiss finding after review</Button>{state.message ? <Notice tone={state.status === "error" ? "error" : "success"}><p>{state.message}</p></Notice> : null}</form></details>;
}
