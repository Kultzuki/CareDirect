/** What the review actions return to the form. Plain messages only. */
export type ReviewActionState =
  | { status: "idle" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

export const INITIAL_REVIEW_STATE: ReviewActionState = { status: "idle" };
