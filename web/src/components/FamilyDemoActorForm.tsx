"use client";

import { useActionState, useState } from "react";
import { switchDemoActor } from "@/app/demo-actor-actions";
import type { UserOut } from "@/lib/types";
import { Button } from "@/components/ui";
import { usePathname } from "next/navigation";
import styles from "./FamilyDemoActor.module.css";

export function FamilyDemoActorForm({ users, currentId }: { users: UserOut[]; currentId: string }) {
  const pathname = usePathname();
  const [selected, setSelected] = useState(currentId);
  const [, action, pending] = useActionState(async (_state: null, data: FormData) => { await switchDemoActor(data); window.location.reload(); return null; }, null);
  if (pathname.startsWith("/upload/") || pathname.startsWith("/provider/")) return null;
  return <aside className={styles.bar} aria-label="Local demo identity"><form action={action}>
    <label htmlFor="demo-actor">Try the demo as</label>
    <select id="demo-actor" name="actor_id" value={selected} onChange={(event) => setSelected(event.target.value)}>{users.filter((user) => user.id === currentId || !/^Synthetic (durable acceptance|crash acceptance|overlapping webhook)$/.test(user.display_name)).map((user) => <option key={user.id} value={user.id}>{user.display_name}</option>)}</select>
    <Button type="submit" variant="secondary" pending={pending}>Switch person</Button>
    <span>Try the demo as a different family member. This does not sign in to a real account.</span>
  </form></aside>;
}
