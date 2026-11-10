// Input checks used by Server Actions and pages. Everything from FormData, the URL or a
// bound argument is untrusted until it passes one of these.

import type { UploadableDocumentType } from "./types";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export const UPLOADABLE_TYPES: readonly UploadableDocumentType[] = ["BILL", "ESTIMATE", "RECEIPT", "INSURANCE_PREAUTH", "INSURANCE_SETTLEMENT", "INSURER_PAYMENT"];

export const ALLOWED_UPLOAD_MIME: readonly string[] = [
  "application/pdf",
  "image/jpeg",
  "image/png",
];

export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

export function isUploadToken(value: unknown): value is string {
  return typeof value === "string" && TOKEN_PATTERN.test(value);
}

export function isUploadableType(value: unknown): value is UploadableDocumentType {
  return typeof value === "string" && (UPLOADABLE_TYPES as readonly string[]).includes(value);
}
