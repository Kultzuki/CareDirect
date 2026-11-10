import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { ApiProblem, DemoIdentityNote, NoDemoPayer } from "@/components/PageProblems";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { DemoRuns } from "@/components/dashboard/DemoRuns";
import { NewEpisode } from "@/components/episode/EpisodeControls";
import { PageHeader } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { attempt } from "@/lib/load";
import type { DashboardOut } from "@/lib/dashboard-types";

import styles from "./cases.module.css";

export const metadata: Metadata = { title: "Cases" };

export default function CasesPage() {
  return (
    <>
      <PageHeader title="Your care records" meta={<p>Follow the bill, the open questions and every payment in one family record.</p>} actions={<div className={styles.pageActions}><Link href="#demo">Start a fresh demo</Link><Link href="/cases/studio">Open family Studio</Link></div>} />
      <Suspense fallback={<div className={styles.skeleton} aria-hidden="true" />}>
        <CaseList />
      </Suspense>
    </>
  );
}

async function CaseList() {
  await connection();

  const loaded = await attempt(async () => {
    const payer = await getDemoPayer();
    if (!payer) return null;
    const dashboard = await apiGet<DashboardOut>("/api/dashboard", { actorId: payer.id });
    return { payer, dashboard };
  });
  if (!loaded.ok) return <ApiProblem error={loaded.error} />;
  if (loaded.value === null) return <NoDemoPayer />;

  const { payer, dashboard } = loaded.value;

  return (
    <>
      <DemoIdentityNote name={payer.display_name} />
      <div className={styles.workspace}><NewEpisode /><Dashboard dashboard={dashboard} /><DemoRuns /></div>
    </>
  );
}
