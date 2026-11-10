"use client";

import { useActionState } from "react";

import { caseAction, revokeProviderLink } from "@/app/cases/[caseId]/actions";
import { INITIAL_WORKSPACE_STATE } from "@/app/cases/[caseId]/workspace-state";
import { Button, Notice } from "@/components/ui";

import styles from "./forms.module.css";

export function WorkspaceAction({ caseId, action, entityId = "", label }: { caseId: string; action: "accept" | "checks"; entityId?: string; label: string }) {
  const [state, invoke, pending] = useActionState(caseAction.bind(null, caseId, action, entityId), INITIAL_WORKSPACE_STATE);
  return <form action={invoke} className={styles.inline}><Button type="submit" variant="secondary" pending={pending}>{label}</Button>{state.message ? <Notice tone={state.status === "error" ? "error" : "success"}><p>{state.message}</p></Notice> : null}</form>;
}

export function RevokeLink({ caseId, flagId, linkId }: { caseId: string; flagId: string; linkId: string }) {
  const [state, invoke, pending] = useActionState(revokeProviderLink.bind(null, caseId, flagId, linkId), INITIAL_WORKSPACE_STATE);
  return <form action={invoke} className={styles.inline}><Button type="submit" variant="quiet" pending={pending}>Revoke link</Button>{state.message ? <Notice tone={state.status === "error" ? "error" : "success"}><p>{state.message}</p></Notice> : null}</form>;
}
