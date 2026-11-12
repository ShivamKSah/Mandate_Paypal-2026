# Release readiness inventory

Read-only inventory, October 30, 2026. This describes the local build and the documented pre-release plan; it does not certify a production deployment.

This is the initial inventory. Its migration, packaging, locking, action-pin, and readiness findings were subsequently repaired. See [the final review summary](00-summary.md) and [operations evidence](04-operations.md) for current status. External provider and submission gates remain open.

## Findings

### P1 — No application image, production web serving, or database upgrade path

[`compose.yaml`](../../../compose.yaml) defines only a PostgreSQL 17 service. There is no API or web Dockerfile, reverse proxy/static-serving service, or application deployment definition. [`scripts/run-api.ps1`](../../../scripts/run-api.ps1) starts Uvicorn on loopback and [`scripts/run-web.ps1`](../../../scripts/run-web.ps1) starts Vite's development server on loopback. The API lifespan calls SQLAlchemy `Base.metadata.create_all` in [`apps/api/mandate/main.py`](../../../apps/api/mandate/main.py); no migration configuration or migration files are present. This is adequate for the stated local bootstrap, but cannot apply controlled upgrades to an existing database. README and implementation status explicitly identify migrations and deployment as pending. Before release, add a versioned migration path and a production-serving/deployment setup, then rehearse a clean install and upgrade.

### P1 — Release acceptance and external evidence remain open

[`docs/06-validation-and-demo.md`](../../06-validation-and-demo.md) keeps the full acceptance matrix and release checklist unchecked. [`docs/08-implementation-status.md`](../../08-implementation-status.md) records 82 local tests and a web build, while actual sandbox capture/refund/webhook evidence and a live model run remain unverified due to missing credentials. It also records known unresolved recovery cases for unknown provider outcomes and incomplete refund/reversal webhook transitions. Mocked provider fixtures do not satisfy the documented live-provider acceptance gate. Do not characterize the current revision as release-ready until the relevant gates pass or the product claims are narrowed to the verified fallback.

### P2 — Python installs are range-based, not locked

[`apps/api/pyproject.toml`](../../../apps/api/pyproject.toml) specifies compatible version ranges for runtime and test dependencies. No Python lockfile or constraints file was found. README's fresh setup uses `pip install -e "./apps/api[test]"`, so a clean install can resolve different dependency versions at different dates. Add a reproducible Python dependency lock/constraints mechanism before relying on repeatable CI or deployment builds. The frontend has `package-lock.json` and both README and CI use `npm ci`.

### P2 — CI actions are major-tagged, not immutable pins

[`.github/workflows/checks.yml`](../../../.github/workflows/checks.yml) runs on pushes and pull requests, with PostgreSQL-backed API tests and a frontend production build. The jobs use `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, and `postgres:17` tags rather than immutable action/image digests. This permits upstream tag/image updates to change the executed toolchain. Pin actions to verified commit SHAs and consider pinning the database image digest for controlled release checks. The docs say remote CI has not yet run, so a successful local check is not evidence of a green hosted workflow.

### P3 — Health endpoint is a database liveness check, not full readiness

[`/api/health`](../../../apps/api/mandate/main.py) executes `SELECT 1` and returns `status: ok` plus `database: postgresql`; this usefully verifies the database connection. It does not report whether the reconciliation poller is running or whether configured provider/model integrations are usable. That is sufficient for the current local run instructions, but an operator should not treat it as proof that payment processing is ready. Deployment health probes should distinguish process/database readiness from provider configuration and worker health without exposing secrets.

## Command results

- `npm.cmd --prefix apps/web audit --json`: exit code 0; 0 vulnerabilities (0 info, low, moderate, high, or critical) across 70 installed dependency entries. Full JSON is retained at ignored [`.local/npm-audit-2026-10-30.json`](../../../.local/npm-audit-2026-10-30.json); no automatic fixes were applied.
- `.venv/Scripts/python.exe -m pip check`: `No broken requirements found.`

The `.env.example` inspection read variable names only. No local `.env` values were inspected or printed. No production files, manifests, or lockfiles were edited.
