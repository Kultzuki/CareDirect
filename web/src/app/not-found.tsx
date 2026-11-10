import { ButtonLink, PageHeader } from "@/components/ui";

export default function NotFound() {
  return (
    <section style={{ background:"var(--cd-color-sheet)", border:"1px solid var(--cd-color-rule)", borderRadius:"12px", padding:"2rem", maxWidth:"48rem", margin:"2rem auto" }}>
      <PageHeader title="We can’t find that page" />
      <p>The case or document may have been removed, or the address may be mistyped.</p>
      <p style={{ marginTop: "var(--cd-space-4)" }}>
        <ButtonLink href="/cases" variant="secondary">
          Go to all cases
        </ButtonLink>
      </p>
    </section>
  );
}
