import type { DocumentType } from "@/lib/types";

/** What the upload action returns. Only what the screen renders; never the raw API body. */
export type UploadState =
  | { status: "idle" }
  | {
      status: "success";
      documentType: DocumentType;
      pageCount: number | null;
      fileSize: number;
      /** First 12 characters of the SHA-256, so the uploader can quote a reference. */
      reference: string;
      uploadsRemaining: number;
    }
  | { status: "error"; message: string; hint?: string };

export const INITIAL_UPLOAD_STATE: UploadState = { status: "idle" };
