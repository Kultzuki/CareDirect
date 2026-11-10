import { ApiError, apiGetDownload, seg } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";
import { isUuid } from "@/lib/validation";

const HEADERS = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'" };

export async function GET(request: Request, { params }: { params: Promise<{caseId: string}> }) {
  const { caseId } = await params;
  const format = new URL(request.url).searchParams.get("format");
  if (!isUuid(caseId) || (format !== "json" && format !== "html")) return new Response("Evidence format not found.", { status: 404, headers: HEADERS });
  try {
    const payer = await getDemoPayer();
    if (!payer) return new Response("Evidence access unavailable.", { status: 403, headers: HEADERS });
    const result = await apiGetDownload(`/api/cases/${seg(caseId)}/evidence?format=${format}`, payer.id);
    return new Response(result.body, { headers: { ...HEADERS, "Content-Type": format === "json" ? "application/json" : "text/html; charset=utf-8", "Content-Disposition": `attachment; filename="caredirect-evidence.${format}"` } });
  } catch (error) { return new Response("Evidence is unavailable. Return to the case and try again.", { status: error instanceof ApiError ? error.status : 503, headers: HEADERS }); }
}
