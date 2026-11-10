import { Icon, Notice } from "@/components/ui";
import type { ApiError } from "@/lib/api";

import styles from "./PageProblems.module.css";

/** Shown when the API answered with an error a page cannot recover from. */
export function ApiProblem({ error }: { error: ApiError }) {
  if (error.status === 503) {
    return (
      <Notice tone="error" title="CareDirect cannot load your records right now">
        <p>Ask the demo owner to restart the service, then reload this page.</p>
      </Notice>
    );
  }
  return (
    <Notice tone="error" title="This page could not be loaded">
      <p>{error.message}</p>
    </Notice>
  );
}

/** Shown when the database has no seeded payer to act as. */
export function NoDemoPayer() {
  return (
    <Notice tone="warning" title="The demo needs a sample person">
      <p>
        Run <code>python -m app.seed</code> in api/, then reload this page.
      </p>
    </Notice>
  );
}

/** Says out loud that the identity in use is a demo stand-in, not a signed-in person. */
export function DemoIdentityNote({ name }: { name: string }) {
  return (
    <p className={styles.identity} data-testid="demo-identity">
      <Icon name="lock" size={16} />
      <span>
        Viewing as {name}. This is a demo person, not a signed-in account.
      </span>
    </p>
  );
}
