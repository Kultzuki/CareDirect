import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

// Runs once before the tests. It makes sure the demo payer exists and writes the synthetic
// fixture documents (no real medical data) to a gitignored folder.
export default function globalSetup(): void {
  const apiDir = path.resolve(__dirname, "..", "..", "api");
  const python =
    process.platform === "win32"
      ? path.join(apiDir, ".venv", "Scripts", "python.exe")
      : path.join(apiDir, ".venv", "bin", "python");
  const generated = path.resolve(__dirname, "../../output/playwright/fixtures");
  fs.mkdirSync(generated, { recursive: true });

  const run = (args: string[]) =>
    execFileSync(python, args, { cwd: apiDir, encoding: "utf8", stdio: "pipe" });

  run(["-m", "app.seed", "--with-example"]); // Explicit isolated-test fixture only.
  run(["-m", "app.extraction.synthetic", "--out", generated]);

  // PNG bytes under a .pdf name: the declared type will not match the content.
  fs.copyFileSync(
    path.join(generated, "photographed_bill.png"),
    path.join(generated, "mismatch.pdf"),
  );
}
