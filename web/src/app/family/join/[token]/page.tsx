import type { Metadata } from "next";
import { connection } from "next/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { apiGet, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { formatDateTime } from "@/lib/format";
import { attempt } from "@/lib/load";
import { isUploadToken } from "@/lib/validation";
import { JoinForm } from "./JoinForm";

export const metadata: Metadata = { title: "Family invitation", referrer: "no-referrer", robots: { index: false, follow: false } };
export default function InvitationPage({ params }: { params: Promise<{ token: string }> }) {
  return <Suspense fallback={<p>Checking invitation…</p>}><Invitation params={params} /></Suspense>;
}
async function Invitation({ params }: { params: Promise<{ token: string }> }) {
  await connection();
  const { token } = await params;
  if (!isUploadToken(token)) notFound();
  const loaded = await attempt(async () => {
    const actor = await getDemoPayer();
    return actor ? { actor, invitation: await apiGet<{ role: string; can_review: boolean; can_approve: boolean; expires_at: string }>(`/api/family/invitations/${seg(token)}`, { actorId: actor.id }) } : null;
  });
  return <div style={{ maxWidth: "48rem", margin: "0 auto", padding: "2rem" }}>
    <PageHeader title="Join a shared care episode" />
    {!loaded.ok || !loaded.value ? <p>This invitation is unavailable for the current identity, or it has expired or been revoked. In the local demo, choose the invited sample person and reload this page.</p> : <>
      <p>Joining as {loaded.value.actor.display_name} · role: {loaded.value.invitation.role.toLowerCase()}.</p><p>Bill review: {loaded.value.invitation.can_review ? "allowed" : "not allowed"} · Payment approval: {loaded.value.invitation.can_approve ? "allowed" : "not allowed"}.</p><p>Expires {formatDateTime(loaded.value.invitation.expires_at)}. Joining grants access to the episode&apos;s shared documents and financial history.</p><JoinForm token={token} />
    </>}
  </div>;
}
