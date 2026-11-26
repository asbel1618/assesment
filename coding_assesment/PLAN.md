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
6. Scripts import from `app/`, so run them as modules from `coding_assesment/`: `uv run python -m scripts.generate_orders` (never `python scripts/generate_orders.py`, which fails with `ModuleNotFoundError: app`). Same for `scripts.load_orders`; in compose: `docker compose run --rm api python -m scripts.load_orders`.

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
- `422` invalid request · `400` LLM output failed validation (include reason) · `502/504` LLM unreachable/timeout/bad response.
- Row limit + statement timeout on execution.

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
- [ ] **3. DB + loader** — `docker/postgres/init/01-readonly-role.sh` (creates `app_ro`, default privileges, read-only/timeout settings) mounted into `db` in compose. `scripts/load_orders.py`: read → clean → Postgres in one transaction (drop/recreate or `TRUNCATE` + insert; idempotent); log dropped counts per defect type.
  `feat: postgres service, read-only role, loader`
  *Why:* the API must run with least privilege even if the validator is bypassed; loader must be re-runnable. Notes: Postgres only runs `docker-entrypoint-initdb.d` on an **empty** volume (re-run with `docker compose down -v`); use `ALTER DEFAULT PRIVILEGES FOR ROLE <owner> … GRANT SELECT … TO app_ro` so later-created tables/views are covered. *Done when:* `docker compose up -d db` healthy; running the loader twice yields the same row count; `app_ro` can `SELECT` from `orders` but `INSERT`/`DROP` fail; loader prints counts (read, duplicates, rejected by reason, loaded).
- [ ] **4. Views** — `views.sql`: `v_sales_by_month_country` (`to_char(order_date,'YYYY-MM')`), `v_top_customers` (`LIMIT 10`); applied by loader; grant `SELECT` to `app_ro`.
  `feat: sales and top-customer views`
  *Why:* spec deliverable and the only objects (with `orders`) the LLM may query. *Done when:* both views return expected rows on the loaded data (spot-check one month/country sum against a manual query); `app_ro` can select from them; sales definition (`completed` only) is commented in `views.sql`.
- [ ] **5. Validator (TDD)** — `validator.py` with `sqlglot`. Reject non-SELECT, multiple statements, tables outside `{orders, v_sales_by_month_country, v_top_customers}`, CTE/subquery smuggling, `pg_catalog`/`information_schema`, schema-qualified names, `INTO`, `FOR UPDATE`, dangerous functions (`pg_read_file`, `set_config`, `pg_sleep`, …), comments. Adversarial cases in `tests/test_validator.py`.
  `feat: SQL validator + tests`
  *Why:* the central safety control; LLM output is untrusted. *Done when:* pure function `validate_sql(sql) -> str` (returns normalized SQL or raises `InvalidSQLError(reason)`); tests include valid cases (plain select, aggregation, join between allowed objects, CTE over allowed tables) and attacks (`DROP`, `;` stacking, `UPDATE`, `SELECT … INTO`, `pg_catalog`/`information_schema`, `public.orders` qualified, `pg_sleep`, comments, empty string, non-SQL prose).
- [ ] **6. LLM client** — `LLMClient` protocol + httpx impl against llama.cpp; prompt with allowed schema only; strip fences/thinking; typed errors (unreachable, timeout, empty).
  `feat: LLM client behind interface`
  *Why:* tests and the service depend on an interface, not on llama.cpp. *Done when:* `LLMClient.generate_sql(question) -> str` with a typed `LLMError` hierarchy (unreachable, timeout, bad/empty response); prompt contains only the allowed schema, dialect, output rules, 2–3 few-shot examples; reasoning/fences stripped; one manual smoke call against the running `llm` service documented (not part of pytest).
- [ ] **7. Endpoint** — `app_ro` engine + `SET TRANSACTION READ ONLY`, row limit, `statement_timeout`, `query_service`, `/query` router, error mapping; `main.py` stays thin.
  `feat: /query endpoint`
  *Why:* ties the pieces together with correct error semantics. *Done when:* `uv run fastapi dev main.py` + `docker compose up -d db llm` + loaded data ⇒ `curl -X POST localhost:8000/query -d '{"question":"how much did we sell in Spain in March?"}'` returns rows; each error class in the API contract is reachable; layering respected (router → service → repository/LLM client; only repository touches the DB).
- [ ] **8. Endpoint test** — `dependency_overrides` for fake LLM and fake repository (no Postgres or network needed): happy path, invalid SQL from LLM, LLM exception, empty question.
  `test: endpoint with mocked LLM`
  *Why:* spec requires an endpoint test with the LLM mocked; it must be hermetic. *Done when:* `uv run pytest` passes with Postgres and the LLM stopped; asserts status codes and error bodies, not just the happy path.
- [ ] **9. Containerize** — `coding_assesment/Dockerfile` (uv, Python 3.14), `.dockerignore`; add `api` service to `docker-compose.yml`: `build: ./coding_assesment`, `depends_on` both `llm` and `db` with `condition: service_healthy`, `networks: [backend]`, `LLM_BASE_URL=http://llm:8080/v1`, `DATABASE_URL`/`READONLY_DATABASE_URL` pointing at `db:5432`, port `127.0.0.1:8000:8000`. Data scripts run via `docker compose run --rm api python -m scripts.<name>` (or locally against `127.0.0.1:5432`). Data is loaded by the loader into the `pgdata` volume, not baked into any image.
  `feat: run API as compose service`
  *Why:* user decision: the API runs inside compose with `llm` and `db`. *Done when:* `docker compose up --build` from a clean volume brings up all services healthy; loader runs through `docker compose run --rm api …`; the endpoint answers from the host on `127.0.0.1:8000`.
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
