# CareDirect

A local synthetic medical-bill review prototype: upload evidence, review recorded extraction, clarify charges with a provider, approve an exact amount and reconcile PayPal Sandbox observations.

## Run

Python 3.11, Node.js and Docker are required. Preserve existing private environment files; examples contain configuration names only.

Terminal 1, from the repository root:

```powershell
docker compose up -d db
cd api
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Setup creates only the local demo payer identity. It does not create bills, cases or payment records. To intentionally load the old INR example, run `python -m app.seed --with-example` using the project virtual environment.

Terminal 2:

```powershell
cd web
npm ci
$env:API_BASE_URL="http://127.0.0.1:8000"
$env:STUDIO_LOCAL_EVALUATION="true"
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open http://127.0.0.1:3000/cases and create a treatment episode. With `GEMINI_API_KEY` configured,
document extraction uses Gemini; without it, auto mode uses recorded synthetic replay.
Review extracted values before promotion. Keep the app local until public access controls are implemented.

## Checks

From api: `.\.venv\Scripts\python.exe -m pytest -o addopts='' -q --tb=short`, Ruff check/format, and `.\.venv\Scripts\python.exe -m tests.run_browser`.
Tests deliberately populate/reset only caredirect_test. Never overlap database tests and browser tests. Browser artifacts are private, ignored and outside web. Do not overlap Next build and dev. From web: `npm run lint`, `npm run typecheck`, `npm run build`.

## Essential references

- [Developer handoff](docs/DEVELOPER_HANDOFF.md): next development assignment, full end-user UX priorities and acceptance criteria.
- [Architecture](docs/ARCHITECTURE.md): code map and financial rules.
- [Care episodes](docs/FEATURE_A_CARE_EPISODES.md): treatment-level records, overlap review and AI configuration.
- [Duplicate and overlap review](docs/FEATURE_C_DUPLICATE_OVERLAP.md): exact, near and cross-document questions with human review.
- [Insurance and TPA reconciliation](docs/FEATURE_D_INSURANCE_TPA.md): insurer approval, remittances, patient components and source-backed explanations.
- [Family collaboration](docs/FEATURE_E_FAMILY_COLLABORATION.md): episode roles, contributions, expense plans and in-app notifications.
- [UI overhaul](docs/UI_OVERHAUL.md): current whole-app layout, preview and verification scope.
- [Next-chat handoff](docs/NEXT_CHAT_HANDOFF.md): connected providers, quota limits, A/B workflow and verification.
- [Status](docs/STATUS.md): actual verification and remaining work.
- [Demo runbook](docs/DEMO_RUNBOOK.md): manual workflow and recovery.
- [Deployment guide](docs/DEPLOYMENT_GUIDE.md): user-operated hosting preparation.
- [PayPal feasibility](docs/PAYPAL_FEASIBILITY_CHECKLIST.md): tested account/API behavior.
- [Security](docs/SECURITY_NOTES.md) and [UI design](web/DESIGN.md).

Do not commit secrets, source uploads or private access URLs. No deployment, commit or push is automatic.
