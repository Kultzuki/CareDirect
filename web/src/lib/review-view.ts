import type { ExtractionViewOut, ReviewViewData } from "./types";

/**
 * Copies only what the review form renders. The API's view also carries the model's raw
 * payload; building a new object here keeps it out of what is sent to the browser.
 */
export function toReviewView(view: ExtractionViewOut): ReviewViewData {
  return {
    document_type: view.document_type,
    id: view.id,
    fields: view.fields,
    review_required: view.review_required,
    promotion_blockers: view.promotion_blockers,
    can_promote: view.can_promote,
  };
}

/** The currency used to format money fields: the extracted currency, else the case's. */
export function displayCurrency(view: Pick<ExtractionViewOut, "fields">, caseCurrency: string) {
  const extracted = view.fields.find((f) => f.path === "currency")?.value ?? null;
  return extracted && /^[A-Z]{3}$/.test(extracted) ? extracted : caseCurrency;
}
