import type { Metadata } from "next";
import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "@fontsource-variable/literata/opsz.css";
import "./globals.css";

import { SiteHeader } from "@/components/ui";
import { FamilyDemoActor } from "@/components/FamilyDemoActor";
import { Suspense } from "react";
import { WorkspaceFrame } from "@/components/workspace/WorkspaceFrame";

export const metadata: Metadata = {
  title: {
    default: "CareDirect",
    template: "%s | CareDirect",
  },
  description: "Understand hospital bills and share care costs as a family",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <a className="cd-skip-link" href="#main">
          Skip to main content
        </a>
        <SiteHeader />
        <Suspense fallback={null}><FamilyDemoActor /></Suspense>
        <Suspense fallback={<main id="main">Loading workspace…</main>}><WorkspaceFrame>{children}</WorkspaceFrame></Suspense>
      </body>
    </html>
  );
}
