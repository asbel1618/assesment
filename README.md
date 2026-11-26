# Natural-language orders API

Ask a question about sales in plain English; a local LLM writes the SQL, a validator checks it, and PostgreSQL runs it as a read-only role.

```
POST /query {"question": "..."}
  -> LLM (llama.cpp, OpenAI-compatible)      generates SQL
  -> validate_sql (sqlglot AST allowlist)    rejects anything but SELECT over 3 objects
  -> app_ro role, read-only tx, 5 s timeout  executes, max 1000 rows
  -> {question, sql, columns, rows, truncated}
```

Contents: [Run with Docker Compose](#run-with-docker-compose) · [Local development](#local-development) · [API](#api) · [Layout](#project-layout) · [Decisions](#decisions) · [Tests](#tests) · [With more time](#with-more-time) · [AI usage](#ai-usage)

## Run with Docker Compose

Prerequisites: Docker with Compose v2.24+, and a GGUF model file (the default is `Qwen3.5-9B-UD-Q4_K_XL.gguf`).

```bash
cp .env.example .env
# fill POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, APP_RO_PASSWORD
# (the *_URL variables are only needed for local development, see below)

docker compose up -d --build        # llm, db, api; waits for healthchecks
docker compose run --rm loader      # generate dirty CSV, clean, load into Postgres

curl -s -X POST localhost:8000/query -H 'content-type: application/json' \
  -d '{"question": "how much did we sell in Spain in March?"}'
```

```json
{"question":"how much did we sell in Spain in March?","sql":"SELECT total_amount FROM v_sales_by_month_country WHERE country = 'Spain' AND month = '2025-03'","columns":["total_amount"],"rows":[["8084.52"]],"truncated":false}
```

The first start takes a while: `llm` loads the model (healthcheck `start_period` is 120 s) and `api` waits for it. The loader is idempotent: running it again reloads the same 917 rows.

### Host-specific `llm` settings

The compose file was written for an Intel-GPU host. Defaults match that host; override them in `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_DIR` | `/home/asbel/models` | Host directory holding the GGUF file |
| `LLM_MODEL_FILE` | `Qwen3.5-9B-UD-Q4_K_XL.gguf` | File name inside `MODEL_DIR` |
| `LLM_IMAGE` | `ghcr.io/ggml-org/llama.cpp:server-intel` | llama.cpp server image |
| `RENDER_GID` / `VIDEO_GID` | `987` / `983` | Host GIDs of `render` / `video` (`getent group render video`) |

No Intel GPU: add the CPU override, which drops the `/dev/dri` mapping and uses the plain server image.

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

The CPU override was only checked by rendering the config (`docker compose config`), not run, since the dev host has the Intel GPU. A 9B model on CPU will be slow; the client timeout may need raising.

## Local development

Run infra in compose, the API on the host. The app reads only `os.environ` (no dotenv loader), so pass the file with `--env-file`. Set the URLs in `.env` with host-style addresses (`127.0.0.1`).

```bash
docker compose up -d db llm
cd coding_assesment
uv sync
uv run --env-file ../.env python -m scripts.generate_orders   # data/orders_raw.csv
uv run --env-file ../.env python -m scripts.load_orders       # clean + load + views
uv run --env-file ../.env fastapi dev main.py                 # http://127.0.0.1:8000/docs
```

Scripts import from `app/`, so they must run as modules (`python -m scripts.x`), never `python scripts/x.py`. Postgres runs `docker/postgres/init/` only on an empty volume; to recreate the `app_ro` role use `docker compose down -v`.

## API

`POST /query` with `{"question": "<1-500 chars>"}`.

`200`: `{question, sql, columns, rows, truncated}`. `NUMERIC` cells are JSON strings (exact money); `truncated` is true when the 1000-row cap cut the result.

Errors share one body, `{code, message, sql}` (`sql` set when the LLM's SQL was the problem):

| Status | `code` | Cause |
|---|---|---|
| 422 | (FastAPI) | Blank or oversized question |
| 400 | `invalid_sql` | LLM output failed validation (the SQL is returned) |
| 400 | `query_failed` | Validator passed but Postgres rejected it (bad column, cast, ...) |
| 502 | `llm_unavailable` / `llm_bad_response` / `llm_error` | LLM unreachable, empty or unusable output |
| 504 | `llm_timeout` | LLM did not answer in time |
| 504 | `query_timeout` | Statement exceeded the 5 s timeout |
| 503 | `db_unavailable` | Database unreachable |

## Project layout

```
docker-compose.yml  docker-compose.cpu.yml  docker/postgres/init/01-readonly-role.sh
coding_assesment/
├── main.py                      thin entrypoint
├── app/
│   ├── api.py                   app factory, router wiring
│   ├── routers/query.py         HTTP only: request/response, error mapping
│   ├── services/query_service.py  question -> LLM -> validate -> execute
│   ├── dependencies.py          lazy providers (importing the app needs no env)
│   ├── llm/{base,prompt,client}.py  LLMClient protocol, prompt, httpx impl
│   ├── validator.py             pure SQL validator
│   ├── cleaning.py              pure clean_orders()
│   ├── db/{connection,repository}.py, schema.sql, views.sql
│   └── schemas.py               Pydantic models
├── scripts/{generate_orders,load_orders}.py
└── tests/
```

Layering: router -> service -> (LLM client, repository). Only the repository touches the database.

## Decisions

**Data.** Orders for 2025 over 8 countries and 4 statuses (`completed`, `pending`, `cancelled`, `refunded`). The generator is seeded (same seed, identical file) and writes 1,080 rows with: ~8% exact duplicates, mixed date formats (ISO, `DD/MM/YYYY`, `Mon DD, YYYY`) plus invalid or misspelled dates (`2025-13-45`, `2O25-03-01`, `n/a`), empty or `N/A` amounts, `$1,200.50`-style amounts, country casing/whitespace variants and invalid statuses.

**Cleaning.** Reject rather than guess: unparseable dates, empty or non-numeric amounts and invalid statuses are dropped, never imputed; `$`/`,` amounts are parsed. Text is trimmed and normalized, duplicates are removed on the normalized row (first kept). Rejected rows go to `data/rejected_orders.csv` with a `reason`. On the generated file: 1,080 read, 917 loaded, 163 rejected (80 duplicate, 38 invalid date, 29 missing amount, 16 invalid status). The loader truncates and reinserts in one transaction, so it is re-runnable and keeps the views.

**"Sales" means `status = 'completed'`.** Cancelled, refunded and pending orders are not revenue. Both views apply it. `v_sales_by_month_country` (`month` as `YYYY-MM`, `country`, `total_amount`, `order_count`) and `v_top_customers` (top 10 by `total_amount`, ties broken by name so the list is deterministic).

**SQL safety in layers**, because LLM output is untrusted:
1. `validate_sql` (sqlglot, postgres dialect) is closed-world: a single `SELECT`/set-operation, tables only from `{orders, v_sales_by_month_country, v_top_customers}` and never schema-qualified (blocks `pg_catalog`, `information_schema`), CTE names resolved per scope, no `INTO`, locks, comments or data-modifying CTEs, and any function sqlglot does not know is rejected.
2. The API connects as `app_ro`: `SELECT` only on those objects, `PUBLIC` privileges revoked (no temp tables), read-only by default.
3. Execution runs in a read-only transaction with `statement_timeout` 5 s and a 1000-row cap.

The `loader` is a separate one-shot service so the owner credentials never reach the long-running `api` container.

**LLM.** Local llama.cpp (Qwen3.5-9B) over its OpenAI-compatible API, called with plain `httpx` behind an `LLMClient` protocol so tests inject a fake. Thinking mode is disabled per request (`chat_template_kwargs.enable_thinking=false`): with it on, `content` came back empty and a call took 82 s versus 10 s. `temperature=0`; the prompt lists only the allowed objects, the dialect, the data range, the sales definition and a few examples.

**Other.** PostgreSQL over SQLite for real roles and privileges; `psycopg` 3 and SQLAlchemy for engine/connection only (raw SQL for views and queries); pandas for the cleaning step.

## Tests

```bash
cd coding_assesment
uv run pytest          # 132 tests, no database, no network, no LLM
uv run ruff check . && uv run ruff format --check .
```

| File | Covers |
|---|---|
| `test_generator.py` | Determinism, row count, every defect type present |
| `test_cleaning.py` | Duplicates, each bad-date class, amounts, casing/whitespace, invalid status, reject reasons |
| `test_validator.py` | Valid queries and adversarial ones (stacking, DML, `INTO`, catalogs, qualified names, dangerous functions, comments, CTE-scope tricks) |
| `test_llm_client.py` | httpx client against a fake transport: parsing, fence/think stripping, error mapping; few-shot SQL passes the validator |
| `test_api.py` | `/query` with fake LLM and repository: happy path and each error class; a hostile LLM output yields 400 and never reaches the repository |

The views and the repository are verified manually against a live Postgres (see the AI log), not in pytest, to keep the suite hermetic.

## With more time

- DB-backed integration tests (e.g. testcontainers) for the views, loader and the `app_ro` privileges.
- An NL-to-SQL evaluation set with expected results to measure accuracy; the manual smoke test partly reuses a few-shot example, so it does not prove generalization.
- Feed validator/Postgres errors back to the LLM for one retry.
- Alembic migrations instead of `schema.sql` applied by the loader.
- CI running ruff and pytest; structured logging and request metrics.
- Authentication and rate limiting on `/query`.
- Async LLM and DB calls; pagination instead of truncation.
- The compose file targets one hardware setup; a CPU override exists but is untested.

## AI usage

Claude Code was used as a pair throughout. Each step started in plan mode (design reviewed and approved by me before any code), validator, cleaning and LLM client were built test-first, and the AI ran the checks (pytest, ruff, live curl against the stack). I owned the decisions: local llama.cpp, sqlglot, PostgreSQL, keeping pandas, how to treat `$1,200.50` amounts, rejecting dirty rows over imputing. The AI never edited the dependency manifest (it printed `uv add` commands). Corrections that mattered:

- A first validator let a CTE defined in one subquery mask a real `pg_user` elsewhere; fixed with per-scope resolution and a regression test.
- `exec_driver_sql` made psycopg read `%` in `LIKE '%a%'` as a placeholder, and the error mapping then hid it as a 503; both fixed after live testing.
- A first `app_ro` privilege check failed for the wrong reason (read-only session default) and had to be redone.
- The plan said to load data via the `api` container; the AI flagged that this would put owner credentials in it and proposed the separate `loader` service.
- The AI's claim about the model's behaviour was checked against the live server: thinking mode and year/`completed` omissions were found by probing, then fixed in the request and prompt.

Per-step log (asked / accepted / corrected):

| Step | Asked | Accepted | Corrected / rejected |
|---|---|---|---|
| planning | Assessment breakdown, layout, step list | Layered layout; validator + read-only role as defense in depth | Local llama.cpp over a hosted API, `sqlglot`, SQLAlchemy, then PostgreSQL instead of SQLite |
| 0 | Root `.gitignore`, `.env.example`, dependency install | Ignore rules and env example; `uv add` run after explicit authorization | Kept `pandas`; rejected ignoring `conversations/`; secrets generated locally without echoing |
| 1 | Seeded dirty-CSV generator + tests | One defect per base row, ~8% duplicates, `random.Random(seed)` only | `$1,200.50` conflicted with reject-invalid policy; decided to parse them |
| 2 | TDD cleaning (`clean_orders`) | Shared `COUNTRIES`/`VALID_STATUSES`; duplicates to rejects; `Decimal` | Generator now runs as a module; result 917 clean, 80 duplicate, 38 invalid_date, 29 missing_amount, 16 invalid_status |
| 3 | DB + loader design, then implementation | `TRUNCATE` + reinsert in one tx; `REVOKE ... FROM PUBLIC`; default privileges | First `app_ro` check invalid (session default, not privilege); redone in AUTOCOMMIT |
| 4 | Views design, then implementation | `CREATE OR REPLACE VIEW`; tie-break in top 10; no pytest for views | Verified March/Spain (8084.52, 9 orders) and top customer against manual queries |
| 5 | TDD validator | Closed-world AST policy instead of a function denylist | Probed sqlglot first (root-type check misses data-modifying CTEs); fixed CTE-scope hole found in self-review |
| 6 | TDD LLM client | Sync httpx client behind a protocol; typed errors; `temperature=0`; schema-only prompt | Probed live model: thinking left `content` empty (82 s); disabled per request (10 s); model needed explicit year and `completed` rule |
| 7 | `/query` design + implementation | Lazy dependency providers; repository protocol; `query_failed` as 400 | `%` placeholder bug and the 503 mis-mapping found by live testing; fixed |
| 8 | Endpoint tests (fakes for LLM and repository) | Override only the two leaf providers so the real service and validator run | Mutation check (504 -> 502 turned a test red); stray fixture removed |
| 9 | Containerization | uv two-stage build, non-root user, explicit `environment`, `/health` healthcheck | Separate `loader` service instead of `run --rm api`; `useradd` UID warning fixed |
| 10 | README and compose parameterization | Root README; env-overridable host values; CPU override file | CPU override only config-checked, not run |
