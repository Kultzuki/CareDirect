"use server";

import { refresh } from "next/cache";

import { ApiError, apiGet, apiPostJson, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { fieldInputError, normaliseFieldInput } from "@/lib/field-input";
import type {
  CorrectionIn,
  ExtractionViewOut,
  PromoteOut,
  RevisionCreate,
} from "@/lib/types";
import { isUuid } from "@/lib/validation";

import type { ReviewActionState } from "./review-state";

const NO_PAYER = "No demo payer found. Run `python -m app.seed` in api/.";
const BAD_REQUEST = "That request was not valid. Reload the page and try again.";

function failure(message: string): ReviewActionState {
  return { status: "error", message };
}

function apiFailure(error: unknown): ReviewActionState {
  if (error instanceof ApiError) return failure(error.message);
  return failure("Something went wrong. Reload the page and try again.");
}

function text(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value : "";
}

/**
 * Saves the payer's corrections and confirmations as one revision. The client sends form
 * values only. The action re-fetches the extraction, refuses any path that is not in it, and
 * sends just the fields that were changed or confirmed. The original AI output is never edited.
 */
export async function saveReview(
  caseId: string,
  documentId: string,
  extractionId: string,
  _previous: ReviewActionState,
  formData: FormData,
): Promise<ReviewActionState> {
  if (!isUuid(caseId) || !isUuid(documentId) || !isUuid(extractionId)) {
    return failure(BAD_REQUEST);
  }
  const reason = text(formData, "reason").trim();
  if (reason.length === 0) return failure("Add a reason for your changes.");
  if (reason.length > 2000) return failure("Keep the reason under 2000 characters.");

  try {
    const payer = await getDemoPayer();
    if (!payer) return failure(NO_PAYER);

    const view = await apiGet<ExtractionViewOut>(`/api/documents/${seg(documentId)}/extraction`, {
      actorId: payer.id,
    });
    if (view.id !== extractionId || view.case_id !== caseId) {
      return failure("This extraction has changed. Reload the page and try again.");
    }
    const fields = new Map(view.fields.map((field) => [field.path, field]));

    const corrections: CorrectionIn[] = [];
    const corrected = new Set<string>();
    const confirmed = new Set<string>();

    for (const [key, raw] of formData.entries()) {
      if (typeof raw !== "string") continue;

      if (key.startsWith("value:")) {
        const path = key.slice("value:".length);
        const field = fields.get(path);
        if (!field) return failure(BAD_REQUEST);

        const submitted = raw.trim();
        if (submitted === (field.value ?? "")) continue; // unchanged

        const problem = fieldInputError(field.kind, submitted);
        if (problem) return failure(`${field.label}: ${problem}`);

        const value = normaliseFieldInput(field.kind, submitted);
        let source: CorrectionIn["source"] = null;
        if (value !== null && field.source === null) {
          const pageText = text(formData, `page:${path}`).trim();
          const page = /^\d{1,4}$/.test(pageText) ? Number.parseInt(pageText, 10) : 0;
          const snippet = text(formData, `snippet:${path}`).trim();
          if (page < 1 || page > 1000 || snippet.length === 0) {
            return failure(`${field.label}: add the page and the text where it appears.`);
          }
          source = { page, snippet: snippet.slice(0, 500) };
        }
        corrections.push({ path, value, source });
        corrected.add(path);
      } else if (key.startsWith("confirm:")) {
        const path = key.slice("confirm:".length);
        if (!fields.has(path)) return failure(BAD_REQUEST);
        confirmed.add(path);
      }
    }

    // A value that was corrected is not also confirmed: the API refuses both for one path.
    const confirmedPaths = [...confirmed].filter((path) => !corrected.has(path));
    if (corrections.length === 0 && confirmedPaths.length === 0) {
      return failure("Change a value or confirm a field before saving.");
    }

    const body: RevisionCreate = { corrections, confirmed_paths: confirmedPaths, reason };
    await apiPostJson<ExtractionViewOut>(
      `/api/extractions/${seg(extractionId)}/revisions`,
      body,
      { actorId: payer.id },
    );
  } catch (error) {
    return apiFailure(error);
  }

  refresh();
  return { status: "success", message: "Review saved." };
}

/**
 * Adds the reviewed extraction to the case. The API decides whether that is allowed and says
 * why not; this action only forwards the request for the demo payer.
 */
export async function promoteExtraction(
  caseId: string,
  documentId: string,
  extractionId: string,
): Promise<ReviewActionState> {
  if (!isUuid(caseId) || !isUuid(documentId) || !isUuid(extractionId)) {
    return failure(BAD_REQUEST);
  }
  try {
    const payer = await getDemoPayer();
    if (!payer) return failure(NO_PAYER);

    const view = await apiGet<ExtractionViewOut>(`/api/documents/${seg(documentId)}/extraction`, {
      actorId: payer.id,
    });
    if (view.id !== extractionId || view.case_id !== caseId) {
      return failure("This extraction has changed. Reload the page and try again.");
    }
    await apiPostJson<PromoteOut>(`/api/extractions/${seg(extractionId)}/promote`, {}, {
      actorId: payer.id,
    });
  } catch (error) {
    return apiFailure(error);
  }

  refresh();
  return { status: "success", message: "Added to case." };
}
