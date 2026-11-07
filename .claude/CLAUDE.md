# Series 76 Technical Assistant

Technical assessment (Konecto, AI Engineer). Requirements and acceptance criteria: `docs/requirements.md`. Design decisions and build order: `docs/design.md`.

## Layout
- `backend/`: FastAPI + LangChain agent + PostgreSQL. Python 3.12, managed with `uv`.
  - `app/api/` routes · `app/services/` business logic · `app/db/` models/session/repositories
  - `app/tools/` LangChain tools (thin wrappers over repository queries) · `app/agent/` agent + prompts
  - `ingest/` PDF → JSON extraction and JSON → Postgres load · `tests/` pytest · `evals/` LLM eval set
- `mobile/`: Android app, Kotlin + Jetpack Compose.
- `data/raw/` source PDFs · `data/processed/` verified, committed table data.

## Non-negotiable rules
- **Numbers shown to users come only from the database** (tool results). The LLM must never produce or recall spec values.
- `series_76_electric_data.pdf` is the only source of truth for numbers. The summary PDF is context only.
- Separate what a document states from what we infer: hazardous marking strings are copied from the PDF; their meaning (zones, gas groups, dust) follows NEC/IEC conventions and must be labelled as interpretation.
- Never open, read or edit `.env`. Commands that load it (e.g. `python -m ingest extract`) are run by the user.
- Never commit `.env` or real keys, never print key values (check only "set / not set"), and never `COPY` `.env` into a Docker image (`.dockerignore` excludes it; keys are passed at runtime). The OpenRouter key has a hard USD 10 cap: use cheap models in dev, never call the LLM from unit tests.
- Tools are fixed, parameterized queries. No text-to-SQL.
- End-user API responses must not expose tool names or internals; debug data lives behind its own endpoint.

## Commands (from `backend/`)
- Install: `uv sync`
- Tests: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format --check .`
- Run API locally: `uv run uvicorn app.main:app --reload`
- DB only: `docker compose up -d db` (from repo root)

## Conventions
- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`), feature branches, PRs into `main`.
- Record every design decision with its trade-off in `docs/design.md` as it is made (no separate ADR files, decision P2).
