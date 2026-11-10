"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { ExtractionViewOut, UploadLinkOut, UploadableDocumentType } from "@/lib/types";
import { isUploadableType, isUuid } from "@/lib/validation";

import type { ExtractState, UploadLinkState } from "./case-state";

const NO_PAYER = "No demo payer found. Run `python -m app.seed` in api/.";

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Reload the page and try again.";
}

/**
 * Creates a link that lets someone upload to this case and nothing else. The raw token comes
 * back once, in this return value; the API keeps only its hash. It is never logged here.
 */
export async function createUploadLink(
  caseId: string,
  _previous: UploadLinkState,
  formData: FormData,
): Promise<UploadLinkState> {
  if (!isUuid(caseId)) return { status: "error", message: "That case was not found." };

  const chosen = formData.getAll("document_types").filter(isUploadableType);
  const documentTypes = [...new Set(chosen)] as UploadableDocumentType[];
  if (documentTypes.length === 0) {
    return { status: "error", message: "Choose at least one kind of document." };
  }

  try {
    const payer = await getDemoPayer();
    if (!payer) return { status: "error", message: NO_PAYER };
    const link = await apiPostJson<UploadLinkOut>(
      `/api/cases/${seg(caseId)}/upload-links`,
      { document_types: documentTypes },
      { actorId: payer.id },
    );
    return {
      status: "success",
      path: `/upload/${link.token}`,
      expiresAt: link.expires_at,
      maxUploads: link.max_uploads,
      documentTypes: link.document_types,
    };
  } catch (error) {
    return { status: "error", message: message(error) };
  }
}

/**
 * Runs extraction on one stored document. On success the payer lands on the review page; if
 * extraction fails the API says why and the document stays available for another try.
 */
export async function extractDocument(caseId: string, documentId: string): Promise<ExtractState> {
  if (!isUuid(caseId) || !isUuid(documentId)) {
    return { status: "error", message: "That document was not found." };
  }

  try {
    const payer = await getDemoPayer();
    if (!payer) return { status: "error", message: NO_PAYER };
    await apiPostJson<ExtractionViewOut>(
      `/api/documents/${seg(documentId)}/extract`,
      {},
      { actorId: payer.id, timeoutMs: 240_000 },
    );
  } catch (error) {
    // "Already extracted" is not a failure: the reviewer wants the existing extraction.
    const already =
      error instanceof ApiError && error.status === 409 && /already extracted/i.test(error.message);
    if (!already) {
      // A failed extraction changes the document's status, so refresh the row as well.
      refresh();
      return { status: "error", message: message(error) };
    }
  }

  redirect(`/cases/${seg(caseId)}/review/${seg(documentId)}`);
}
