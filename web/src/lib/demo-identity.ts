import "server-only";
import { cookies } from "next/headers";

import { apiGet } from "./api";
import type { UserOut } from "./types";

// DEMO ONLY. The API chooses payer@demo.invalid deterministically; unrelated test actors
// can never become the family payer merely by being created first.
export async function getDemoPayer(): Promise<UserOut | null> {
  const selected = (await cookies()).get("caredirect-demo-actor")?.value;
  if (selected && /^[a-f0-9-]{36}$/.test(selected)) {
    const users = await apiGet<UserOut[]>("/api/users");
    const actor = users.find((user) => user.id === selected);
    if (actor) return actor;
  }
  return apiGet<UserOut | null>("/api/demo/identity");
}
