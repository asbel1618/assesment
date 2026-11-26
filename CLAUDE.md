# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## HARD UNBREACKABLE Constraints
1- Never read the files inside @conversations/ and @orders_sample_file.csv.

## What this is

A take-home coding assessment. Git root is this directory; the Python project lives in `coding_assesment/` (run all `uv`/`pytest`/`ruff` commands from there). It currently holds only a FastAPI stub (`main.py`: `GET /`, `GET /health`); everything below under "Required deliverables" is to be built. Python 3.14 (`.python-version`), managed with `uv`.

### Required deliverables (the assessment spec)

1. **Data loading**: script generating a CSV of ≥1,000 orders (`date, customer, country, product, amount, status`) with deliberate defects: duplicates, misspelled/invalid dates, empty amounts. A second script cleans it and loads it into the database (PostgreSQL chosen, compose service `db`).
2. **Models**: two SQL views — sales by month and country; top 10 customers by purchases.
3. **API (FastAPI, required)**: an endpoint accepting a natural-language question (e.g. "how much did we sell in Spain in March?"), using an LLM to produce SQL, **validating it before execution** (read-only, allowed tables/views only), and returning the result. LLM failure or invalid output must return a clear error response.
4. **Tests (pytest, ≥3)**: cleaning, query validation, and the endpoint with the LLM mocked.
5. **README**: how to run, decisions made, what would be done with more time, and how AI was used (what was asked, accepted, corrected).

### Constraints

- LLM provider is the local `llm` compose service (llama.cpp, OpenAI-compatible at `http://llm:8080/v1`, or `http://127.0.0.1:8080/v1` from the host); config via env. **Never commit secrets** (DB passwords etc. come from env; keep `.env` gitignored — it is not in `.gitignore` yet).
- Commit incrementally with meaningful messages; a single large commit fails the assessment. Reviewers read commit history as evidence of thinking. Commit only when the user asks.
- Optimize for evaluator readability: clear structure, runnable instructions, small focused changes.
- Keep dependencies minimal. Do not edit `pyproject.toml` dependencies; propose the exact `uv add ...` command and wait for the user to run it. `fastapi` is imported by `main.py` but is **not declared** in `pyproject.toml` (`dependencies = []`), so it currently needs adding by the user.

## Commands

Tooling is `uv` + `pytest` + `ruff` (none declared yet; same rule applies — propose, don't edit).

```
uv run fastapi dev main.py          # run API (requires fastapi[standard])
uv run python -m scripts.generate_orders   # scripts run as modules (they import app/); NOT `python scripts/x.py`
uv run pytest                       # all tests
uv run pytest path/to/test.py::test_name   # single test
uv run ruff check . && uv run ruff format .
```

## Architecture (target)

Layered package; keep `main.py` as a thin entrypoint once the package exists.

- **routers**: HTTP only (request/response models, error mapping).
- **services**: orchestration — question → LLM → validate → execute.
- **repositories / db**: SQLAlchemy + PostgreSQL (`psycopg` 3) access; the only layer touching the database. The views are defined in SQL here.
- **schemas**: Pydantic models.
- **LLM client**: isolated behind an interface so tests inject a mock; the endpoint test must never hit the network.
- **SQL validator**: separate, pure, unit-testable module. Must reject anything non-`SELECT`, multiple statements, and any table/view outside the allowlist, regardless of what the LLM returns. Execute with a read-only DB role (`app_ro`, SELECT-only on allowed tables/views) in a read-only transaction as defense in depth.
- **Data scripts** (generate, clean/load): standalone, idempotent; cleaning logic lives in an importable function so it is testable.

LLM prompt must include the schema of the allowed tables/views only (PostgreSQL dialect).

## Infrastructure

`docker-compose.yml` (repo root) defines `llm` (llama.cpp), `db` (`postgres:17-alpine`, volume `pgdata`, credentials from root `.env`; `POSTGRES_PASSWORD` is required) and, once built, `api` (depends on `llm` and `db` healthy). Services share the `backend` network and reach each other by service name (`db:5432`, `llm:8080`). Full plan: `coding_assesment/PLAN.md`.

```
docker compose up -d db llm         # infra only; run API locally with uv
docker compose up --build           # everything, once the api service exists
```
