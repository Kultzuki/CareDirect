import type { ProviderResponseOut } from "@/lib/provider-types";

export interface ProviderFormState {
  status: "idle" | "error" | "success";
  message?: string;
  response?: ProviderResponseOut;
}

export const INITIAL_PROVIDER_STATE: ProviderFormState = { status: "idle" };
