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
import { DuplicateWorkbench } from "@/components/workspace/DuplicateWorkbench";
export const metadata = { title:"Duplicate and overlap review" };
export default function DuplicatesPage({ params }: { params: Promise<{ caseId:string }> }) { return <Suspense fallback={<p>Loading review questions…</p>}><Duplicates params={params} /></Suspense>; }
async function Duplicates({ params }: { params: Promise<{ caseId:string }> }) {
  await connection(); const { caseId } = await params; if (!isUuid(caseId)) notFound();
  const loaded = await attempt(async () => { const actor = await getDemoPayer(); if (!actor) return null; const [episode, detail] = await Promise.all([apiGet<CareEpisodeOut>(`/api/cases/${seg(caseId)}/episode`, { actorId:actor.id }), apiGet<CaseDetailOut>(`/api/cases/${seg(caseId)}`, { actorId:actor.id })]); return { episode, detail }; });
  if (!loaded.ok) return <ApiProblem error={loaded.error} />; if (!loaded.value) return <NoDemoPayer />;
  return <div style={{ display:"grid", gap:"1.25rem" }}><PageHeader title="Repeated charges" meta={<p>Compare source evidence before deciding whether a charge is repeated.</p>} /><DuplicateWorkbench {...loaded.value} /></div>;
}
