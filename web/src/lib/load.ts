import "server-only";

import { ApiError } from "./api";

export type Loaded<T> = { ok: true; value: T } | { ok: false; error: ApiError };

/**
 * Runs a data load and turns an API failure into a value the page can render. Anything that is
 * not an ApiError (a bug) is rethrown so the error boundary shows it.
 */
export async function attempt<T>(load: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, value: await load() };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error };
    throw error;
  }
}
