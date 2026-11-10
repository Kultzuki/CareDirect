import { ApiError, apiGetDownload } from "@/lib/api";
import { getDemoPayer } from "@/lib/demo-identity";

const HEADERS = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox" };
const SAMPLES = ["usd_bill.pdf", "usd_estimate.pdf", "usd_receipt.pdf", "usd_bill.png"];

export async function GET(_request: Request, { params }: { params: Promise<{name: string}> }) {
  const { name } = await params;
  if (!SAMPLES.includes(name)) return new Response("Sample not found.", { status: 404, headers: HEADERS });
  try {
    const payer = await getDemoPayer();
    if (!payer) return new Response("Sample access unavailable.", { status: 403, headers: HEADERS });
    const result = await apiGetDownload(`/api/demo/samples/${name}`, payer.id);
    return new Response(result.body, { headers: { ...HEADERS, "Content-Type": name.endsWith(".png") ? "image/png" : "application/pdf", "Content-Disposition": `attachment; filename="synthetic-${name}"` } });
  } catch (error) { return new Response("The sample is unavailable. Return to Cases and try again.", { status: error instanceof ApiError ? error.status : 503, headers: HEADERS }); }
}
