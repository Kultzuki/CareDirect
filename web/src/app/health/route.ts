import { connection } from "next/server";

export async function GET() {
  // Answer at request time; do not serve a build-time prerendered response.
  await connection();
  return Response.json({ status: "ok", service: "web" });
}
