import { apiGet } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { UserOut } from "@/lib/types";
import { FamilyDemoActorForm } from "./FamilyDemoActorForm";

export async function FamilyDemoActor() {
  let users: UserOut[];
  let current: UserOut | null;
  try { [users, current] = await Promise.all([apiGet<UserOut[]>("/api/users"), getDemoPayer()]); }
  catch { return null; }
  if (users.length < 2) return null;
  return <FamilyDemoActorForm users={users} currentId={current?.id ?? users[0].id} />;
}
