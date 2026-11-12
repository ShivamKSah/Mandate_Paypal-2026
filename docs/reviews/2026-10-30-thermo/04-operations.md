# Database migrations and local production packaging

Reviewed and implemented October 30, 2026. This worker changed migrations, Python packaging, Docker packaging, production Compose, CI, and the migration launcher. The coordinator owns application startup, configuration validation, the local database backup and adoption, and the final integrated checks. No deployment or publication occurred.

Coordinator integration update, October 31: migration tests now include the stable operator workspace; all tests pass in the 138-test backend suite. The backed-up local prototype was adopted with financial/audit row counts retained. A final clean installed-wheel production-mode boot verified the working-directory static paths, compiled frontend, access gate, browser headers, schema check and readiness. Docker health uses `/api/ready`. Actual container execution and hosted CI remain pending.

## Findings and repairs

The original startup used `Base.metadata.create_all`, which neither versions schema changes nor adds new columns to existing prototype tables. Startup now has a dedicated read-only integration contract, `ensure_schema_current(engine)`. The coordinator calls it before starting the payment worker. Explicit upgrades run through `python -m mandate.migrate`, never through application startup.

The migration history has two revisions. `0001_prototype` uses the frozen definitions in `apps/api/alembic/prototype.py`; it does not import live ORM definitions. `0002_hardening` adds session credentials and expiry, retained provider request payloads, raw webhook bodies and retry scheduling, shared rate-limit buckets, and unique provider order/capture identities. Fresh databases traverse both revisions. Existing unversioned databases must pass an exact baseline check and explicitly request `--adopt-prototype`. Adoption stamps only the baseline and then runs the hardening revision in the same PostgreSQL transaction.

Schema validation checks columns, types, nullability, defaults, foreign keys, indexes, uniqueness, primary keys, accounting checks, and constraint validation status. The CHECK comparison removes redundant PostgreSQL parentheses because these frozen accounting expressions contain only conjunctions. This normalization is specific to these expressions; review it if a later revision introduces Boolean grouping. Unknown or partially modified prototype schemas are rejected instead of silently repaired.

The migration transaction takes a database-and-schema-specific advisory lock before inspecting state. This serializes concurrent migration commands. A failed upgrade rolls back its stamp and all DDL. The revisions disable destructive downgrades. Back up before upgrading; a restore from a verified backup is the recovery path for a failed release. A duplicate legacy provider order or capture ID blocks the new uniqueness constraint without deleting or modifying the conflicting financial records.

Prototype adoption preserves sessions as ownership records and retains grants, proposals, balances, reservations, payments, operation retry IDs, reconciliation leases, cases, webhooks, and audit rows. It revokes old bearer-cookie sessions and expires their access. A migration cannot prove which person owns an old record, so it does not issue replacement access tokens. Existing operations retain their identities and unknown outcomes.

Python runtime and development dependencies now have separate exact locks. The API wheel includes the migration environment, frozen baseline, and revisions under the installed `mandate_migrations` package. A clean installed wheel can locate its migration head without the source checkout. The CLI loads the current working directory's `.env` before importing database configuration, and existing environment variables take precedence. Database driver failures do not print URLs or SQL parameters; known schema-state errors give a safe operator message.

The Dockerfile builds the frontend with `npm ci`, builds locked Python wheels separately, and installs those wheels into a non-root Python runtime. Its only frontend artifact is `/app/apps/web/dist`. The build context uses an allowlist and excludes environment files, local configuration, tests, caches, and virtual environments. Official Node, Python, and PostgreSQL image indexes are pinned by registry-verified digest.

Production Compose gives PostgreSQL a persistent volume, waits for database health, completes a one-shot migration before starting the app, and keeps the app on the loopback interface for an operator-managed HTTPS reverse proxy. The app and migration containers use a read-only root filesystem, a temporary `/tmp`, no Linux capabilities, and no privilege escalation. Secrets come from the operator's ignored environment file. No credentials enter the Docker build.

CI now installs the Python locks, checks dependency consistency, compiles Python, migrates a fresh CI database, runs API tests, builds the API wheel and frontend, and builds an image. The image check verifies its non-root user, bundled migration revision, and frontend entry point. GitHub Actions are pinned to commit SHAs verified against their primary repositories with `git ls-remote`. CI has not run remotely in this session.

## Evidence

All PostgreSQL migration tests create `test_migrations_<random UUID>` schemas and remove only their own schema. They never migrate or clear `public`.

| Command | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest apps/api/tests/test_migrations.py -q --tb=short` | 14 passed. Covers fresh/repeated upgrades, legacy retention, column/index/unique/CHECK drift, unvalidated constraints, transaction rollback, duplicate provider identities, read-only startup refusal, concurrent upgrade serialization, CLI credential redaction, and safe remediation messages. |
| `.venv/Scripts/python.exe -m pip install -r requirements-dev.lock.txt -e './apps/api[test]'` | Passed. |
| `.venv/Scripts/python.exe -m pip check` | No broken requirements. |
| `.venv/Scripts/python.exe -m compileall -q apps/api/mandate/migrate.py apps/api/alembic` | Passed. |
| `.venv/Scripts/python.exe -m pip wheel --no-deps --wheel-dir .local/packaging/wheels ./apps/api` | Built `mandate_api-0.1.0-py3-none-any.whl`. |
| Install runtime lock and wheel into `.local/packaging/venv`, then `pip check` | Passed in a clean Windows Python 3.13 environment. |
| Installed-wheel `python -m mandate.migrate --help` and `ScriptDirectory` head assertion | Passed; discovered `0002_hardening` and its bundled file. |
| Installed-wheel `python -m mandate.migrate` and `ensure_schema_current(engine)` against a unique disposable schema | Passed. The installed wheel executed the actual revision chain and validated the resulting schema; its temporary schema was removed afterwards. |
| `pip download --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --python-version 313 -r requirements.lock.txt` | Linux runtime wheels resolved successfully into `.local/packaging/linux-wheels`. This is dependency resolution, not Linux execution. |
| `docker compose -f compose.production.yaml config -q` with dummy, non-secret environment values | Passed without printing resolved configuration. |
| `docker version` | Client available; Docker Desktop Linux daemon unavailable. Local image build and container boot remain unverified. |

The migration suite emits one existing Starlette warning about its TestClient HTTPX integration. No dependency was added to suppress it.

## Operator commands

Run these from the repository root. The coordinator must back up the existing local PostgreSQL database before adoption. An unversioned database that differs from the frozen prototype needs investigation, not a forced stamp.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.lock.txt -e './apps/api[test]'
./scripts/migrate.ps1 -AdoptPrototype # Existing exact prototype, once, after backup
./scripts/migrate.ps1                 # Blank or already versioned database
```

For an eventual local container rehearsal, create an ignored `.env.production` with `POSTGRES_PASSWORD`, an appropriately encoded `DATABASE_URL` using host `db` and port `5432`, an HTTPS `PUBLIC_BASE_URL`, and a random `APP_ACCESS_KEY` with at least 32 characters. Add optional sandbox provider credentials through that environment file. `COOKIE_SECURE` is forced true and `APP_ENV` is forced production by Compose. Use `MANDATE_ENV_FILE` if selecting a different environment file, and pass that same file to Compose's `--env-file` option.

```powershell
docker compose --env-file .env.production -f compose.production.yaml build
docker compose --env-file .env.production -f compose.production.yaml up -d
```

These commands are documented for a later operator rehearsal; this worker did not run them or configure hosting. Production Compose uses its own named volume and does not attach the existing native development cluster or development Compose volume. For an imported exact prototype inside that production volume, explicitly run `docker compose --env-file .env.production -f compose.production.yaml run --rm migrate python -m mandate.migrate --adopt-prototype` before starting the app. Never use `down -v` for a retained database.

## Review result and limits

The migration boundary is one focused module with no branching inserted into business operations. Frozen revision definitions, one transaction, and one schema validator replace implicit startup repair. No new file approaches 1,000 lines. The remaining required integration work is the coordinator's startup call, backed-up public adoption, and full suite. Image build, real container boot, HTTPS reverse proxy setup, and remote CI remain unverified. Dependency locks pin versions rather than distribution hashes; image indexes and action code are digest/SHA pinned.

Sources checked for the implementation include the [Alembic shared-connection cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands), the primary repositories for [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), and [setup-node](https://github.com/actions/setup-node), and Docker's official registry manifest responses for `library/node`, `library/python`, and `library/postgres`.
