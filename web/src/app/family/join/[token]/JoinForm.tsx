"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui";
import { acceptFamilyInvitation } from "./actions";

export function JoinForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(acceptFamilyInvitation.bind(null, token), {});
  return <form action={action}><p><label><input type="checkbox" name="confirmed" required />I want to join this episode with the permissions shown.</label></p><Button type="submit" pending={pending}>Accept family invitation</Button>{state.error && <p role="alert">{state.error}</p>}</form>;
}
