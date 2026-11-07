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
| A1 | **Dual extraction:** two vision models from **different families** each extract every table to JSON: **Model A = Gemini via Google AI Studio (free tier)**, **Model B = a cheap non-Google model via OpenRouter**. A script diffs them; every disagreement is resolved by a human against the PDF; then the validation suite runs. Both providers are called through the same OpenAI-compatible client, so each model is just a base URL + key + name in `.env`. | ✅ | The tables are images, so text parsers return nothing. Two independent models rarely make the *same* mistake, so the diff points the human to likely errors instead of re-reading 1,000+ cells. Total cost about USD 0.01, which keeps the budget for the agent and evals. A fully free variant (Gemini + Gemma) works but its errors are less independent. Free-tier requests may be used by Google for training; acceptable here because the datasheet is public. OCR (Tesseract) is free but noisy on these layouts. |
| A2 | **Table metadata is hand-written**, not extracted: `data/table_metadata.yaml` holds, per table, enclosure, voltage, phase, AC/DC, service layout, certifications, hazardous markings and footnotes. The LLMs only extract the numeric rows. | ✅ | 7 tables, static information, safety-relevant (D-2). Writing it by hand is faster and more reliable than extracting it. |
| A2b | **Rows are matched by model code; the part number ending is table metadata.** Every row of a table prints the same ending after the 4-character model code (e.g. `763B` + `00-11300000/A`), so the canonical part number is model code + the hand-checked `part_number_suffix`. Transcriptions that differ are reported as warnings. | ✅ | Found in practice: Gemini dropped a zero in all 11 part numbers of one table, twice, while every value was right. Checking 7 endings by hand is more reliable than trusting 68 transcriptions. |
| A3 | **One committed, canonical file:** `data/processed/actuators.json` (typed, reviewed). | ✅ | JSON keeps types and nesting (ratings per service). A reviewer can diff it in a PR. |
| A4 | **Ingest CLI** `python -m ingest <command>`: `extract` (needs a key, writes `data/interim/`), `validate` (rules + diff report), `load` (idempotent upsert into Postgres, no key needed). Docker runs only `load`. | ✅ | Reviewers reproduce without spending money; extraction stays re-runnable and documented. |
| A5 | **Validation rules** (pytest, `tests/test_data.py`): row counts per table (11, 16, 11, 5, 5, 10, 10); part number regex; no duplicates; Nm ≈ in-lbs × 0.113 within ±5%; LRA ≥ FLA; 50 Hz speed ≥ 60 Hz speed; values in sane ranges; ~15 hand-checked spot values. | ✅ | Catches misread digits automatically, every time CI runs. |

### Database schema (✅)

Normalized to match how the tables are actually shaped:

```
catalog_tables   one row per source table (7)
  id, code ('wp_110_1ph', 'xp_24_onoff', ...), title, enclosure ('weatherproof'|'explosionproof'),
  voltage (24|110|220), phase ('single'|'three'|null), current_type ('ac'|'dc'|'ac_dc'),
  frequency_dependent (bool), service_split (bool), certifications text[], markings text[],
  hazardous_divisions int[], hazardous_zones int[], nec_gas_groups text[], iec_gas_groups text[],
  temperature_class text, dust_rated bool, source_page int, notes text[]

parts            one row per Base Part Number (~68)
  part_number (PK, display form), part_number_norm (unique, for matching), model_code ('763B'),
  size (1..7), table_id → catalog_tables, data_available (bool, false for N/A),
  csa_certified (bool, footnote override), motor_power_w,
  speed_s_60hz, speed_s_50hz, fla_a_60hz, fla_a_50hz, lra_a_60hz, lra_a_50hz

ratings          one row per part × service (single-phase parts have 2 rows)
  id, part_number → parts, service ('on_off'|'modulating'|'both'),
  torque_inlb, torque_nm, duty_cycle_pct, cycles_per_hour, starts_per_hour

sessions         id (uuid), user_id (nullable, login-ready), title, created_at, updated_at
messages         id (uuid), session_id, role ('user'|'assistant'), content, payload jsonb, debug jsonb, created_at
```

- **Why normalized:** in the PDF, speed/current/power belong to the *part* and torque/duty cycle belong to the *service*. One flat table would duplicate electrical data or need nullable column pairs. A SQL view `v_ratings` joins all three for searching.
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

- **Failing constraint detection** is deterministic: re-run the search dropping one constraint at a time; the constraints whose removal gives results are the failing ones.
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
| C6 | `sessions.user_id` exists from the start (nullable), so login (US-21) needs no schema rework. | ✅ | |
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
| M6 | Design: Material 3 via Material Theme Builder (Figma plugin), light + dark themes, tabular figures for numbers, specs in a fixed order. Screens and components designed in Figma first; exports in `docs/design/`. | ✅ | ❓ Brand color still to choose. |

---

## 6. Quality

| ID | Decision | Status | Why / trade-off |
|---|---|---|---|
| Q1 | **Test pyramid:** (1) data validation tests; (2) tool and repository tests against **real PostgreSQL** (local compose; GitHub Actions service container in CI); (3) API tests with LangChain's fake chat model (no cost); (4) evals with the real LLM. | ✅ | SQLite would behave differently from Postgres (arrays, JSONB). The LLM is never called in CI. |
| Q2 | **Evals** (`evals/questions.yaml`, ~30 cases, single and multi-turn): deterministic assertions on `status`, expected / forbidden part numbers in `products`, and the number check. **No LLM-as-judge.** Run manually: `uv run python -m evals.run --model …`; results and cost recorded in `docs/evals.md`. | ✅ | Deterministic, free to grade, every case traces to an AC. |
| Q3 | CI: lint + format + tests with a Postgres service. Android `assembleDebug` job only if time allows. | ✅ | |
| Q4 | Token usage and estimated cost logged per request. | ✅ | NFR-05. |

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
4. **Evals and Docker:** eval set and runner → model comparison → Dockerfile and compose → fresh-clone check.
5. **App:** Figma → theme → networking → Conversations → Chat (cards, comparison, quick replies) → Debug.
6. **Docs and delivery:** README, evals report, final fresh-clone test.

---

## 8. Extraction run log

| Date | Models | Result |
|---|---|---|
| 2026-11-07 | A `gemini-3.5-flash` (Google AI Studio free tier) · B `anthropic/claude-haiku-5.5` (OpenRouter, USD 0.012) | 912/917 cells agree. 5 conflicts resolved by hand in `data/review/resolutions.yaml`: 4 empty-vs-"N/A" Motor Power cells (page 2) and one merged-cell boundary (`764Y30-11300000/A`, 180 W, page 4). Model A misread all 11 part numbers of `wp_110_1ph` (dropped a zero) in two runs; handled by A2b. Validation rules and 23 independent spot values pass. `gemini-3.8-flash` was unavailable (HTTP 503) at the time. |
