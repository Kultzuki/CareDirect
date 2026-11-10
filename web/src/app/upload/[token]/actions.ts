"use server";

import { ApiError, apiPostBytes, seg } from "@/lib/api";
import type { UploadReceiptOut } from "@/lib/types";
import {
  ALLOWED_UPLOAD_MIME,
  isUploadableType,
  isUploadToken,
} from "@/lib/validation";

import type { UploadState } from "./upload-state";

const INVALID_LINK =
  "This upload link is invalid or has expired. Ask the person who sent it for a new link.";

function failure(message: string, hint?: string): UploadState {
  return { status: "error", message, hint };
}

function sentence(text: string): string {
  const trimmed = text.trim();
  if (trimmed.length === 0) return "The file could not be uploaded.";
  const capitalised = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalised) ? capitalised : `${capitalised}.`;
}

/**
 * Sends one file to the API as a raw request body. The upload token is the only credential, so
 * it is validated here, never logged, and never echoed back. The browser never calls FastAPI.
 */
export async function uploadDocument(
  _previous: UploadState,
  formData: FormData,
): Promise<UploadState> {
  const token = formData.get("token");
  const documentType = formData.get("document_type");
  const file = formData.get("file");

  if (!isUploadToken(token)) return failure(INVALID_LINK);
  if (!isUploadableType(documentType)) return failure("Choose a document type.");
  if (!(file instanceof File) || file.size === 0) {
    return failure("Choose a file to upload.");
  }
  if (!ALLOWED_UPLOAD_MIME.includes(file.type)) {
    return failure("Only PDF, JPG and PNG files can be uploaded.");
  }

  try {
    const receipt = await apiPostBytes<UploadReceiptOut>(
      `/api/uploads/${seg(token)}?document_type=${seg(documentType)}`,
      file,
      file.type,
    );
    return {
      status: "success",
      documentType: receipt.document_type,
      pageCount: receipt.page_count,
      fileSize: receipt.file_size,
      reference: receipt.sha256.slice(0, 12),
      uploadsRemaining: receipt.uploads_remaining,
    };
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 403) return failure(INVALID_LINK);
      if (error.status === 503) {
        return failure("The upload service is not reachable right now.", "Try again in a moment.");
      }
      return failure(
        sentence(error.message),
        error.status === 422
          ? "Check that you chose a PDF, JPG or PNG, and that it is the right file."
          : undefined,
      );
    }
    return failure("The file could not be uploaded.", "Try again in a moment.");
  }
}
