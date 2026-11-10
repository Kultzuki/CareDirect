"use client";

import { useActionState, useState, type ReactNode } from "react";
import { Button } from "@/components/ui";
import { familyAction, type FamilyCommand } from "./actions";
import styles from "./family.module.css";

export function FamilyForm({ caseId, command, targetId = "", requestId, label, children }: { caseId: string; command: FamilyCommand; targetId?: string; requestId: string; label: string; children?: ReactNode }) {
  const [state, action, pending] = useActionState(familyAction.bind(null, caseId, command, targetId, requestId), {});
  const [copyMessage, setCopyMessage] = useState("");
  async function copyLink() {
    if (!state.invitationPath) return;
    try { await navigator.clipboard.writeText(new URL(state.invitationPath, window.location.origin).href); setCopyMessage("Invitation link copied."); }
    catch { setCopyMessage("Copy was unavailable. Open the invitation and copy its address."); }
  }
  return <form action={action} className={styles.form}>
    {children}<Button type="submit" pending={pending} variant="secondary">{label}</Button>
    {(state.error || state.message) && <p role={state.error ? "alert" : "status"}>{state.error ?? state.message}</p>}
    {state.invitationPath && <div className={styles.invitation}><a href={state.invitationPath} referrerPolicy="no-referrer">Open family invitation</a><Button type="button" variant="quiet" onClick={copyLink}>Copy invitation link</Button><p role="status">{copyMessage}</p><p>This private, expiring link works only with the invited identity. It is shown once; create a replacement if you lose it.</p></div>}
  </form>;
}
