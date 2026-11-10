"use server";

import { cookies } from "next/headers";
import { apiGet } from "@/lib/api";
import type { UserOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

export async function switchDemoActor(data: FormData) {
  const id = String(data.get("actor_id") ?? "");
  if (!isUuid(id)) return;
  const users = await apiGet<UserOut[]>("/api/users");
  if (!users.some((user) => user.id === id)) return;
  (await cookies()).set("caredirect-demo-actor", id, { httpOnly: true, sameSite: "strict", path: "/", maxAge: 86400 });
}
