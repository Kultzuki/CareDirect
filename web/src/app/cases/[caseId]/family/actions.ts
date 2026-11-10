"use server";

import { refresh } from "next/cache";
import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isUuid } from "@/lib/validation";

export type FamilyCommand = "invite" | "member" | "contribution" | "reverse" | "allocate" | "revoke" | "read" | "demo";
export interface FamilyActionState { error?: string; message?: string; invitationPath?: string }

export async function familyAction(caseId: string, command: FamilyCommand, targetId: string, requestId: string, _state: FamilyActionState, data: FormData): Promise<FamilyActionState> {
  void _state;
  if (!isUuid(caseId)) return { error: "Episode unavailable." };
  const value = (key: string) => String(data.get(key) ?? "").trim();
  const permissions = { role: value("role"), can_review: data.has("can_review"), can_approve: data.has("can_approve") };
  let path = "";
  let body: Record<string, unknown> = {};
  if (command === "invite") { path = "invitations"; body = { ...permissions, recipient_email: value("recipient_email") }; }
  if (command === "member") { path = `members/${seg(targetId)}`; body = { ...permissions, active: data.has("active"), note: value("note") }; }
  if (command === "contribution") { path = "contributions"; body = { user_id: value("user_id"), amount: value("amount"), currency: value("currency"), contributed_on: value("contributed_on"), reference: value("reference") || null, note: value("note"), request_id: requestId }; }
  if (command === "reverse") { path = `contributions/${seg(targetId)}/reverse`; body = { note: value("note"), request_id: requestId }; }
  if (command === "allocate") {
    path = "allocations";
    body = { line_item_id: targetId, source_fingerprint: value("source_fingerprint"), request_id: requestId, note: value("note"), shares: [...data.entries()].filter(([key, amount]) => key.startsWith("share:") && String(amount).trim() && !/^0(?:\.0+)?$/.test(String(amount).trim())).map(([key, amount]) => ({ user_id: key.slice(6), amount: String(amount).trim() })) };
  }
  if (command === "revoke") path = `invitations/${seg(targetId)}/revoke`;
  if (command === "read") path = `notifications/${seg(targetId)}/read`;
  if (command === "demo") { path = "demo-identities"; body = { display_name: value("display_name"), email: value("email") }; }
  if (!path) return { error: "Unknown family action." };
  try {
    const actor = await getDemoPayer();
    if (!actor) return { error: "Select a local demo identity." };
    const result = await apiPostJson<{ token?: string }>(`/api/cases/${seg(caseId)}/family/${path}`, body, { actorId: actor.id });
    refresh();
    return { message: command === "invite" ? "Invitation created. Share this link with the intended person; no email was sent." : command === "demo" ? "Synthetic identity created. Invite its .invalid email, then switch identities to accept." : "Family record updated. No hospital payment or PayPal credit was created.", ...(result.token ? { invitationPath: `/family/join/${result.token}` } : {}) };
  } catch (error) { return { error: error instanceof ApiError ? error.message : "The family action could not be completed." }; }
}
