import Link from "next/link";
import type { ComponentProps } from "react";

import styles from "./Button.module.css";

type Variant = "primary" | "secondary" | "quiet";

function classes(variant: Variant, extra?: string, pending?: boolean, full?: boolean) {
  return [styles.button, styles[variant], pending ? styles.pending : "", full ? styles.full : "", extra]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = ComponentProps<"button"> & {
  variant?: Variant;
  /** Shows a spinner and disables the button. Keep the label; it is still read out. */
  pending?: boolean;
  full?: boolean;
};

export function Button({
  variant = "primary",
  pending = false,
  full = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={classes(variant, className, pending, full)}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
    >
      {pending ? <span className={styles.spinner} aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

type ButtonLinkProps = ComponentProps<typeof Link> & { variant?: Variant; full?: boolean };

export function ButtonLink({
  variant = "primary",
  full = false,
  className,
  ...rest
}: ButtonLinkProps) {
  return <Link {...rest} className={classes(variant, className, false, full)} />;
}
