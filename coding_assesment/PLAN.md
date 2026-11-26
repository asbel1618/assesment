# PLAN

Working plan for the take-home assessment. Status: **planned, nothing applied**.
Update the checkboxes as steps land.

## 0. Agent handoff (read first)

**What this is:** a take-home assessment graded on engineering judgment, not feature volume: safe SQL validation, tests, readable structure, commit history, honest AI-usage log. Spec summary is in §1; the full rules are in `../CLAUDE.md` (and the user's global rules). Read both before acting.

**Current state:** only a FastAPI stub exists (`coding_assesment/main.py`: `GET /`, `GET /health`). `pyproject.toml` has `dependencies = []`. The git repo (root `test/`) has **no commits**. `docker-compose.yml` already has `llm` and `db` services. Nothing else is built.

**How to work:**
1. Do **one step at a time** (§4), in order. Each step lists *Why* (the reason it exists) and *Done when* (verifiable exit criteria). Run the check, then tick the box and report.
2. Hard rules: never edit `pyproject.toml` dependencies (print the `uv add` command, let the user run it); commit only when the user asks (one commit per step, message given in the step); never commit secrets/`.env`; lint changed files after each step; stop and report on any non-zero exit; same command failing twice → stop and propose a different approach.
3. TDD for steps 2 and 5 (tests before implementation).
4. Keep a running note of AI interactions (asked / accepted / corrected) for the README; append to §8 as you go.
5. Commands run from `coding_assesment/`; compose commands run from the repo root `test/`.
6. Scripts import from `app/`, so run them as modules from `coding_assesment/`: `uv run python -m scripts.generate_orders` (never `python scripts/generate_orders.py`, which fails with `ModuleNotFoundError: app`). Same for `scripts.load_orders`; in compose: `docker compose run --rm loader` (generates + loads in-container).

**Data contract (decided defaults; change only with user approval):**

| Item | Value | Why |
|---|---|---|
| Date range | 2025-01-01 … 2025-12-31 | Single year keeps "March" unambiguous for NL questions |
| Countries | ~8 (e.g. Spain, France, Germany, Italy, Portugal, UK, USA, Mexico), canonical English names | Enables "in Spain" style questions |
| Statuses | `completed`, `pending`, `cancelled`, `refunded` | Gives the views a meaningful filter |
| `orders` table | `id BIGSERIAL PK`, `order_date DATE NOT NULL`, `customer TEXT NOT NULL`, `country TEXT NOT NULL`, `product TEXT NOT NULL`, `amount NUMERIC(12,2) NOT NULL CHECK (amount >= 0)`, `status TEXT NOT NULL CHECK (status IN (...))` | Constraints make the cleaning contract explicit |
| "Sales" definition | `status = 'completed'` only | Cancelled/refunded/pending are not revenue; state this in README |
| `v_sales_by_month_country` | `month` (`YYYY-MM`), `country`, `total_amount`, `order_count` | Directly answers "how much did we sell in X in month Y" |
| `v_top_customers` | `customer`, `total_amount`, `order_count`; top 10 by `total_amount` desc | Spec: top 10 customers by purchases |
| Injected defects | ≥1,000 total rows incl. ~5–10% exact duplicates; dates in mixed formats (ISO, `DD/MM/YYYY`, `Mon DD, YYYY`) plus invalid/misspelled (`2025-13-45`, `2025/02/30`, `2O25-03-01`, `n/a`); empty/`N/A`/`$1,200.50`-style amounts; country casing/whitespace variants; invalid status | Matches spec; each defect type must be counted by the tests |
| Cleaning policy | trim/normalize text; dedupe on normalized row (keep first); unparseable date → reject; empty/invalid amount → reject (no imputation); invalid status → reject. Rejected rows written to `data/rejected_orders.csv` with a `reason` column | Rejecting beats guessing; the rejects file is reviewable evidence |

**Environment variables (root `.env`, mirrored in `.env.example` without values):**

| Var | Used by | Notes |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `db` | password mandatory |
| `APP_RO_PASSWORD` | init script, API | password of the read-only role `app_ro` |
| `DATABASE_URL` | loader | owner role. Host: `postgresql+psycopg://…@127.0.0.1:5432/…`; container: host `db` |
| `READONLY_DATABASE_URL` | API | `app_ro` role, same host rule |
| `LLM_BASE_URL` | API | host `http://127.0.0.1:8080/v1`; container `http://llm:8080/v1` |

## 1. Requirements

| # | Requirement | Acceptance signal |
|---|---|---|
| 1 | Generate CSV, ≥1,000 rows (`date, customer, country, product, amount, status`) with duplicates, misspelled/invalid dates, empty amounts | Seeded/deterministic; defects measurable |
| 2 | Clean CSV and load into PostgreSQL | Idempotent; cleaning function importable |
| 3 | Two SQL views: sales by month+country; top 10 customers by purchases | Defined in SQL, queryable |
| 4 | FastAPI endpoint: NL question → LLM → SQL → **validate** → execute → result | Read-only, allowlist-only; LLM failure/invalid output → clear error |
| 5 | pytest ≥3: cleaning, validation, endpoint with mocked LLM | No network in tests |
| 6 | README: run, decisions, with-more-time, AI usage (asked / accepted / corrected) | Candid AI log |
| 7 | No API key committed; incremental commits | `.env` gitignored; history shows thinking |

Hidden criteria: validator holds regardless of LLM output; commit history readability; honest AI log (keep notes as we go).

## 2. Decisions (settled)

| Topic | Decision |
|---|---|
| DB | PostgreSQL (`postgres:17-alpine`, compose service `db`, named volume `pgdata`, healthcheck via `pg_isready`). Host: `127.0.0.1:5432`; in-compose: `db:5432`. Credentials only via `.env` (gitignored); compose fails fast if `POSTGRES_PASSWORD` is unset. |
| DB driver | `psycopg` 3 (`psycopg[binary]`); SQLAlchemy URL `postgresql+psycopg://…`. |
| DB roles | Owner role (`POSTGRES_USER`) for loader/DDL. Separate `app_ro` role for the API: `SELECT` only on `orders` + the 2 views (via `ALTER DEFAULT PRIVILEGES`/explicit grants), `default_transaction_read_only=on`, `statement_timeout`. Created by an init script mounted in `docker-entrypoint-initdb.d`. |
| LLM provider | `llm` service in `../docker-compose.yml`: llama.cpp server, model `Qwen3.5-9B-UD-Q4_K_XL.gguf`, OpenAI-compatible API. Host: `http://127.0.0.1:8080/v1`; in-compose: `http://llm:8080/v1`. No API key needed, base URL via env (`LLM_BASE_URL`). |
| LLM client | Plain `httpx` call to `POST /v1/chat/completions` (no `openai` SDK; `httpx` already ships with `fastapi[standard]`). Hidden behind an `LLMClient` protocol. |
| SQL validation | `sqlglot` AST (dialect `postgres`): single statement, `SELECT` only, tables ⊆ allowlist, unqualified names only (no `pg_catalog`/`information_schema`/schema-qualified refs), no `INTO`/locking clauses. Defense in depth: `app_ro` role. |
| DB access | SQLAlchemy for engine/connection only; raw SQL for views and queries. Query execution uses the `app_ro` connection inside a read-only transaction. |

Risks to verify early (do not assume):
- Qwen3.5 may emit reasoning/thinking output; confirm response shape from `llama-server` and how to disable or strip it (e.g. `chat_template_kwargs`, `/no_think`, or strip `<think>…</think>`).
- Local 9B model SQL quality: keep prompt tight (schema only, PostgreSQL dialect, few-shot examples, `temperature=0`), strip code fences.
- Timeout/latency: set explicit client timeout; map to a 504/502 error.
- Postgres specifics: `amount` as `NUMERIC(12,2)`, `order_date` as `DATE`; month grouping via `to_char(order_date,'YYYY-MM')`; confirm `app_ro` cannot read other schemas/catalog data beyond defaults (`pg_catalog` is readable by default, hence validator blocks it).

## 3. Target layout

Git root is `test/` (repo moved up). The Python project stays in `coding_assesment/`; every `uv`/`pytest`/`ruff` command runs from there. Root-level `CLAUDE.md` command examples are relative to `coding_assesment/`.

```
test/                             # git root
├── CLAUDE.md  docker-compose.yml # services: llm, db (postgres), api (step 9)
├── docker/postgres/init/01-readonly-role.sh  # creates app_ro role
├── .gitignore                    # root: .env, data/, plus Python ignores
└── coding_assesment/             # Python project (uv)
    ├── README.md  PLAN.md  Dockerfile  .dockerignore  .env.example  pyproject.toml
    ├── main.py                   # thin entrypoint -> app factory
    ├── app/
    │   ├── routers/query.py          # POST /query, error mapping (HTTP only)
    │   ├── services/query_service.py # question -> LLM -> validate -> execute
    │   ├── llm/{base.py,client.py}   # LLMClient protocol + llama.cpp httpx impl
    │   ├── validator.py              # pure: SELECT-only, single stmt, allowlist
    │   ├── db/{connection.py,views.sql,repository.py}  # engines: owner + read-only
    │   └── schemas.py                # Pydantic request/response/error
    ├── scripts/{generate_orders.py,load_orders.py}
    ├── data/                         # raw CSV (generated, gitignored)
    └── tests/{test_cleaning.py,test_validator.py,test_api.py}
```

API contract:
- `POST /query {"question": str}` → `200 {question, sql, columns, rows}`
- `422` invalid request · `400` LLM output failed validation or was rejected by Postgres (`invalid_sql` / `query_failed`, include reason + `sql`) · `502/504` LLM unreachable/bad response/timeout · `504` query timeout · `503` database unreachable.
- `200` also carries `truncated: bool`; `Decimal` cells serialize as JSON strings.
- Row limit (1000) + statement timeout (5s) on execution.

## 4. Steps (one or two focused commits each)

- [x] **0. Init** — root `.gitignore` (`.env`, `data/`, `.venv`, `__pycache__/`; supersedes the inner one, which is removed or kept as-is), root `.env.example` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `APP_RO_PASSWORD`, `LLM_BASE_URL`, `DATABASE_URL`, `READONLY_DATABASE_URL`). Compose `db` service is already added. User runs deps (see §5). First commit also tracks `CLAUDE.md` and `docker-compose.yml`.
  `chore: gitignore, env example, deps`
  *Why:* nothing may leak (secrets) and dependencies must exist before code. *Done when:* `git status` shows `.env` ignored; `.env.example` lists every var in §0; user confirmed `uv add` ran; `uv run python -c "import fastapi, sqlalchemy, psycopg, sqlglot"` succeeds.
- [x] **1. Generator** — `scripts/generate_orders.py`, seeded, ~1,100 rows. Inject: exact duplicates, multiple date formats + typos/invalid dates, empty/garbage amounts; also country casing, whitespace, invalid status.
  `feat: dirty orders CSV generator`
  *Why:* reproducible dirty input so the cleaning tests and README numbers are stable. *Done when:* same seed ⇒ identical file; ≥1,000 rows; a quick script/test counts each defect type > 0; output goes to `data/orders_raw.csv` (gitignored).
- [x] **2. Cleaning (TDD)** — pure `clean_orders()`: dedupe, parse dates (drop/flag unparseable), coerce amounts, normalize text/status. `tests/test_cleaning.py` first.
  `feat: cleaning logic + tests`
  *Why:* pure logic is the most testable part and the spec requires a cleaning test. *Done when:* `test_cleaning.py` covers duplicates, each bad-date class, empty/garbage amounts, casing/whitespace, invalid status; `clean_orders` returns `(clean_df, rejects_df)` with reasons; no I/O or DB inside it.
- [x] **3. DB + loader** — `docker/postgres/init/01-readonly-role.sh` (creates `app_ro`, default privileges, read-only/timeout settings) mounted into `db` in compose. `scripts/load_orders.py`: read → clean → Postgres in one transaction (drop/recreate or `TRUNCATE` + insert; idempotent); log dropped counts per defect type.
  `feat: postgres service, read-only role, loader`
  *Why:* the API must run with least privilege even if the validator is bypassed; loader must be re-runnable. Notes: Postgres only runs `docker-entrypoint-initdb.d` on an **empty** volume (re-run with `docker compose down -v`); use `ALTER DEFAULT PRIVILEGES FOR ROLE <owner> … GRANT SELECT … TO app_ro` so later-created tables/views are covered. *Done when:* `docker compose up -d db` healthy; running the loader twice yields the same row count; `app_ro` can `SELECT` from `orders` but `INSERT`/`DROP` fail; loader prints counts (read, duplicates, rejected by reason, loaded).
- [x] **4. Views** — `views.sql`: `v_sales_by_month_country` (`to_char(order_date,'YYYY-MM')`), `v_top_customers` (`LIMIT 10`); applied by loader; grant `SELECT` to `app_ro`.
  `feat: sales and top-customer views`
  *Why:* spec deliverable and the only objects (with `orders`) the LLM may query. *Done when:* both views return expected rows on the loaded data (spot-check one month/country sum against a manual query); `app_ro` can select from them; sales definition (`completed` only) is commented in `views.sql`.
- [x] **5. Validator (TDD)** — `validator.py` with `sqlglot`. Reject non-SELECT, multiple statements, tables outside `{orders, v_sales_by_month_country, v_top_customers}`, CTE/subquery smuggling, `pg_catalog`/`information_schema`, schema-qualified names, `INTO`, `FOR UPDATE`, dangerous functions (`pg_read_file`, `set_config`, `pg_sleep`, …), comments. Adversarial cases in `tests/test_validator.py`.
  `feat: SQL validator + tests`
  *Why:* the central safety control; LLM output is untrusted. *Done when:* pure function `validate_sql(sql) -> str` (returns normalized SQL or raises `InvalidSQLError(reason)`); tests include valid cases (plain select, aggregation, join between allowed objects, CTE over allowed tables) and attacks (`DROP`, `;` stacking, `UPDATE`, `SELECT … INTO`, `pg_catalog`/`information_schema`, `public.orders` qualified, `pg_sleep`, comments, empty string, non-SQL prose).
- [x] **6. LLM client** — `LLMClient` protocol + httpx impl against llama.cpp; prompt with allowed schema only; strip fences/thinking; typed errors (unreachable, timeout, empty).
  `feat: LLM client behind interface`
  *Why:* tests and the service depend on an interface, not on llama.cpp. *Done when:* `LLMClient.generate_sql(question) -> str` with a typed `LLMError` hierarchy (unreachable, timeout, bad/empty response); prompt contains only the allowed schema, dialect, output rules, 2–3 few-shot examples; reasoning/fences stripped; one manual smoke call against the running `llm` service documented (not part of pytest).
- [x] **7. Endpoint** — `app_ro` engine + `SET TRANSACTION READ ONLY`, row limit, `statement_timeout`, `query_service`, `/query` router, error mapping; `main.py` stays thin.
  `feat: /query endpoint`
  *Why:* ties the pieces together with correct error semantics. *Done when:* `uv run fastapi dev main.py` + `docker compose up -d db llm` + loaded data ⇒ `curl -X POST localhost:8000/query -d '{"question":"how much did we sell in Spain in March?"}'` returns rows; each error class in the API contract is reachable; layering respected (router → service → repository/LLM client; only repository touches the DB).
- [x] **8. Endpoint test** — `dependency_overrides` for fake LLM and fake repository (no Postgres or network needed): happy path, invalid SQL from LLM, LLM exception, empty question.
  `test: endpoint with mocked LLM`
  *Why:* spec requires an endpoint test with the LLM mocked; it must be hermetic. *Done when:* `uv run pytest` passes with Postgres and the LLM stopped; asserts status codes and error bodies, not just the happy path.
- [x] **9. Containerize** — `coding_assesment/Dockerfile` (uv, Python 3.14), `.dockerignore`; add `api` service to `docker-compose.yml`: `build: ./coding_assesment`, `depends_on` both `llm` and `db` with `condition: service_healthy`, `networks: [backend]`, `LLM_BASE_URL=http://llm:8080/v1`, `DATABASE_URL`/`READONLY_DATABASE_URL` pointing at `db:5432`, port `127.0.0.1:8000:8000`. Data scripts run via the profile-gated one-shot `loader` service (`docker compose run --rm loader`; owner credentials stay out of `api`), or locally against `127.0.0.1:5432`. Data is loaded by the loader into the `pgdata` volume, not baked into any image.
  `feat: run API as compose service`
  *Why:* user decision: the API runs inside compose with `llm` and `db`. *Done when:* `docker compose up --build` from a clean volume brings up all services healthy; loader runs through `docker compose run --rm loader`; the endpoint answers from the host on `127.0.0.1:8000`.
- [ ] **10. Docs + lint** — README (run via `docker compose up`, local dev alternative, decisions, with-more-time, AI log); `ruff check` + `ruff format`.
  `docs: README`
  *Why:* graded deliverable. *Done when:* a fresh clone can follow it end to end; sections: run (compose + local), decisions (§2 + §0 data contract), what I'd do with more time, AI usage from §8, note that compose is host-specific (model path, GPU, GIDs); `uv run ruff check . && uv run ruff format --check .` clean; `uv run pytest` green.

## 5. Dependency commands (user runs; do not edit `pyproject.toml`)

```
uv add "fastapi[standard]" sqlalchemy "psycopg[binary]" sqlglot pandas
uv add --dev pytest ruff
```

`pandas` is optional: drop it and clean with stdlib `csv` + `datetime` if keeping deps minimal is preferred (decide at step 2).

## 6. Conventions

- Commit only when the user asks; incremental, meaningful messages.
- Lint changed files after each step (`uv run ruff check . && uv run ruff format .`).
- No `any`-style type escapes; no swallowed exceptions; typed errors mapped in the router.
- Never commit secrets; `.env` ignored.
- Record AI interactions (asked / accepted / corrected) in a running log for the README.

## 7. Open points

- Resolved: DB is PostgreSQL (compose `db` service added). API runs as a compose service (step 9). Git root is `test/`; project in `coding_assesment/`.
- Compose hardcodes host-specific values (`/home/asbel/models`, GIDs 987/983, Intel GPU image). Reviewers cannot run it as-is: document in README, consider parameterizing via env vars.
- Compose now requires a root `.env` (`POSTGRES_PASSWORD` mandatory); document in README.
- Repo has no commits yet; step 0 is the first commit.
- Option: flatten `coding_assesment/` into the root (matches `CLAUDE.md` commands exactly). Not done; say so if wanted.

## 8. AI usage log (append as work proceeds)

| Step | Asked | Accepted | Corrected / rejected |
|---|---|---|---|
| planning | Assessment breakdown, target layout, step list | Layered layout, validator + read-only role as defense in depth | User chose local llama.cpp over a hosted API, `sqlglot`, SQLAlchemy, then PostgreSQL instead of SQLite; plan updated accordingly |
| 0 | Init scaffolding: root `.gitignore`, `.env.example`, dependency install, `.env` variables | Ignore rules and env example as proposed; AI ran `uv add` after explicit user authorization | User kept `pandas` (to showcase real data work, over stdlib `csv`); rejected ignoring `conversations/` (transcripts are for the reviewer); AI generated `APP_RO_PASSWORD` and built DB URLs locally without echoing secrets |
| 1 | Seeded dirty-CSV generator (stdlib only) + determinism/defect-coverage tests | Plan as proposed: one defect per base row, ~8% exact dupes, `random.Random(seed)` only | `$1,200.50` amounts: AI flagged the conflict with the reject-invalid policy; user decided to parse them (step 2 must strip `$`/`,`); only empty/`N/A`/non-numeric are rejected |
| 2 | TDD cleaning: `app/cleaning.py` (`clean_orders`), tests first (red: `ModuleNotFoundError`), then green | `COUNTRIES`/`VALID_STATUSES` owned by `app/cleaning.py` and imported by the generator; duplicates go to rejects as `duplicate`; multi-reason rejects `;`-joined; `Decimal` amounts | Importing `app` from the generator means it must now run as `uv run python -m scripts.generate_orders` (direct `python -m scripts.<name>` fails); output verified byte-identical. Real CSV: 1080 rows -> 917 clean, 80 duplicate, 38 invalid_date, 29 missing_amount, 16 invalid_status |
| 3 | Plan-mode design of DB + loader, then implementation: `app_ro` init script, `app/db`, `scripts/load_orders.py`, compose mount | `TRUNCATE` + reinsert in one transaction (not `DROP`, so step-4 views survive); `REVOKE ... FROM PUBLIC` to block temp tables; default privileges for later tables/views | AI's first `app_ro` check was invalid: `SET default_transaction_read_only = off` inside an already-open transaction doesn't take effect, so the INSERT failed for the wrong reason; re-ran in AUTOCOMMIT and got the real `permission denied` (privilege layer works). User approved wiping `test_pgdata` (init scripts only run on an empty volume); AI recreated only `db`, leaving `llm` running. Verified: loader run twice -> 917 loaded, 163 rejected (80 duplicate, 38 invalid_date, 29 missing_amount, 16 invalid_status) |
| 4 | Plan-mode design of the views, then implementation: `app/db/views.sql`, loader runs it after `schema.sql` in the same transaction | `CREATE OR REPLACE VIEW` (idempotent); no explicit `GRANT` since `ALTER DEFAULT PRIVILEGES ... ON TABLES` already covers views; `ORDER BY total_amount DESC, customer` tie-break so the top 10 is deterministic; no pytest for the views (a DB-backed test would break the hermetic-pytest goal of step 8), verified manually | Verified: March/Spain view row (8084.52, 9 orders) equals a manual query on `orders`; top customer matches a manual `GROUP BY`; `app_ro` selects from both views. The `app_ro` CREATE VIEW check failed on `ReadOnlySqlTransaction`, so it proves the session default, not the missing privilege (privilege layer was already checked in step 3) |
| 5 | Plan-mode design of the validator, then TDD: `tests/test_validator.py` first (red: `ModuleNotFoundError`), then `app/validator.py` (green, 53 cases) | Closed-world `sqlglot` AST policy instead of a function denylist: parse as `postgres`, single `Select`/`SetOperation` root, whole-tree walk (data-modifying CTEs, `INTO`, locks, comments), unqualified allowlisted tables only, any function sqlglot leaves as `exp.Anonymous` is rejected (`ALLOWED_EXTRA_FUNCTIONS` starts empty); identifiers normalized to lowercase | AI probed sqlglot 30.35 before designing, which showed a root-type check alone misses `WITH x AS (DELETE ...) SELECT`. Self-review found a hole in the first implementation: a global set of CTE names let a CTE defined in one subquery mask a real `pg_user` used elsewhere; fixed with `traverse_scope`/`cte_sources` (per-scope resolution) plus a regression test |
| 6 | Plan-mode design of the LLM client, then TDD: `tests/test_llm_client.py` first (red: `ModuleNotFoundError: app.llm`), then `app/llm/{base,prompt,client}.py` (green, 119 tests total) | Sync `httpx.Client` behind an `LLMClient` protocol; typed `LLMError` hierarchy (unavailable / timeout / response) with a safe `reason`; `temperature=0`; prompt lists only the 3 allowed objects, the 2025 data range, the `completed` sales definition, and reuses `COUNTRIES`/`VALID_STATUSES` from `app/cleaning.py`; a test checks the few-shot SQL passes `validate_sql` | AI probed the live `llm` before designing: with default thinking, `content` is empty (answer in `reasoning_content`), truncated at `max_tokens`, 82 s; `chat_template_kwargs: {"enable_thinking": false}` gave bare SQL in 10 s, so thinking is disabled in the request (the `<think>` strip is only a fallback). Without context the model used year 2023 and omitted `status='completed'`, hence the explicit facts in the prompt. Smoke (manual, not pytest): 3 questions answered in 5-17 s and all pass `validate_sql`; the Spain/March answer matches a few-shot example verbatim, so it does not prove generalization |
| 7 | Plan-mode design of `/query`, then implementation: `app/{schemas,dependencies,api}.py`, `app/db/repository.py`, `app/services/query_service.py`, `app/routers/query.py`, thin `main.py` | Sync route + lazy `lru_cache` dependency providers (importing the app needs no env/network, for step 8); `QueryRepository` protocol mirroring `LLMClient`; execution failures become typed errors, with Postgres rejecting valid-looking SQL mapped to 400 `query_failed` (user decision, same class as validator rejects); explicit `SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout` on top of the role defaults | Live testing disproved two assumptions in the AI's own plan: `exec_driver_sql` with no params still lets psycopg read `%` as a placeholder (`LIKE '%a%'` failed), fixed by escaping `%` to `%%`; and any error without a SQLSTATE was mapped to `db_unavailable`, which hid that bug as a 503, so it is now only for `OperationalError`/`InterfaceError`. Verified manually: Spain/March 200 (8084.52), a non-few-shot question 200, `LIKE` 200, blank question 422, model refusing an injection prompt 400 `invalid_sql`, bad `LLM_BASE_URL` 502, bad `READONLY_DATABASE_URL` 503. 504 paths and `query_failed` are left to step 8 (fakes). Two `pkill`/`pgrep -f` attempts killed the AI's own shell (pattern matched its own command line) |
| 8 | Plan-mode design of the endpoint tests, then `tests/test_api.py` (13 cases, 132 total) | Override only the two leaf providers (`get_llm_client`, `get_query_repository`) so the real service and validator run; asserts a hostile LLM output yields 400 with the repository never called; full `ErrorResponse` body checked for every error class incl. the 504 and `query_failed` paths left from step 7; autouse fixture deletes `LLM_BASE_URL`/`READONLY_DATABASE_URL` so a lost override fails loudly | AI's first draft left a stray unused fixture and an untyped helper, removed before running. Mutation check: changing `llm_timeout` 504 -> 502 turned the matching test red, then reverted. Not done: stopping `db`/`llm` to prove hermeticity (left the running stack alone); the env-var guard covers it |
| 9 | Plan-mode design of the containerization, then implementation: `coding_assesment/Dockerfile` (uv two-stage sync, `python:3.14-slim`, uv pinned to local 0.9.16, non-root uid 10001), `.dockerignore`, `api` + `loader` services in `docker-compose.yml` | uv's documented `--no-install-project` layer pattern (checked against current uv docs); explicit `environment` instead of `env_file` so host-style `127.0.0.1` URLs never reach containers; `/health` reused for the healthcheck | AI deviated from this plan's wording: loading via `run --rm api` would put the owner `DATABASE_URL` in the long-running API container, defeating the `app_ro` least-privilege design, so a profile-gated one-shot `loader` service was added instead (user approved the plan). Data is generated in-container (user choice over a bind mount). Fixed a `useradd` UID warning (`--system` with uid 10001) after the first build. Verified after wiping `test_pgdata` (user-approved): `up -d --build` -> llm/db/api healthy; loader run twice -> read 1080, rejected 163, loaded 917 both times; host `curl` Spain/March -> 200, 8084.52; `printenv DATABASE_URL` empty in `api`; runs as uid 10001; pytest 132 passed |
