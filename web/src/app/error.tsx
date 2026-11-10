"use client";

import { Button, Notice, PageHeader } from "@/components/ui";

// The message of an unexpected error is not shown: it may contain details a reader should not
// see. The digest lets someone find the full error in the server log.
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section style={{ background:"var(--cd-color-sheet)", border:"1px solid var(--cd-color-rule)", borderRadius:"12px", padding:"2rem", maxWidth:"48rem", margin:"2rem auto" }}>
      <PageHeader title="Something went wrong" />
      <Notice tone="error" title="This page could not be shown">
        <p>Try again. If it keeps happening, tell the team{error.digest ? ` (reference ${error.digest})` : ""}.</p>
      </Notice>
      <p style={{ marginTop: "var(--cd-space-4)" }}>
        <Button variant="secondary" onClick={() => reset()}>
          Try again
        </Button>
      </p>
    </section>
  );
}
