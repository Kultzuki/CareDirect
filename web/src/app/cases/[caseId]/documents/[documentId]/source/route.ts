import { ApiError, apiGet, apiGetDocumentContent, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import type { DocumentOut } from "@/lib/types";
import { isUuid } from "@/lib/validation";

const PRIVATE_HEADERS = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'; sandbox" };

export async function GET(_request: Request, { params }: { params: Promise<{ caseId: string; documentId: string }> }) {
  const { caseId, documentId } = await params;
  if (!isUuid(caseId) || !isUuid(documentId)) return new Response("Source not found.", { status: 404, headers: PRIVATE_HEADERS });
  try {
    const payer = await getDemoPayer();
    if (!payer) return new Response("Source access is unavailable.", { status: 403, headers: PRIVATE_HEADERS });
    const document = await apiGet<DocumentOut>(`/api/documents/${seg(documentId)}`, { actorId: payer.id });
    if (document.case_id !== caseId) return new Response("Source not found.", { status: 404, headers: PRIVATE_HEADERS });
    const content = await apiGetDocumentContent(documentId, payer.id);
    const allowed = ["application/pdf", "image/png", "image/jpeg"];
    if (!allowed.includes(document.mime_type)) return new Response("Source type unavailable.", { status: 415, headers: PRIVATE_HEADERS });
    const extension = document.mime_type === "application/pdf" ? "pdf" : document.mime_type === "image/png" ? "png" : "jpg";
    return new Response(content.body, { headers: { ...PRIVATE_HEADERS, "Content-Type": document.mime_type, "Content-Disposition": `inline; filename="synthetic-source.${extension}"` } });
  } catch (error) {
    return new Response("Source access is unavailable. Return to the case and try again.", { status: error instanceof ApiError ? error.status : 503, headers: PRIVATE_HEADERS });
  }
}
