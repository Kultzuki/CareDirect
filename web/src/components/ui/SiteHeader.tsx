import Link from "next/link";
import { Suspense } from "react";

import styles from "./SiteHeader.module.css";
import { ScopedNavigation } from "./ScopedNavigation";

function Mark() {
  // A sheet of paper with one highlighted line: the product in one picture.
  return (
    <svg
      width="30"
      height="30"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={styles.mark}
    >
      <path
        d="M5 2.8h9.3L19 7.5v13.7H5z"
        fill="var(--cd-color-sheet)"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path
        d="M14.3 2.8v4.7H19"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <rect x="7.4" y="10.6" width="9.2" height="3.6" rx="0.7" fill="var(--cd-prov-review-mark)" />
      <path d="M8 18h5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

/** The app frame. The product name is a link, not a heading: each page owns its single h1. */
export function SiteHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          <Mark />
          <span className={styles.name}>CareDirect</span>
        </Link>
        <Suspense fallback={null}><ScopedNavigation /></Suspense>
        <p className={styles.sandbox}>
          <span className={styles.sandboxStrong}>Demo:</span> sample records · test payments only
        </p>
      </div>
    </header>
  );
}
