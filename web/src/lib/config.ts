// Server-side configuration only. API_BASE_URL has no NEXT_PUBLIC_ prefix, so it is not
// shipped to the browser. PayPal settings never belong in web/; they live in the API.
export const apiBaseUrl = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
