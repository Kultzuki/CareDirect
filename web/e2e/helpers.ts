import path from "node:path";

import { expect, type APIRequestContext } from "@playwright/test";

// The tests talk to FastAPI directly only to arrange data and to check results.
// The screens under test reach FastAPI server-side through Next.js.
export const API_URL = "http://127.0.0.1:8100";

export type UploadableType = "BILL" | "ESTIMATE" | "RECEIPT";

export interface CaseRef {
  id: string;
  caseReference: string;
}

export interface LinkRef {
  token: string;
  path: string;
}

export async function getDemoPayer(request: APIRequestContext): Promise<string> {
  const res = await request.get(`${API_URL}/api/demo/identity`);
  expect(res.ok()).toBe(true);
  const payer = (await res.json()) as { id: string; role: string };
  expect(payer.role, "the designated seeded demo payer").toBe("PAYER");
  return payer.id;
}

/** A fresh case per test, so the one-copy-per-case SHA-256 rule never trips a second run. */
export async function createCase(request: APIRequestContext, payerId: string): Promise<CaseRef> {
  const res = await request.post(`${API_URL}/api/cases`, {
    headers: { "X-Demo-User-Id": payerId },
    data: { patient_alias: "E2E synthetic patient", currency: "INR" },
  });
  expect(res.status()).toBe(201);
  const body = (await res.json()) as { id: string; case_reference: string };
  return { id: body.id, caseReference: body.case_reference };
}

export async function createUploadLink(
  request: APIRequestContext,
  payerId: string,
  caseId: string,
  types: UploadableType[],
): Promise<LinkRef> {
  const res = await request.post(`${API_URL}/api/cases/${caseId}/upload-links`, {
    headers: { "X-Demo-User-Id": payerId },
    data: { document_types: types },
  });
  expect(res.status()).toBe(201);
  const body = (await res.json()) as { token: string };
  return { token: body.token, path: `/upload/${body.token}` };
}

/** Absolute path of a generated synthetic fixture, such as "photographed_bill.png". */
export function fixture(name: string): string {
  return path.resolve(__dirname, "../../output/playwright/fixtures", name);
}

export const reviewPath = (caseId: string) => `/cases/${caseId}/review`;

/** The case as the API reports it, for checking what the UI actually changed. */
export async function getCase(request: APIRequestContext, payerId: string, caseId: string) {
  const res = await request.get(`${API_URL}/api/cases/${caseId}`, {
    headers: { "X-Demo-User-Id": payerId },
  });
  expect(res.ok()).toBe(true);
  return (await res.json()) as {
    bills: {
      source_type: string;
      printed_total: string | null;
      line_items: {
        line_number: number;
        line_total: string;
        status: string;
        source_type: string;
      }[];
    }[];
  };
}
