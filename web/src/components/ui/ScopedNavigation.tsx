"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import styles from "./SiteHeader.module.css";

/** Capability pages have their own task and expose no payer navigation. */
export function ScopedNavigation() {
  const path = usePathname();
  if (path.startsWith("/upload/") || path.startsWith("/provider/respond/")) return null;
  return <nav aria-label="Main" className={styles.nav}><Link href="/cases" className={styles.navLink}>Care records</Link></nav>;
}
