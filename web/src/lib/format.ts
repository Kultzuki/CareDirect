// Display helpers shared by server and client components. Output is deterministic (fixed locale
// and UTC) so server-rendered and hydrated text always match. Not for money: see money.ts.

import type { CaseStatus, DocumentType, ExtractionStatus, PaymentMethod } from "./types";

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  BILL: "Bill",
  ESTIMATE: "Estimate",
  RECEIPT: "Receipt",
  PROVIDER_SUPPORTING: "Provider supporting document",
  OTHER: "Other document",
  INSURANCE_PREAUTH: "Insurance initial approval",
  INSURANCE_SETTLEMENT: "Insurance settlement statement",
  INSURER_PAYMENT: "Insurance payment record",
};

export const EXTRACTION_STATUS_LABEL: Record<ExtractionStatus, string> = {
  NOT_STARTED: "Ready to read",
  EXTRACTED: "Details ready to check",
  FAILED: "Could not read document",
};

export const PAYMENT_METHOD_LABEL: Record<PaymentMethod, string> = {
  UPI: "UPI",
  CASH: "Cash",
  CARD: "Card",
  BANK_TRANSFER: "Bank transfer",
  OTHER: "Other",
};

export const PAYMENT_METHODS = Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[];

export const CASE_STATUS_LABEL: Record<CaseStatus, string> = {
  DRAFT: "Draft",
  UNDER_REVIEW: "Under review",
  AWAITING_PROVIDER: "Awaiting provider",
  READY_FOR_APPROVAL: "Ready for approval",
  RECONCILIATION_REQUIRED: "Amounts need checking",
  CLOSED: "Closed",
};

const MIME_LABEL: Record<string, string> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPEG image",
  "image/png": "PNG image",
};

export function documentTypeLabel(type: string): string {
  return DOCUMENT_TYPE_LABEL[type as DocumentType] ?? type;
}

export function mimeLabel(mime: string): string {
  return MIME_LABEL[mime] ?? mime;
}

export function pageCountLabel(pages: number | null): string {
  if (pages === null) return "Page count unknown";
  return pages === 1 ? "1 page" : `${pages} pages`;
}

export function lineCountLabel(lines: number): string {
  return lines === 1 ? "1 line" : `${lines} lines`;
}

/** File sizes only (never money): 1536 becomes "1.5 KB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Whole megabytes for limits, such as 20971520 becoming "20 MB". */
export function formatLimitMb(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

const dateFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const dateTimeFormat = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** "2026-11-02" becomes "2 Nov 2026". Anything else is returned unchanged. */
export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

/** An ISO timestamp as "8 Nov 2026, 21:00 UTC". */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : `${dateTimeFormat.format(date)} UTC`;
}
