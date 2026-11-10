import type { ReactNode } from "react";

import { Icon } from "./Icon";
import styles from "./FormField.module.css";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}

/**
 * Label, hint and error for one control, wired together. The control is a render prop so the
 * caller keeps full control of the element:
 *
 *   <FormField id="reason" label="Reason for changes" hint="Shown in the history.">
 *     {(control) => <textarea {...control} name="reason" />}
 *   </FormField>
 */
export function FormField({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: (control: FieldControlProps) => ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })}
      {error ? (
        <p id={errorId} className={styles.error}>
          <Icon name="cross" size={16} />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}
