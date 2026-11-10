import type { UploadableDocumentType } from "@/lib/types";

/** Result of creating an upload link. The token is shown once, here, and not stored. */
export type UploadLinkState =
  | { status: "idle" }
  | {
      status: "success";
      path: string;
      expiresAt: string;
      maxUploads: number;
      documentTypes: UploadableDocumentType[];
    }
  | { status: "error"; message: string };

export type ExtractState = { status: "idle" } | { status: "error"; message: string };

export const INITIAL_LINK_STATE: UploadLinkState = { status: "idle" };
export const INITIAL_EXTRACT_STATE: ExtractState = { status: "idle" };
