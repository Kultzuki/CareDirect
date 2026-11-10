import { Suspense } from "react";
import { connection } from "next/server";
import { notFound } from "next/navigation";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { attempt } from "@/lib/load";
import { isUuid } from "@/lib/validation";
import type { CareEpisodeOut, CaseDetailOut } from "@/lib/types";
import { ApiProblem, NoDemoPayer } from "@/components/PageProblems";
import { PageHeader } from "@/components/ui";
import { CareTimeline } from "@/components/workspace/CareTimeline";
import { EpisodeIntelligence } from "@/components/episode/EpisodeIntelligence";

export const metadata = { title: "Care timeline" };
export default function EpisodePage({ params }: { params: Promise<{ caseId: string }> }) { return <Suspense fallback={<p>Loading episode…</p>}><Episode params={params} /></Suspense>; }
async function Episode({ params }: { params: Promise<{ caseId: string }> }) {
  await connection(); const { caseId } = await params; if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => { const actor = await getDemoPayer(); if (!actor) return null; const [episode, detail] = await Promise.all([apiGet<CareEpisodeOut>(`/api/cases/${seg(caseId)}/episode`, { actorId: actor.id }), apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId: actor.id })]); return { episode, detail }; });
  if (!loaded.ok) return <ApiProblem error={loaded.error} />; if (!loaded.value) return <NoDemoPayer />;
  const { episode, detail } = loaded.value;
  return <div style={{ display:"grid", gap:"1.25rem" }}><PageHeader title="Care timeline" meta={<p>Care timeline · {episode.patient_alias}</p>} /><CareTimeline episode={episode} /><EpisodeIntelligence episode={episode} canReview={detail.family_permissions.can_review} canManage={detail.family_permissions.can_manage} /></div>;
}
