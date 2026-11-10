"""Lead-owned isolated browser runner with capability URL redaction in console output."""

import os
import re
import subprocess
import sys

from app.config import REPO_ROOT, Settings

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env.update(
        DATABASE_URL=Settings().test_database_url,
        CI="1",
        CAREDIRECT_E2E_MOCK="1",
        STUDIO_LOCAL_EVALUATION="true",
    )
    if not env["DATABASE_URL"].endswith("/caredirect_test"):
        raise RuntimeError("Browser runner requires isolated caredirect_test")
    command = [
        "npm.cmd" if os.name == "nt" else "npm",
        "run",
        "test:e2e",
        "--",
        *sys.argv[1:],
        "--reporter=line",
    ]
    process = subprocess.Popen(  # noqa: S603 - explicit local operator CLI, no shell interpolation
        command,
        cwd=REPO_ROOT / "web",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in process.stdout:
        # Retained ignored traces remain private; console never reveals capability paths.
        line = re.sub(
            r"((?:/api)?/uploads?/|/provider/respond/|/api/provider/respond/)[A-Za-z0-9_-]{20,}",
            r"\1[redacted]",
            line,
        )
        print(line, end="", flush=True)
    raise SystemExit(process.wait())
