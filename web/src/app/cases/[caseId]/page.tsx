import { Suspense } from "react";
import type { Metadata } from "next";
import Overview from "./CaseOverview";
import Timeline from "./episode/page";
import Comparison from "./comparison/page";
import Duplicates from "./duplicates/page";
import Insurance from "./insurance/page";
import Family from "./family/page";
import Documents from "./review/page";
import Payments from "./payments/page";
import History from "./evidence/page";

export const metadata: Metadata = { title: "Your care workspace", robots: { index: false, follow: false }, referrer: "no-referrer" };
type Props = { params: Promise<{ caseId: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };
export default function CareWorkspace(props: Props) {
  return <Suspense fallback={<p role="status">Opening your care record…</p>}><SelectedTab {...props} /></Suspense>;
}
async function SelectedTab(props: Props) {
  const query = await props.searchParams;
  switch (query.tab) {
    case "timeline": return <Timeline {...props} />;
    case "comparison": return <Comparison {...props} />;
    case "duplicates": return <Duplicates {...props} />;
    case "insurance": return <Insurance {...props} />;
    case "family": return <Family {...props} />;
    case "documents": return <Documents {...props} />;
    case "payments": return <Payments {...props} />;
    case "history": return <History {...props} />;
    default: return <Overview {...props} />;
  }
}
