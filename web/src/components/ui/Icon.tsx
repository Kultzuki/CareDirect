// Small stroke icons, drawn for this app. Always decorative: the meaning is in adjacent text,
// so every icon is aria-hidden.

export type IconName =
  | "alert"
  | "check"
  | "cross"
  | "pencil"
  | "info"
  | "document"
  | "upload"
  | "lock"
  | "copy";

const PATHS: Record<IconName, React.ReactNode> = {
  alert: (
    <>
      <path d="M12 3.6 21.6 20H2.4z" />
      <path d="M12 10v4.6" />
      <path d="M12 17.4v.2" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m7.8 12.4 2.9 2.9 5.5-6" />
    </>
  ),
  cross: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m9 9 6 6M15 9l-6 6" />
    </>
  ),
  pencil: (
    <>
      <path d="M4 20l.9-4.1L16.2 4.6a1.8 1.8 0 0 1 2.5 0l.7.7a1.8 1.8 0 0 1 0 2.5L8.1 19.1z" />
      <path d="m14.6 6.2 3.2 3.2" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.6" />
      <path d="M12 7.6v.2" />
    </>
  ),
  document: (
    <>
      <path d="M6 3h8.2L19 7.8V21H6z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h7M9 16.5h5" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V5" />
      <path d="m7.6 9.4 4.4-4.4 4.4 4.4" />
      <path d="M5 19h14" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="10" rx="2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </>
  ),
  copy: (
    <>
      <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
      <path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5" />
    </>
  ),
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ flex: "none" }}
    >
      {PATHS[name]}
    </svg>
  );
}
