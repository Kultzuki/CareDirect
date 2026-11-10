"use client";

import { useActionState } from "react";
import { analyzeEpisode, createEpisode, saveEpisode } from "@/app/cases/episode-actions";
import { Button, FormField } from "@/components/ui";
import type { CareEpisodeOut } from "@/lib/types";
import styles from "./EpisodeIntelligence.module.css";

export function NewEpisode() {
  const [state, action, pending] = useActionState(createEpisode, {});
  return <section id="new-episode" className={styles.container} aria-labelledby="new-episode-title">
    <h2 id="new-episode-title">Start a care record</h2>
    <p>Keep the estimate, bills, receipts and hospital responses for one treatment together.</p>
    <form action={action} className={styles.form}>
      <FormField id="new-episode-name" label="Treatment name" hint="For example: Knee Replacement — November 2026">{(props) => <input {...props} name="episode_title" required maxLength={200} />}</FormField>
      <FormField id="new-patient-alias" label="Patient name or nickname" hint="For example: Father. Use a sample name in this demo.">{(props) => <input {...props} name="patient_alias" required maxLength={120} />}</FormField>
      <FormField id="new-episode-currency" label="Currency">{(props) => <select {...props} name="currency"><option value="INR">INR — Indian rupee</option><option value="USD">USD — US dollar</option></select>}</FormField>
      <FormField id="new-episode-context" label="Treatment context (optional)">{(props) => <textarea {...props} name="clinical_context" maxLength={2000} rows={3} />}</FormField>
      <Button type="submit" pending={pending}>Create care record</Button>
      {state.error && <p role="alert">{state.error}</p>}
    </form>
  </section>;
}

export function EpisodeControls({ episode, canReview = true, canManage = true }: { episode: CareEpisodeOut; canReview?: boolean; canManage?: boolean }) {
  const [saved, save, saving] = useActionState(saveEpisode.bind(null, episode.case_id), {});
  const [analyzed, analyze, analyzing] = useActionState(analyzeEpisode.bind(null, episode.case_id, episode.input_fingerprint), {});
  return <div className={styles.form}>
    {canManage && <details><summary>Edit treatment details</summary><form action={save} className={styles.form}>
      <FormField id="episode-name" label="Treatment name">{(props) => <input {...props} name="episode_title" defaultValue={episode.episode_title} required maxLength={200} />}</FormField>
      <FormField id="episode-context" label="Treatment context">{(props) => <textarea {...props} name="clinical_context" defaultValue={episode.clinical_context ?? ""} maxLength={2000} rows={3} />}</FormField>
      <Button type="submit" pending={saving}>Save details</Button>
      <p role={saved.error ? "alert" : "status"}>{saved.error ?? saved.message}</p>
    </form></details>}
    <form action={analyze} className={styles.form}>
      <p>Ask AI whether these records belong to the same treatment and whether differently named tests could be the same service. CareDirect also checks dates, quantities and service codes. You must review any suggestions. If AI is enabled, an outside service may keep a copy of the details sent to it. Use sample records only.</p>
      {!episode.ai_configured && <p>AI is turned off in this demo. You can still check the documents and bill amounts.</p>}
      <Button type="submit" pending={analyzing} disabled={!canReview || !episode.ai_configured || !episode.documents.length}>Ask AI to check the records</Button>
      <p role={analyzed.error ? "alert" : "status"}>{analyzed.error ?? analyzed.message}</p>
    </form>
  </div>;
}
