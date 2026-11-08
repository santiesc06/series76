# Technical Design: Series 76 Technical Assistant

The decision log for the project: what we build, how, and why. Requirements and acceptance criteria live in
[`requirements.md`](requirements.md); this document says how the system meets them.

**Status legend:** ✅ Decided · ❓ Open. All proposals were approved on 2026-11-07.

---

## 1. Architecture overview

```
 series_76_electric_data.pdf
          │  ingest extract (vision LLMs, offline, once)
          ▼
 data/interim/*.json ──► ingest validate ──► human review ──► data/processed/actuators.json  (committed)
                                                                      │  ingest load (on container start)
                                                                      ▼
 Android app ──HTTP/JSON──► FastAPI ──► Conversation service ──► LangChain agent ──► tools ──► PostgreSQL
 (Compose)                    │                 │                     │                        (catalog +
                              │                 └── persists messages, products, debug data ──► conversations)
                              └── /debug endpoint (developer only)
```

Principle: **the LLM decides *what* to look up and *what* to show; the database supplies every number.**

---

## 2. Data and ingestion

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| A1 ✅ | **Dual extraction:** two vision models from **different families** each extract every table to JSON: **Model A = Gemini via Google AI Studio (free tier)**, **Model B = a cheap non-Google model via OpenRouter**. A script diffs them; every disagreement is resolved by a human against the PDF; then the validation suite runs. Both providers are called through the same OpenAI-compatible client, so each model is just a base URL + key + name in `.env`. | ✅ | The tables are images, so text parsers return nothing. Two independent models rarely make the *same* mistake, so the diff points the human to likely errors instead of re-reading 1,000+ cells. Total cost about USD 0.01, which keeps the budget for the agent and evals. A fully free variant (Gemini + Gemma) works but its errors are less independent. Free-tier requests may be used by Google for training; acceptable here because the datasheet is public. OCR (Tesseract) is free but noisy on these layouts. |
| A2 ✅ | **Table metadata is hand-written**, not extracted: `data/table_metadata.yaml` holds, per table, enclosure, voltage, phase, AC/DC, service layout, certifications, hazardous markings and footnotes. The LLMs only extract the numeric rows. | ✅ | 7 tables, static information, safety-relevant (D-2). Writing it by hand is faster and more reliable than extracting it. |
| A2b | **Rows are matched by model code; the part number ending is table metadata.** Every row of a table prints the same ending after the 4-character model code (e.g. `763B` + `00-11300000/A`), so the canonical part number is model code + the hand-checked `part_number_suffix`. Transcriptions that differ are reported as warnings. | ✅ | Found in practice: Gemini dropped a zero in all 11 part numbers of one table, twice, while every value was right. Checking 7 endings by hand is more reliable than trusting 68 transcriptions. |
| A3 ✅ | **One committed, canonical file:** `data/processed/actuators.json` (typed, reviewed). | ✅ | JSON keeps types and nesting (ratings per service). A reviewer can diff it in a PR. |
| A4 ✅ | **Ingest CLI** `python -m ingest <command>`: `extract` (needs a key, writes `data/interim/`), `validate` (rules + diff report), `load` (idempotent upsert into Postgres, no key needed). Docker runs only `load`. | ✅ | Reviewers reproduce without spending money; extraction stays re-runnable and documented. |
| A5 ✅ | **Validation rules** (pytest, `tests/test_data.py`): row counts per table (11, 16, 11, 5, 5, 10, 10); part number regex; no duplicates; Nm ≈ in-lbs × 0.113 within ±5%; LRA ≥ FLA; 50 Hz speed ≥ 60 Hz speed; values in sane ranges; ~15 hand-checked spot values. | ✅ | Catches misread digits automatically, every time CI runs. |

### Database schema (✅)

Normalized to match how the tables are actually shaped:

```
catalog_tables   one row per source table (7)
  code (PK: 'wp_110_1ph', 'xp_24_onoff', ...), title, page, enclosure ('weatherproof'|'explosionproof'),
  voltage (24|110|220), phase ('single'|'three'|null), current_type ('ac'|'dc'|'ac_dc'),
  frequency_dependent (bool), service_split (bool), layout, certifications text[], markings text[],
  hazardous jsonb (division, zone, nec_gas_groups, iec_gas_group, temperature_class, dust_rated),
  summary_claim, notes text[], footnotes text[]

parts            one row per Base Part Number (~68)
  part_number (PK, display form), match_key (unique, for matching), model_code ('763B'),
  size (1..7), table_code → catalog_tables, data_available (bool, false for N/A), position,
  csa_certified (bool, footnote override), motor_power_w,
  speed_s_60hz, speed_s_50hz, fla_a_60hz, fla_a_50hz, lra_a_60hz, lra_a_50hz

ratings          one row per part × service (single-phase parts have 2 rows)
  id, part_number → parts, service ('on_off'|'modulating'|'both'),
  torque_inlb, torque_nm, duty_cycle_pct, cycles_per_hour, starts_per_hour

sessions         id (uuid), user_id (nullable, login-ready), title, created_at, updated_at
messages         id (uuid), session_id, role ('user'|'assistant'), content, payload jsonb, debug jsonb, created_at
```

- **Why normalized:** in the PDF, speed/current/power belong to the *part* and torque/duty cycle belong to the *service*. One flat table would duplicate electrical data or need nullable column pairs.
- **Hazardous markings as JSONB** (✅ changed from separate columns during Phase 2; approved by the user 2026-11-07): a small fixed structure read whole for 2 tables, never filtered by key in SQL. Trade-off: Postgres checks only that the field is valid JSON, not the type of each key; correctness comes from the hand-reviewed `table_metadata.yaml` and the hazardous-area tests. If SQL filtering by zone were ever needed: JSON operators (`(hazardous->>'zone')::int`) or an Alembic migration to columns.
- **24V tables** (not frequency dependent): the single value is stored in both the 60 Hz and 50 Hz columns, and `frequency_dependent = false` tells the app to show one value. Filters stay uniform.
- **Migrations:** Alembic. The container runs `alembic upgrade head` then `ingest load` on start.

---

## 3. Agent

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| B1 | **LangChain 1.x `create_agent`** (tool-calling loop on the LangGraph runtime), no hand-built graph. Max 6 tool iterations per turn, 30 s LLM timeout. | ✅ | Standard modern LangChain API, meets the "orchestrated with LangChain" requirement, less custom code to defend. |
| B2 | **Three tools**, all fixed parameterized queries (no text-to-SQL): see §3.1. | ✅ | Predictable, testable without an LLM, no injection risk. Less flexible than free SQL; acceptable for ~68 parts. |
| B3 | **Structured final answer:** the agent ends each turn with `{answer_text, status, view, product_refs, alternative_refs, quick_replies}`. It refers to products **by part number only**. The backend then **hydrates** those refs from the database into `products`. Refs not returned by a tool in this turn (or the context) are rejected. | ✅ | This is how NFR-01 is guaranteed by construction: the LLM picks *which* products to show, never their numbers. |
| B4 | **Answer-text number check:** every number in `answer_text` must appear in this turn's tool results (part numbers and units excluded). On failure: one repair retry with a correction message; if it still fails, the text is replaced with a safe generic sentence and the cards carry the data. Result is recorded in the debug data. | ✅ | Defense in depth for the free text. Costs one extra LLM call only when the model misbehaves. |
| B5 | **Conversation context:** the LLM receives the last `HISTORY_WINDOW` user/assistant messages (text only, not raw tool output) plus a short **context note** built from stored payloads: products shown recently and the last search filters. | ✅ | Makes follow-ups (US-02, US-09) reliable and cheap. Alternative rejected: LangGraph's Postgres checkpointer replays everything, owns its own schema, and gives less control over what the app and debug screen need. |
| B6 | **System prompt in a versioned file** (`app/agent/prompts/system.md`): scope, the numbers rule, when to ask (power supply missing), language rule, D-1…D-6 interpretations, short field definitions taken from the summary PDF (US-06), and refusal of role-change attempts. | ✅ | Prompt changes show up in PR diffs and can be eval-tested. |
| B7 | **Models** (env-configurable): see §3.2. | ✅ | |

### 3.1 Tools

| Tool | Input | Output |
|---|---|---|
| `lookup_part` | `query` (full or partial part number, any case/spacing) | `found` (part + ratings) · `partial` (list of variants) · `no_data` (N/A part) · `not_found` (up to 5 closest real part numbers by edit distance) |
| `search_actuators` | optional filters: enclosure, voltage (±10% mapping, D-4), phase, current type, service, min torque + unit, max speed + frequency, min duty cycle, min cycles/hour, min starts/hour, max FLA, max motor power, CSA required, hazardous zone / division / gas group / dust; `sort_by`; `limit ≤ 5` | `matches` (ranked smallest-adequate first, with total count) · or `no_match` with the **failing constraints** and up to 3 **alternatives** that meet all other constraints |
| `catalog_overview` | none | available enclosures, power supplies, torque range per table, markings. Used to ask good clarifying questions. |

- **Requirements are named predicates evaluated in Python** over the catalog loaded in one query (✅ changed from a planned SQL view during Phase 2; approved by the user 2026-11-07). The database is queried once per search; explaining a failure (US-10) re-checks the requirements in memory, where the SQL version would need one query per requirement. Instant up to thousands of parts. Scaling path: (1) keep the catalog cached in memory and reload it only after `ingest load`; (2) at tens of thousands of parts, move each named predicate into a SQL `WHERE` condition (one-to-one, mechanical).
- **Failing requirement detection (decided in Phase 2, found by the US-10 test):** requirements are split into *setting* (enclosure, voltage, phase, AC/DC, service, CSA, hazardous area) and *performance* (torque, speed, duty cycle, cycles/starts, current, power). Setting requirements are kept; a performance requirement is reported as failing when dropping it alone gives results, and the alternatives are the closest models on that metric that meet everything else. If the setting itself does not exist (e.g. 24V AC modulating), each setting requirement whose removal gives results is reported with one example.
- **Hazard hierarchy (D-2e, option A):** Zone 1 / Division 1 / IIB markings also cover Zone 2 / Division 2 / IIA, as interpretation of NEC/IEC conventions (`app/services/hazardous.py`). The literal-only alternative was rejected because the most common hazardous area (Zone 2) would never get an answer.
- **Safety rule:** a hazardous-area requirement, or "explosionproof", is never relaxed to suggest an alternative. A hydrogen (IIC) area gets "no model", never a weatherproof suggestion.
- **Lookup matching (decided in Phase 2):** input is normalized to letters and digits (`763b00 11300000 a` = `763B00-11300000/A`). Prefix matching applies only to short input (≤ 6 characters, e.g. `761A00`), so a full-length number with a typo is never silently resolved to a near match; it returns `not_found` with up to 5 suggestions by edit distance. Input not starting with `7` + digit is `invalid_input`.
- **Comparison** needs no tool: the agent returns 2+ refs with `view = "comparison"`.
- **Term explanations** (US-06) come from the system prompt, not a tool.

### 3.2 Models (prices from OpenRouter's public model list, 2026-11-07, USD per 1M tokens)

| Role | Proposed default | Alternative to evaluate | Price in / out |
|---|---|---|---|
| Agent (`LLM_MODEL`) | `anthropic/claude-haiku-5.5` | `openai/gpt-6-luna` | 0.10 / 0.50 (both) |
| Extraction A (`EXTRACTION_A_*`) | a Gemini Flash model on **Google AI Studio (free tier)** | n/a | free |
| Extraction B (`EXTRACTION_B_*`) | `anthropic/claude-haiku-5.5` via OpenRouter | `openai/gpt-6-luna` | 0.10 / 0.50 |

- **Cost estimate per chat turn:** ~3 LLM calls × ~4k input tokens + ~600 output tokens ≈ **USD 0.002**. 1,000 turns of development and evals ≈ USD 2.
- **Choosing the agent model with data:** run the eval set on both candidates and pick by pass rate, then latency and cost. The README reports the numbers.
- **Extraction runs once** (4 pages): about USD 0.01 in total. The exact free Gemini model is chosen from AI Studio's free-tier list on the day of extraction and recorded in the README.

---

## 4. API

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| C1 | Endpoints: `POST /api/conversation`, `GET /api/sessions`, `GET /api/sessions/{id}/messages`, `GET /api/messages/{id}/debug`, `GET /health`, `GET /health/ready`. OpenAPI docs at `/docs`. | ✅ | Follows the suggested endpoints, adds a separate debug endpoint. |
| C2 | **Debug data is not in end-user responses**; it is served by `/api/messages/{id}/debug`, enabled by `DEBUG_ENDPOINTS=true` (on by default in docker-compose so evaluators can use the debug screen). | ✅ | End-user payloads never carry internals. In production the flag would be off or behind auth. |
| C3 | **No streaming.** One request per turn (~3–8 s), with a typing indicator in the app. | ✅ | Streaming (SSE) is nicer but adds complexity on both sides and conflicts with the post-answer number check (B4). |
| C4 | **Error format:** `{"error": {"code": "...", "message": "..."}}` with 400/404/422, 502 (LLM provider failed or budget exhausted), 503 (database down). | ✅ | One shape for the app to handle. |
| C5 | Session created on the first message; title = first query truncated to 60 characters (no LLM call). Unknown `session_id` → 404 (US-16 AC4). | ✅ | |
| C6 | `sessions.user_id` exists from the start (nullable), so login (US-21) needs no schema rework. | ✅ | **Changed 2026-11-08 by U3** (user approved): the column became a UUID foreign key to `users.id`, one small migration, so the database guarantees every conversation has a real owner. |
| C7 | History responses return the **snapshot** of products as the user saw them (stored in `messages.payload`), not re-hydrated data. | ✅ | The past conversation shows what was actually answered. |

### 4.1 `POST /api/conversation` response

```json
{
  "session_id": "2b0c…",
  "message_id": "9f1e…",
  "answer": "The 763B00-11300000/A delivers 500 Nm in On/Off service.",
  "status": "answered",
  "view": "cards",
  "products": [
    {
      "part_number": "763B00-11300000/A",
      "model_code": "763B",
      "enclosure": "weatherproof",
      "power_supply": { "label": "110V single phase", "voltage": 110, "phase": "single", "current_type": "ac" },
      "certifications": ["CSA", "CE", "UKCA"],
      "hazardous_markings": [],
      "data_available": true,
      "notes": [],
      "highlight": ["on_off.torque"],
      "spec_groups": [
        { "title": "On/Off service", "key": "on_off", "specs": [
          { "key": "torque", "label": "Output torque", "values": [ { "value": 4400, "unit": "in-lbs" }, { "value": 500, "unit": "Nm" } ] },
          { "key": "duty_cycle", "label": "Duty cycle (S4)", "values": [ { "value": 30, "unit": "%" } ] },
          { "key": "cycles_per_hour", "label": "Cycles per hour", "values": [ { "value": 16, "unit": "cycles" } ] } ] },
        { "title": "Electrical", "key": "electrical", "specs": [
          { "key": "speed", "label": "Operating speed", "values": [ { "value": 26, "unit": "s", "condition": "60 Hz" }, { "value": 32, "unit": "s", "condition": "50 Hz" } ] } ] }
      ]
    }
  ],
  "alternatives": [],
  "quick_replies": [],
  "created_at": "2026-11-07T15:04:05Z"
}
```

- `status`: `answered` · `clarification_needed` · `not_found` · `no_data` · `no_match` · `out_of_scope`
- `view`: `none` · `cards` · `comparison`
- `quick_replies`: `[{ "label": "110V single phase", "message": "110V single phase" }]`. One mechanism for clarification options (US-08), part number variants (US-04) and "did you mean" suggestions (US-03).
- **Server-driven specs:** labels, units, grouping and order come from the backend, so the app renders any product generically and the comparison table is built from the same structure.

### 4.2 `GET /api/messages/{id}/debug` response

`{ message_id, model, latency_ms, tokens: {input, output}, steps: [{tool, args, result, duration_ms, error}], number_check: "pass"|"repaired"|"fallback", context_note }`

---

## 5. Mobile app

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| M1 | Kotlin + Jetpack Compose, single module; MVVM with unidirectional data flow (UI state as sealed classes, `StateFlow`); Hilt; Retrofit + OkHttp + kotlinx.serialization; Navigation Compose. | ✅ | Standard modern Android stack. Windows rules out SwiftUI. |
| M2 | **No local database** (no Room): the backend is the source of truth for conversations. | ✅ | Offline support is not required; saves a day. |
| M3 | minSdk 26, target/compile the latest stable SDK. | ✅ | Covers almost all devices, allows modern APIs. |
| M4 | Base URL from a Gradle property (`local.properties`: `api.baseUrl`), default `http://10.0.2.2:8000/` (emulator → host). Cleartext HTTP allowed **only in the debug build** via network security config. | ✅ | Point to any backend without code changes. |
| M5 | **Debug screen:** exists only in the `debug` build type; opened by **long-pressing an assistant message** → "Developer details". | ✅ | End users never see it (release builds don't contain it). |
| M6 | Design: Material 3 via Material Theme Builder (Figma plugin), light + dark themes, tabular figures for numbers, specs in a fixed order. Screens and components designed in Figma first; exports in `docs/design/`. | ✅ | Brand color chosen 2026-11-07: **safety amber, seed `#C25E00`**. Figma scope (user, 2026-11-07): Material Theme Builder theme (exported to `docs/design/theme/`, used as is) + quick frames of the 3 screens; the frames are **deferred until after a working demo** (user, 2026-11-07), and the app follows the M6 rules directly. Because amber reads as a warning color, warnings, no-match and hazardous-area notes **never rely on color alone**: they always carry an icon and text and use the theme's error role, not the brand color. |

---

## 6. Quality

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| Q1 | **Test pyramid:** (1) data validation tests; (2) tool and repository tests against **real PostgreSQL** (local compose; GitHub Actions service container in CI); (3) API tests with LangChain's fake chat model (no cost); (4) evals with the real LLM. | ✅ | SQLite would behave differently from Postgres (arrays, JSONB). The LLM is never called in CI. |
| Q1b | **Tests never read `.env`:** `APP_DISABLE_DOTENV=1` (set in `tests/conftest.py` and CI) makes settings use only real environment variables and defaults. Tests use a separate database (`series76_test`), migrated with Alembic and loaded once per run; each test runs in a rolled-back transaction. | ✅ | No secrets can reach tests, and the dev database is never modified by tests. |
| Q2 | **Evals** (`evals/questions.yaml`, ~30 cases, single and multi-turn): deterministic assertions on `status`, expected / forbidden part numbers in `products`, and the number check. **No LLM-as-judge.** Run manually: `uv run python -m evals.run --model …`; results and cost recorded in `docs/evals.md`. | ✅ | Deterministic, free to grade, every case traces to an AC. |
| Q3 | CI: lint + format + tests with a Postgres service. Android `assembleDebug` job only if time allows. | ✅ | |
| Q4 | Token usage and estimated cost logged per request. | ✅ | NFR-05. |
| Q5 | **Evals run on OpenRouter models only:** prompt iteration and reported results both use the shipped model, and the model comparison uses OpenRouter candidates (e.g. `gpt-oss-120b` as the cheapest). Unit tests keep the scripted fake model (USD 0). Google AI Studio's free API stays limited to extraction (A1), where the assessment's hint applies. | ✅ 2026-11-07 | Measured cost: ~USD 0.0011 per turn on Haiku 5.5, so ~USD 0.05 per eval run and under USD 1 for all iteration. Gemini would save cents, but a prompt tuned on Gemini may not transfer to the shipped model, the free tier's low daily limit can stop a run, and a second provider adds config. Every reported result describes a real candidate model (assessment §5.1). |
| Q6 | **Langfuse tracing (optional):** a LangChain callback sends each turn's trace (LLM calls, tool calls, tokens, latency) to Langfuse Cloud, only when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are set. Off by default. Not self-hosted. Our own debug data in PostgreSQL stays the source for the app's debug screen (US-19). | ✅ 2026-11-07 | A developer dashboard with no setup cost for the evaluator. Self-hosting Langfuse needs ClickHouse, Redis and object storage, too heavy for `docker compose up`. Trade-off: traces go to a third party, and two more secrets live in `.env`. |

---

## 7. Delivery

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| P1 | One branch + PR per phase, conventional commits, CI green before merge. | ✅ | |
| P2 | This document is the decision log; **no separate ADR files**. The README's "Design and architecture" section summarizes it and links here. | ✅ | Avoids writing the same decisions twice. |
| P3 | Docs: `README.md`, `docs/requirements.md`, `docs/design.md`, `docs/evals.md`, `docs/design/` (Figma exports), `.claude/`. | ✅ | |

### Build order

1. **Data:** table metadata YAML → dual extraction → diff and review → validation tests → `actuators.json`.
2. **Database and tools:** Alembic schema → `ingest load` → repositories → 3 tools + tests.
3. **Agent and API:** prompt → agent → hydration and number check → conversation service → endpoints → API tests.
4. **Evals and Docker:** eval set and runner → Dockerfile and compose → fresh-clone check. The **model comparison** (§3.2) is deferred until after the app (user, 2026-11-07): it does not affect the app, and Haiku 5.5 already passes the full eval set.
5. **App:** Figma → theme → networking → Conversations → Chat (cards, comparison, quick replies) → Debug.
6. **Docs and delivery:** README, evals report, final fresh-clone test.

---

## 7b. Phase 3 implementation details (✅ approved 2026-11-07)

Details the approved decisions (B1–B7, C1–C7) left open, decided while implementing Phase 3.

| ID | Detail | Why / trade-off |
|---|---|---|
| B3a ✅ | **Invalid FinalAnswer calls** (✅ user, 2026-11-08): leaked tool markup (`</parameter>`, `<parameter name=…>`) is cut from `answer_text`; an invalid call gets a plain retry message naming the failed fields (e.g. `status: missing`) instead of the raw pydantic error; the server log records the number of invalid calls and which fields failed (`agent error` detail, `format_retries` on each turn), never the answer text. **Tried and reverted:** moving `answer_text` last so the short fields are written first; with it `out-of-scope-price` failed in 2 of 2 runs (status `answered` instead of `out_of_scope`), so `answer_text` stays first. Rejected: answering with the products already found when the agent gives up. | Seen once with Haiku via OpenRouter: the model wrote `view` and `product_refs` as XML inside `answer_text`, left out `status`, repeated it on every retry and the turn ended in `agent_step_limit` (504). The same question passes the `compare-two` eval, so it is intermittent. Writing the answer before the status acts as a short reasoning step. Trade-off: if the model keeps failing despite the clearer message, the user still gets the error and retries. |
| B4a ✅ | **Number check sources:** a number in `answer_text` passes if it appears in this turn's tool results (values, string values and JSON keys), in anything the user wrote in the conversation, or in the field definitions of the system prompt (90° turn, 50/60 Hz). Part numbers, model codes and digits glued to letters (S4, T4, IIB) are ignored. Decimal comma and thousands dot (Spanish) are understood. | The user's own requirement ("5000 Nm") may be repeated back; it is not a spec value. |
| B4b ✅ | **Bare integers up to 10 are not checked; followed by a unit they are** ("5 A", "8 starts", "3 Nm", "7 s"). Unit symbols are case-sensitive, so the Spanish preposition "a" ("2 a 60 Hz") is not read as amperes. | Counts and ordinals ("2 models", "Zone 1") would cause false repairs, while a small number with a unit is a spec value. Chosen over "skip all small integers" (misses "5 A") and "check every number" (repairs every count). Trade-off: a small spec value written without a unit is not caught; cards still show the exact value. |
| B4c ✅ | **Fixed fallback sentence in English or Spanish** when the repair attempt also fails, chosen by a word-list check on the user's message (Spanish-only characters ¿ ¡ ñ, or more Spanish than English function words; English by default). | Keeps NFR-04 without another LLM call. Chosen over "always English". Trade-off: other languages get the English sentence. |
| B4d ✅ | The repair request is sent to the model as an extra message marked "[Automatic check, not from the user]" and is never saved in the history. | Keeps the conversation history clean. |
| B5a ✅ | **Context note** = part numbers shown in the last 3 assistant turns (most recent first) + the last search filters, appended to the system prompt. `HISTORY_WINDOW` counts messages (user and assistant), text only. | Enough to resolve "it", "that one", "the same but explosionproof" without resending tool outputs. |
| B8 ✅ | **A failed turn is rolled back:** if the LLM fails, nothing is saved (no empty new conversation). | The app shows the error with retry; the user's question is not lost on the device. |
| B9 ✅ | **Highlights are decided by the backend** from the search filters of the turn (min torque → "torque", max speed → "speed"…), not by the LLM. Alternatives carry a `match_note` ("Does not meet: torque ≥ 5000 Nm"). | Deterministic, and the app needs no logic to explain alternatives. |
| B10 ✅ | **View normalization:** `comparison` with fewer than 2 products becomes `cards`; products present but view `none` becomes `cards`; only alternatives → `cards`. | The LLM's view choice cannot produce an empty or broken screen. |
| C2a ✅ | `DEBUG_ENDPOINTS` defaults to **true** in the code too (not only in Compose). When false, the debug endpoint answers 404 as if it did not exist. | The debug screen works in local runs without extra config. Production would set it to false. |
| C4a ✅ | Error codes: `not_found` 404, `invalid_request` 422, `llm_unavailable` / `llm_auth` / `llm_rate_limited` / `llm_budget_exhausted` 502, `agent_step_limit` 504, `llm_not_configured` / `database_unavailable` 503, `internal_error` 500. | One machine-readable code per failure type, so the app can show the right message. |
| C8 ✅ | `GET /api/sessions` also returns `message_count`. | Lets the app show a count or skip empty sessions; costs one grouped count. |

---

## 7c. Phase 4 implementation details (✅ approved 2026-11-07)

| ID | Detail | Why / trade-off |
|---|---|---|
| E1 ✅ | **Eval runner calls the conversation service in-process** (`handle_turn`, the same code the API runs), not over HTTP. Each case runs in a transaction that is **rolled back**, so eval conversations never stay in the database. | No server to start and nothing to clean up. Trade-off: HTTP routing and serialization are not exercised (the API tests cover them). |
| E2 ✅ | **Always-on checks** for every eval turn: no tool names in the answer, the number check did not fall back, no invented part number was rejected, and the answer is in the question's language (B4c detector). Plus per-turn checks from `questions.yaml` (status, expected / excluded part numbers, product fields, alternatives, quick replies, answer substrings). | Deterministic and free to grade (Q2). A test fails on unknown check names, so a typo cannot silently skip a check. |
| E3 ✅ | **Cost guard:** `--max-cost` (default USD 1) stops a run; prices per model in `evals/models.yaml`. Results go to `evals/results/<timestamp>_<model>.json` and are committed as evidence for `docs/evals.md`. | Protects the USD 10 key. Committed results let the reviewer see real runs without spending. |
| E4 ✅ | **Cases state the power supply** whenever the expected outcome is a recommendation or a no-match. Where the AC example has none (US-07 AC5 "fastest explosionproof", US-10 AC3 "at least 10,000 Nm"), US-08 AC1 tells the agent to ask first, so the eval either adds the supply or accepts `clarification_needed` too. | Those ACs and US-08 AC1 conflict when no supply is given; asking is the safer behavior and matches the prompt. |
| D1 ✅ | **Docker image:** `python:3.12-slim` + uv, **runtime dependencies only** (no dev/ingest groups), non-root user, healthcheck on `/health/ready`, `APP_DISABLE_DOTENV=1`. On every start: `alembic upgrade head` → `python -m ingest load` → uvicorn (A4). `ingest/paths.py` imports PyYAML lazily so `load` runs without it. | `docker compose up --build` gives a working system on an empty database (verified from a fresh copy). Reloading the catalog on every start is idempotent and takes under a second. |
| D2 ✅ | **Compose passes an explicit list of variables** to the backend (`environment:` with `${VAR:-default}`), not `env_file: .env`. Compose reads the values from `.env`; the image never contains it (`.dockerignore`). `DATABASE_URL` is built from the `POSTGRES_*` values with host `db`. `API_PORT` (default 8000) sets the host port. | Only the variables the backend needs reach the container (extraction keys do not). `docker compose --env-file .env.example …` runs everything without reading `.env`. |
| D3 ✅ | **CI builds the Docker image** (new `docker-build` job). | A broken Dockerfile fails the PR instead of the evaluator's first run. |
| B10a ✅ 2026-11-07 | **Slots follow the status** (extends B10, found by the first eval run): with `no_match`, any `product_refs` become alternatives (with their "Does not meet / Available if you relax" label); with `clarification_needed`, no cards are shown and the choices are the quick replies. The prompt asks for the same; the debug data records `slot_fix` when the backend had to correct it. | First eval run: the model showed relaxed or example models as matches in 4 of 34 cases. A deterministic rule means a non-matching part can never look like a match, whatever the model does. Trade-off: an ambiguous follow-up ("which of the two?") does not repeat the two cards; the quick replies name them. |
| B2a ✅ 2026-11-07 | **Power-supply guard in the search tool:** a search without a voltage whose matches span 2+ power supplies returns `power_supply_needed` with the supplies that have matches (and how many), and no product list; the agent asks, offering those supplies as quick replies. If only one supply has matches it answers directly; if nothing matches it says "no model" as before. The guard is on for the agent's tool only (`require_power_supply=True`); the service function is unchanged for other callers. | Second eval run: asked "an actuator for 500 Nm", the model showed 5 cards mixing 110V, 220V and 3-phase models and asked for the voltage only at the end (US-08 AC1). Deterministic, and the quick replies offer only supplies that can meet the requirement. Trade-off: browsing questions without a supply ("fastest explosionproof actuator") also get the voltage question first. |
| B4a′ | **Series name and size codes are identifiers** in the number check ("Series 76", "sizes 766 and 767"), unless a unit follows ("766 Nm" is checked). Bug fix within B4a, which already excluded model codes. | First eval run: 5 of 34 cases fell back because "Series 76" was read as an invented value. |
| B4a″ ✅ 2026-11-08 | **Unicode dashes and spaces are read as ASCII** before the number check: look-alike hyphens and dashes (U+2010–U+2015, minus sign, small and full-width hyphen) become `-`, and no-break and thin spaces (U+00A0, U+202F, …) become a space. Bug fix within B4a; only the copy used for checking is changed, never the answer shown. Part-number lookups already ignore punctuation (`match_key`). | Model comparison: gpt-oss-120b wrote "763B00‑11300000/A" with a non-breaking hyphen (U+2011), so the part-number pattern missed it, "11300000" was read as an invented value and correct answers were repaired or replaced. Haiku never did this in the evals, but text pasted from PDFs or Word contains these characters too. |
| L1 ✅ | **Langfuse wiring:** `app/observability.py` imports Langfuse only when both keys are set; runs are grouped by `session_id` and tagged `api` or `eval` + case id; any tracing error is logged and the turn continues without tracing. The eval runner flushes traces at the end. Verified 2026-11-07: an eval run produced its traces in Langfuse Cloud, tagged `eval`. | Q6 says tracing is optional; it must never cost a user's answer. |

## 7d. Phase 5 implementation details (✅ approved 2026-11-07)

| ID | Detail | Why / trade-off |
|---|---|---|
| A1 | **Toolchain:** the Android Studio template (AGP 9.5.1, Gradle 9.6, compile/target SDK 37), Kotlin raised to **2.4.21** with KSP 2.3.13, Hilt 2.60.1, Navigation 2.10.2 (type-safe routes), Lifecycle 2.11, Retrofit 3 + kotlinx.serialization 1.12, OkHttp 4.12. Versions read from Maven Central / Google Maven on 2026-11-07. | The template's Kotlin 2.2.10 cannot reliably read libraries built with Kotlin 2.4. |
| A2 | **Debug screen lives only in the `debug` source set** (`devtools/`), with a no-op `DevTools` object of the same name in `release`. The chat asks `DevTools.ENABLED`; the release APK contains no developer screen or route. Same for cleartext HTTP (debug-only network security config). | Implements M4/M5 with no runtime flag that could be flipped. |
| A3 | **Numbers are formatted like the datasheet** ("4,400", US separators) whatever the device locale; tabular figures in spec rows and the comparison table. | NFR-01: a user can check a value against the PDF character by character. Trade-off: a Spanish-locale user sees "4,400" rather than "4.400". |
| A4 | **Failed send stays on screen** with "Not sent" and Retry; the input is not lost. Retry re-sends the same question to the same session (the backend saved nothing, B8). | US-18 AC3 without a local database (M2). |
| A5 | **Quick replies only on the latest answer**; an empty chat shows three example questions as chips. | Old chips would send out-of-context answers; examples help the evaluator start. |
| A6 ✅ | **Comparison:** `view = comparison` opens the table; any answer with 2+ products offers "Compare side by side" (US-12 AC3). Rows are the union of the products' spec groups in backend order; a missing spec shows "—". Frequency-dependent values stay in one cell with their condition ("26 s (60 Hz)"), so a 24V model is never shown under a 60 Hz label. | Same server-driven structure as the cards (§4.1). |
| A7 ✅ | **Network:** 60 s read timeout (one turn is ~3–8 s, up to ~30 s with a repair); HTTP logging (BASIC, no bodies) in debug builds only; base URL from `local.properties` `api.baseUrl` (M4). | No streaming (C3). |
| A8 ✅ | **Theme:** Material Theme Builder export used as is (seed `#C25E00`), dynamic color off. | Android 12+ wallpaper colors would otherwise replace the brand amber. |
| A9 ✅ | **Local network permission (debug builds):** Android 17 (API 37) silently drops connections from apps to private addresses (such as the emulator's host alias `10.0.2.2` or a LAN IP) unless they hold the runtime permission `ACCESS_LOCAL_NETWORK`. The debug manifest declares it, and `MainActivity` asks for it on start only if the build declares it. Android shows it as "nearby devices". Found on the first emulator run (connect timeouts), confirmed by granting it with `adb` (200 OK). | Keeps M3 (target the latest SDK). Release builds talk to a public HTTPS server and neither declare nor need it. Alternative rejected: target SDK 36 to skip the check, which would change M3. Trade-off: one permission dialog on first launch of the debug app. |

---

## 7e. Optional features plan (✅ user, 2026-11-07)

| ID | Decision | Why / trade-off |
|---|---|---|
| O1 | **Order:** model comparison (fills the README's model-choice table), then login (US-21), then voice (US-22). | Cheapest and closest to a required item first; login is fully specified by the assessment. |
| O2 | **Voice = Whisper on the backend:** the app records audio and sends it to a new transcription endpoint; the backend runs open-source **faster-whisper** (small model) on CPU. The transcript becomes a normal chat message. | Free and keyless, same quality on every phone, and it is the open-source route the assessment allows. Trade-off: the Docker image grows (model weights) and transcription takes a few seconds on CPU. Rejected: Android's built-in recognizer (device-dependent, may send audio to Google, not Whisper) and whisper.cpp in the app (native code and a large APK, too risky for the deadline). |

## 7f. Login plan (US-21, ✅ user, 2026-11-08)

| ID | Decision | Why / trade-off |
|---|---|---|
| U1 | **Opaque tokens stored in the database:** login returns a random token (`secrets.token_urlsafe(32)`); the `auth_tokens` table stores only its SHA-256 hash, the user and an expiry (7 days, `AUTH_TOKEN_TTL_HOURS`). Each request looks the hash up. Rejected: JWT. | Logout really revokes a token, and there is no signing secret to configure, so `docker compose up` keeps working without new keys. A leaked database does not leak usable tokens. Trade-off: one indexed lookup per request; a JWT avoids it but needs a secret and cannot be revoked before it expires without a denylist table. |
| U2 | **argon2id password hashes** (`argon2-cffi`, library defaults). An unknown email is verified against a dummy hash, so the response time does not reveal which emails exist. Rejected: bcrypt (72-byte limit), hand-rolled stdlib scrypt. | OWASP's first recommendation; one small dependency. |
| U3 | **`sessions.user_id` becomes a UUID foreign key to `users.id`** (`ON DELETE CASCADE`), in one Alembic migration. **Changes the detail of C6** ("no schema rework"): the column already existed, but as nullable text with no key. | The column is empty, so the change is safe, and the database then guarantees every conversation points to a real user. Conversations created before login (`user_id` NULL) are visible to nobody; only a dev database has them. |
| U4 | **Every `/api/*` route needs a token** except `POST /api/auth/login`; `/health`, `/health/ready` and `/docs` stay open. Another user's conversation or message returns 404 (`not_found`), not 403. Endpoints: `POST /api/auth/login` → `{token, token_type, expires_at, user}`, `POST /api/auth/logout`, `GET /api/auth/me`. Swagger gets an "Authorize" button (HTTP Bearer). | One rule, no "anonymous" mode to test. 404 does not confirm that someone else's conversation exists. Evals call the service directly, so they are unaffected. |
| U5 | **Test users seeded on every start** from `backend/app/auth/seed_users.json` (email, name, argon2 hash only); the passwords are documented in the README as test values. Idempotent upsert, run in the container start command after `ingest load`. | The repository never holds a plain password in code or data, and a fresh database always has the users the README lists. |
| U6 | **App token storage: Jetpack DataStore** in app-private storage, excluded from cloud backup. Not encrypted at rest. Rejected: Keystore + Tink encryption (more code and a dependency for little gain here); EncryptedSharedPreferences (deprecated). | Standard and simple; the token expires and logout revokes it, which bounds the risk. Listed as a known limitation. |
| U6a | **App flow** (built 2026-11-08, within U6): the root of the app shows the login screen or the app from one session state; the app's navigation is rebuilt on every sign-in, so nothing of the previous user stays on screen. An OkHttp interceptor adds the token and, on a 401 to that token, signs out with "session expired". Logout forgets the token at once, then revokes it on the server (best effort). A saved token opens the app immediately and is confirmed with `GET /api/auth/me`. | No splash wait on start; one place handles every 401. A 401 that arrives for an old token after a new sign-in is ignored. |
| U7 | **Not implemented** (known limitations): login rate limiting, sign-up, password reset, refresh tokens. | Not required by the assessment (§7). |

---

## 8. Extraction run log

| Date | Models | Result |
|---|---|---|
| 2026-11-07 | A `gemini-3.5-flash` (Google AI Studio free tier) · B `anthropic/claude-haiku-5.5` (OpenRouter, USD 0.012) | 912/917 cells agree. 5 conflicts resolved by hand in `data/review/resolutions.yaml`: 4 empty-vs-"N/A" Motor Power cells (page 2) and one merged-cell boundary (`764Y30-11300000/A`, 180 W, page 4). Model A misread all 11 part numbers of `wp_110_1ph` (dropped a zero) in two runs; handled by A2b. Validation rules and 23 independent spot values pass. `gemini-3.8-flash` was unavailable (HTTP 503) at the time. |


## 9. Known limitations

Accepted for this scope; each has a known next step.

| Limitation | Why it is acceptable now | Next step |
|---|---|---|
| Migrations run when the backend container starts. | One backend instance; Alembic runs before the server accepts requests. | With several replicas, run `alembic upgrade head` as a one-off job before rolling out. |
| One eval run per change; LLM output varies between runs. | Temperature 0, deterministic checks, 34/34 on the latest run. | Run each case 3 times and report a pass rate per case. |
| Eval runner switches the model by changing settings at runtime. | It is a command-line tool, not server code. | Pass the model and prices explicitly through the service. |
| `app/services/conversation.py` is ~400 lines (turn flow, response building, reading). | One cohesive flow, covered by API tests. | Move response building (cards, slots, view) into its own module. |
| The image keeps the `uv` binary (~40 MB), needed only at build time. | Simplicity of a single-stage build. | Two-stage build: install in a builder stage, copy `/opt/venv` only. |
| App: unit tests cover formatting and the login session (12 tests); ViewModels are covered by manual runs. | The logic that matters (number check, card slots, search rules) lives in the backend and is tested there. | ViewModel tests with a fake `ChatRepository` and `kotlinx-coroutines-test`. |
| App: the release build compiles but has not been run (R8 is on). | Evaluators run the debug build (it has the developer screen). | Run the release APK; add R8 keep rules for kotlinx.serialization if needed. |
| App: a new chat's `session_id` lives in the ViewModel, so it survives rotation but not process death. | Rare on a demo; the conversation is still in the list. | Store it in `SavedStateHandle`. |
| App: the login token is stored unencrypted in app-private storage (design U6). | Only this app can read it; it expires in 7 days and logout revokes it on the server. | Encrypt it with a Keystore key (Tink). |
| App: a torque requirement highlights the torque row of every service group, not only the service asked for. | Cosmetic; values are correct. | Send highlights as `group.spec` keys from the backend. |
