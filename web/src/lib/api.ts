import "server-only";

import { apiBaseUrl } from "./config";

// Server-side FastAPI client. The browser never calls FastAPI: pages fetch here, and every
// mutation (including the file upload) is a Server Action that calls these helpers.
// Nothing in this file logs request paths, bodies or tokens.

const JSON_TIMEOUT_MS = 15_000;
const UPLOAD_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions {
  /** Demo identity sent as X-Demo-User-Id. Upload-token requests send none. */
  actorId?: string;
  timeoutMs?: number;
}

async function readError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `The CareDirect API answered with status ${res.status}.`;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      if (typeof record.error === "string") code = record.error;
      if (typeof record.message === "string" && record.message.length > 0) {
        message = record.message;
      }
    }
  } catch {
    // Keep the generic message when the body is not JSON.
  }
  return new ApiError(res.status, code, message);
}

async function send<T>(path: string, init: RequestInit, options: RequestOptions): Promise<T> {
  const headers = new Headers(init.headers);
  if (options.actorId) headers.set("X-Demo-User-Id", options.actorId);

  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs ?? JSON_TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(503, "api_unavailable", "The CareDirect API is not reachable.");
  }
  if (!res.ok) throw await readError(res);
  return (await res.json()) as T;
}

export function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return send<T>(path, { method: "GET" }, options);
}

export function apiPostJson<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return send<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    options,
  );
}

/** POST the raw bytes of a file. `contentType` is the declared MIME type. */
export function apiPostBytes<T>(path: string, body: Blob, contentType: string): Promise<T> {
  return send<T>(
    path,
    { method: "POST", headers: { "Content-Type": contentType }, body },
    { timeoutMs: UPLOAD_TIMEOUT_MS },
  );
}

/** Path segments from user input are always encoded before they reach a URL. */
export function seg(value: string): string {
  return encodeURIComponent(value);
}

/** Private document bytes are proxied by an authorized Next Route Handler, never a public URL. */
export async function apiGetDocumentContent(documentId: string, actorId: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl}/api/documents/${seg(documentId)}/content`, {
      headers: { "X-Demo-User-Id": actorId }, cache: "no-store", signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
    });
  } catch { throw new ApiError(503, "api_unavailable", "The source document is unavailable right now."); }
  if (!res.ok) throw await readError(res);
  return res;
}

/** Only the allowlisted evidence/sample Route Handlers call this server-side helper. */
export async function apiGetDownload(path: string, actorId: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl}${path}`, { headers: { "X-Demo-User-Id": actorId }, cache: "no-store", signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS) });
  } catch { throw new ApiError(503, "api_unavailable", "The download is unavailable right now."); }
  if (!res.ok) throw await readError(res);
  return res;
}
