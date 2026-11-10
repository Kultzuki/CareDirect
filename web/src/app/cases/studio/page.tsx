import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";
import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { StudioView } from "@/components/dashboard/StudioView";
import { PageHeader, Notice } from "@/components/ui";
import { apiGet } from "@/lib/api";
import type { DashboardOut } from "@/lib/dashboard-types";
import { getDemoPayer } from "@/lib/demo-identity";
import { attempt } from "@/lib/load";

export const metadata:Metadata = {title:"Family Studio",robots:{index:false,follow:false}};
export default function StudioPage() { return <><PageHeader title="Family overview" back={{href:"/cases",label:"All cases"}} meta={<p>Explore open questions and payment observations in a read-only case table.</p>} /><Suspense fallback={<p role="status">Loading authorized cases…</p>}><StudioWorkspace /></Suspense></>; }
async function StudioWorkspace() {
  await connection();
  const loaded = await attempt(async()=>{const payer=await getDemoPayer(); if(!payer)return null; return {payer,dashboard:await apiGet<DashboardOut>("/api/dashboard",{actorId:payer.id})};});
  if(!loaded.ok)return <ApiProblem error={loaded.error}/>;
  if(!loaded.value)return <NoDemoPayer/>;
  const key = process.env.AG_STUDIO_LICENSE_KEY;
  const evaluation = process.env.STUDIO_LOCAL_EVALUATION === "true" && process.env.NODE_ENV === "development";
  return <><DemoIdentityNote name={loaded.value.payer.display_name}/>{key || evaluation ? <StudioView dashboard={loaded.value.dashboard} licenseKey={key}/> : <Notice tone="info" title="The family workspace is available"><p><Link href="/cases">Open Cases</Link> to use all balances, questions and evidence. The optional analysis table is not enabled in this environment.</p></Notice>}</>;
}
