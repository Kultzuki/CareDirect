import type { ProviderPreviewOut } from "@/lib/provider-types";

export interface WorkspaceState {
  status: "idle" | "error" | "success";
  message?: string;
  path?: string;
  expiresAt?: string;
  preview?: ProviderPreviewOut;
}

export const INITIAL_WORKSPACE_STATE: WorkspaceState = { status: "idle" };
