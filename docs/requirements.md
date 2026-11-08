# Requirements: Series 76 Technical Assistant

User stories with acceptance criteria (AC). Every criterion maps to a test (`backend/tests/`), an LLM eval
case (`backend/evals/`) or an app check, listed in the **Verified by** column of the traceability table.
Example values come from `series_76_electric_data.pdf` (the only source of truth for numbers).

**Priority** (MoSCoW): **Must** = required by the assessment · **Should** = expected for a robust, general
solution · **Could** = only if time allows.

## ID conventions

Every requirement and decision has a short ID, so code, tests and discussions can point to it
(tests carry comments like `# US-10 AC1`).

| Prefix | Meaning | Defined in | Example |
|---|---|---|---|
| **US-xx** | User story: what a user needs | this document | US-10 "Know when no model meets my requirements" |
| **ACn** | Acceptance criterion: a testable condition inside a story | this document, under each story | US-10 AC1 |
| **NFR-xx** | Non-functional requirement: a quality rule, not a feature | this document | NFR-01 numbers come only from the database |
| **D-x** | Data interpretation decision: how ambiguous parts of the PDF are read | this document | D-1 3-phase ratings apply to both services |
| **A, B, C, M, Q, P + n** | Technical design decision, by area: **A** data, **B** agent, **C** API, **M** mobile, **Q** quality, **P** delivery | `design.md` | B3 the LLM refers to products only by part number |

Decisions marked ✅ are approved. Changing an approved decision requires asking first, and the change is
recorded next to the original with its date and reason.

## Personas

| Persona | Who | Goal |
|---|---|---|
| **Plant engineer** (end user) | Selects actuators for valves and dampers in a plant | Get exact specs fast and pick a model that fits the application |
| **Developer** | Maintains the assistant | See what the agent did (tools, parameters, data) to debug answers |
| **Evaluator** | Runs the project from the repository | Set it up from the README alone and test it with their own cases |

## Scope

- **In:** Series 76 electrical data for the part numbers in the data PDF (weatherproof and explosionproof; 24V, 110V 1-ph, 220V 1-ph, 220V 3-ph; On/Off and Modulating), plus explanations of what the data fields mean.
- **Out:** prices, stock, lead times, mechanical dimensions, valve sizing, other product series. The assistant says so instead of guessing.

## Data interpretation decisions

The tables leave some things open. These decisions are applied everywhere and explained in the README/ADRs.

| ID | Situation in the data | Decision |
|---|---|---|
| D-1 | The **220V 3-phase** table has a single rating (torque, duty cycle, cycles/hour **and** starts/hour) with no On/Off vs Modulating split. | Its rating applies to **both** services: the row lists cycles/hour (an On/Off metric) and starts/hour (a Modulating metric), and the notes give the duty cycle "for on/off and modulating service". Stored as `service = 'both'`, `service_split = false`. Answers about 3-phase models say the table does not split by service. |
| D-2a | Explosionproof tables are titled **"CSA"**; the summary says "CSA, IECEx/ATEX". Certifications are not numbers, and the summary is legitimate context. | **Report both, naming the source:** the per-model table lists CSA plus its markings; the product summary states IECEx/ATEX for the explosionproof line, which the per-model tables do not confirm, so the user should verify the certificate for their model. |
| D-2b | The markings define *where* a model may be used: `Class I, Division 1, Groups C, D; T4`, `Ex d IIB T4 Gb`, `Class I, Zone 1, AEx d IIB T4 Gb`. | Store them as **structured fields** (divisions, zones, NEC gas groups, IEC gas groups, temperature class, dust rating) from a hand-reviewed table metadata file. Hazardous-area suitability is a **deterministic filter**, like torque. |
| D-2c | Some hazardous areas are **not** covered by the markings: Zone 0, NEC Groups A/B, IEC group IIC (hydrogen, acetylene), and dust (no Class II / Group III marking), although the summary mentions "gases or dust". | **Conservative default:** anything not explicitly in the marking is "not listed in the data for this model, verify with the manufacturer", never "yes". Dust suitability is never claimed. |
| D-2d | Explaining a marking can involve numbers that are not in the PDF (e.g. what temperature T4 means). | The agent names the class (`T4`) without stating numbers from memory (NFR-01). A reviewed glossary served by a tool is a possible later extension. |
| D-2e | The markings name the most demanding area covered (Zone 1, Division 1, gas group IIB), not the less demanding ones. | **Standard hierarchy applies** (decided 2026-11-07, option A): equipment marked for Zone 1 is also suitable for Zone 2, Division 1 for Division 2, and group IIB covers IIA (NEC 500/505, IEC 60079). This is interpretation, stated as such in every answer. It refines D-2c: Zone 0, IIC / Groups A–B and dust remain "not covered". |
| D-3 | Torque is given in in-lbs **and** Nm, and the two columns are rounded (700 in-lbs is listed as 80 Nm). | Filter on the column of the unit the user asked for. Never show a converted value as if it came from the table. |
| D-4 | The notes allow a motor voltage tolerance of ±10%. | Map nearby nominal voltages to table voltages within ±10% (120V → 110V, 230V/240V → 220V) and say so. Out of tolerance (e.g. 480V) means no match. |
| D-5 | Speed and current depend on frequency for AC models; the 24V tables have one value. | If the user gives no frequency, show both 60 Hz and 50 Hz; **filter** on 60 Hz and state that assumption. 24V values are frequency independent. |
| D-6 | Some 3-phase part numbers are listed as **N/A**. | They exist (so they are not "invalid") but have no data. They are never recommended. |

---

## Epic A: Look up a specific actuator

### US-01 Look up an actuator by part number · Must
**As a** plant engineer, **I want to** give a Base Part Number and get its technical data, **so that** I don't search the tables by hand.
- **AC1** Given `763B00-11300000/A`, the answer shows its data: enclosure (weatherproof), power supply (110V single phase), On/Off torque 4,400 in-lbs / 500 Nm, Modulating torque 3,350 in-lbs / 380 Nm, speed 26 s (60 Hz) / 32 s (50 Hz), FLA 4.8 A / 4.6 A, LRA 5.0 A / 4.9 A, motor power 90 W.
- **AC2** The part number is recognized regardless of case, surrounding spaces or a missing `/A` suffix (`763b00-11300000` works).
- **AC3** If the question asks for one value ("what's the torque of …"), the answer leads with that value, and the product card still shows the full spec set.
- **AC4** Every number shown matches the source table exactly, with its unit.

### US-02 Ask follow-up questions without repeating the part number · Must
**As a** plant engineer, **I want to** ask follow-ups like "and how much power does it draw?", **so that** the conversation feels natural.
- **AC1** After US-01, "and how much power does it draw?" answers for `763B00-11300000/A` without the user repeating the part number: motor power 90 W and full load current 4.8 A (60 Hz) / 4.6 A (50 Hz).
- **AC2** If several products were discussed, a follow-up that does not say which one asks the user to choose.
- **AC3** "And the same model at 220V?" resolves to the sibling part number (`763B00-11320000/A`) and shows its data.

### US-03 Get help when a part number does not exist · Must
**As a** plant engineer, **I want to** be told clearly when a part number is wrong, **so that** I don't act on wrong data.
- **AC1** Given `761A00-11380000/A` (shown as an example in the summary PDF, but not present in the data), the assistant says it is not in the catalog and shows **no specs**.
- **AC2** It suggests up to 5 real part numbers that are closest to the input (e.g. `761A00-11300000/A`, `761A00-11320000/A`, `761X30-11380000/A`). Suggestions come from the database, never invented, and show no specs until the user picks one.
- **AC3** A typo (`763B00-1130000/A`, one digit missing) is caught as "not found", and the suggestions include both one-edit-away parts (`763B00-11300000/A` and `763B00-11320000/A`). The assistant does not guess between them.
- **AC4** Malformed input (`hello123`, empty string) gets a helpful message, not an error.

### US-04 Resolve a partial part number · Must
**As a** plant engineer, **I want to** type only part of a part number, **so that** I can find it without knowing the full code.
- **AC1** Given `761A00`, the assistant lists the matching variants (110V 1-ph, 220V 1-ph, 220V 3-ph marked "no data") and asks which one, offering them as quick options.
- **AC2** It does not pick one variant silently.

### US-05 Know when data is not available · Must
**As a** plant engineer, **I want to** know when the catalog has no data for a model, **so that** I don't assume values.
- **AC1** Given `761A00-11330C00/A` (N/A in the 3-phase table), the assistant says the part number exists but no electrical data is published for it, and shows no numbers.
- **AC2** Recommendations never return N/A models (D-6).

### US-06 Understand the data fields · Should
**As a** plant engineer, **I want to** ask what a term means ("what is LRA?", "On/Off vs Modulating?"), **so that** I read the specs correctly.
- **AC1** The assistant explains the term using the summary document's definitions and includes no spec numbers unless they come from a lookup.

---

## Epic B: Get a recommendation

### US-07 Get models that meet my requirements · Must
**As a** plant engineer, **I want to** describe my requirements (torque, power supply, enclosure, service type, speed, duty cycle, current…), **so that** I get suitable models.
- **AC1** "Explosionproof, 220V single phase, modulating, at least 2,000 Nm" returns **only** `765Y30-11320000/A` (2,400 Nm modulating). `765X30-11320000/A` (1,600 Nm) is excluded.
- **AC2** Results are ordered from the smallest model that meets the requirement (right-sizing), and the spec that matched is highlighted.
- **AC3** On/Off requirements are checked against On/Off ratings and Modulating against Modulating ratings (3-phase: D-1).
- **AC4** At most 5 results are shown, with a note when more exist.
- **AC5** Superlative questions work: "fastest explosionproof actuator", "lowest full load current at 220V".
- **AC6** "24V AC, modulating" returns no match, because the 24V Modulating table is DC only.

### US-08 Be asked for missing information · Must
**As a** plant engineer, **I want** the assistant to ask when my request is too vague, **so that** recommendations are relevant.
- **AC1** If the **power supply** is missing (it decides which table applies), the assistant asks for it with quick options. Example: "I need an actuator for 500 Nm".
- **AC2** If enclosure or service type is missing, it does not ask. It includes both and labels each result.
- **AC3** Hazardous-area wording ("flammable gas", "hazardous", "ATEX zone") is treated as an explosionproof requirement.
- **AC4** At most one clarifying question per turn.

### US-09 Refine a recommendation · Must
**As a** plant engineer, **I want to** change one requirement in a follow-up ("now the same but explosionproof", "what about at 50 Hz?"), **so that** I don't restate everything.
- **AC1** The previous requirements are kept and only the changed one is replaced.

### US-10 Know when no model meets my requirements · Must
**As a** plant engineer, **I want to** be told when nothing fits and what comes closest, **so that** I can relax a requirement.
- **AC1** "Explosionproof, at least 5,000 Nm" says no model meets it and names the failing constraint (torque).
- **AC2** It shows up to 3 closest alternatives that meet every other constraint, ordered by the failing metric (here: the largest explosionproof, `765Y30-…` at 3,000 Nm On/Off). They are labelled as alternatives, not matches.
- **AC3** "At least 10,000 Nm" (more than any model, max 9,000 Nm) also gets a clear "no model" answer.

### US-11 Use my units, voltage and frequency · Must
**As a** plant engineer, **I want to** use Nm or in-lbs, common voltages and 50 or 60 Hz, **so that** I don't convert by hand.
- **AC1** Torque requirements work in Nm and in-lbs (D-3).
- **AC2** 120V maps to 110V and 230V to 220V, with a note on the ±10% tolerance; 480V gets "no model" (D-4).
- **AC3** "At 50 Hz" makes speed and current answers use the 50 Hz columns. Without a frequency, D-5 applies.
- **AC4** For 24V models, the assistant says the value does not depend on frequency.

### US-12 Compare models side by side · Should
**As a** plant engineer, **I want to** compare two or more models, **so that** I can choose between them.
- **AC1** "Compare 762A00-11300000/A and 762B00-11300000/A" shows both in a side-by-side table with the same spec rows.
- **AC2** Specs that do not apply to a model (e.g. 50 Hz values for 24V) show "—", not 0.
- **AC3** Recommendation results with 2+ models can also be viewed side by side.

### US-13 Check certifications · Must
**As a** plant engineer, **I want to** know the certifications of a model, **so that** I meet site regulations.
- **AC1** Weatherproof models show CSA, CE & UKCA. Explosionproof models show CSA and their hazardous location markings, word for word (D-2a).
- **AC2** Sizes 6 and 7 (`766…`, `767…`) are reported as **not CSA certified** (table footnote), while CE & UKCA still apply.
- **AC3** A requirement for CSA excludes sizes 6 and 7.
- **AC4** "Is it ATEX certified?" gets the sourced answer from D-2a, never a plain "yes".

### US-14 Check hazardous-area suitability · Should
**As a** plant engineer, **I want to** ask whether a model suits my hazardous area (zone, division, gas group), **so that** I don't install unsafe equipment.
- **AC1** "Explosionproof for Zone 1, gas group IIB" or "Class I Div 1, propane (Group D)" returns explosionproof models (D-2b).
- **AC2** Hydrogen or acetylene areas (IIC, Groups A/B) and Zone 0 return **no model**, and the answer says the markings do not cover them (D-2c).
- **AC3** Combustible dust areas return no model and say no dust rating is listed, even though the summary mentions dust (D-2c).
- **AC4** Hazardous wording without details ("flammable gas area") returns explosionproof models and states which zones/groups they are marked for.

---

## Epic C: Conversations (mobile app)

### US-15 See my previous conversations · Must
**As a** plant engineer, **I want** a list of my conversations with title and date, **so that** I can come back to them.
- **AC1** The list shows title (first question, shortened) and last activity date, newest first.
- **AC2** Empty, loading and error states (with retry) are shown.

### US-16 Resume a conversation · Must
**As a** plant engineer, **I want to** open a previous conversation and continue it, **so that** I keep the context.
- **AC1** Opening a conversation loads its full history, including product cards.
- **AC2** Follow-ups continue with the same context (US-02 and US-09 work on a resumed conversation).
- **AC3** This still works after the backend restarts.
- **AC4** A `session_id` that does not exist returns a clear "not found" error (HTTP 404), not a silent new conversation.

### US-17 Start a new conversation · Must
- **AC1** A "New conversation" action opens an empty chat. The backend creates the session on the first message and returns its `session_id`.

### US-18 Read product data clearly · Must
**As a** plant engineer, **I want** specs shown as cards and tables, not paragraphs, **so that** I can scan and compare numbers.
- **AC1** Each product shows as a card: part number, enclosure, power supply, then specs in a fixed order with units.
- **AC2** No tool names, JSON or internal details appear on end-user screens.
- **AC3** While the agent is answering, a "typing" indicator is shown. If the backend fails, an error with retry is shown.
- **AC4** Clarification options (US-04, US-08) are tappable chips that send the choice as the next message.

---

## Epic D: Developer and evaluator

### US-19 Inspect what the agent did · Must
**As a** developer, **I want** a debug screen per answer with the tools called, their parameters and returned data, **so that** I can explain or fix an answer.
- **AC1** For any assistant message, the debug screen lists each tool call: name, arguments, raw result, duration. Model name and token usage are shown too.
- **AC2** It is only reachable in debug builds through a hidden gesture documented in the README.

### US-20 Run everything from the README · Must
**As an** evaluator, **I want to** start the full system with documented commands, **so that** I can test it without asking anyone.
- **AC1** `docker compose up --build` starts the database and backend, creates the schema and loads the verified data.
- **AC2** The README explains how to run ingestion, run the app on an emulator, point it to the backend and open the debug screen.

---

## Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Numeric fidelity:** spec values in `products` are copied from database rows, never generated. Every number in the answer **text** must also appear in that turn's tool results. |
| NFR-02 | **Out of scope:** questions about prices, stock or other products get a polite "not in the data" answer, never an invented one. |
| NFR-03 | **Robustness:** attempts to change the assistant's role or rules ("ignore your instructions…") are declined, and it stays on topic. |
| NFR-04 | **Language:** the assistant answers in the user's language (e.g. Spanish), while part numbers and units stay unchanged. |
| NFR-05 | **Budget:** the OpenRouter key has a USD 10 cap. Unit tests never call the LLM; token usage is logged per request. |
| NFR-06 | **Persistence:** conversations and their debug data survive backend restarts (PostgreSQL). |
| NFR-07 | **Configurability:** models, keys and URLs come from environment variables. No secrets in the repository. |
| NFR-08 | **Resilience:** LLM or database failures return a clear error status, never a stack trace. |

## Optional (Could)

### US-21 Login · Could (✅ planned 2026-11-08, design §7f, U1–U7)
**As a** plant engineer, **I want to** sign in with email and password, **so that** only I see and use my conversations.
Assessment §7: token login, hashed passwords, pre-loaded test users, `Authorization: Bearer <token>` on every request, each user sees only their own conversations. Not required: sign-up, password recovery, OAuth.
- **AC1** `POST /api/auth/login` with valid credentials returns a token. A wrong password and an unknown email give the same 401 `invalid_credentials` (no account enumeration).
- **AC2** Passwords are stored only as argon2id hashes; they are never returned or logged.
- **AC3** At least two test users are created on every start (idempotent, like `ingest load`) and listed in the README.
- **AC4** Every `/api/*` route except login needs a valid token (`/health` stays open). A missing, invalid, expired or logged-out token gives 401 `unauthorized`.
- **AC5** A user lists, reads, continues and debugs only their own conversations. Another user's `session_id` or `message_id` returns 404, as if it did not exist.
- **AC6** A new conversation belongs to the token's user.
- **AC7** App: a login screen is shown when there is no valid token; the token survives app restarts; a 401 returns to the login screen with a "session expired" message.
- **AC8** Logout revokes the token on the server; it no longer works.

- **US-22 Voice:** as a user, I dictate my question instead of typing it (on-device speech recognition).

---

## Traceability

| Story | Verified by |
|---|---|
| US-01, US-03, US-04, US-05 | Lookup tool unit tests (`tests/test_tools_lookup.py`) + evals |
| US-07, US-10, US-11, US-13, US-14, D-1…D-6 | Search tool unit tests (`tests/test_tools_search.py`) + evals |
| US-02, US-09, US-16 | API integration test with a stubbed LLM + evals |
| US-06, US-08, NFR-02, NFR-03, NFR-04 | Evals (`evals/questions.yaml`) |
| NFR-01 | Data validation tests (`tests/test_data.py`) + answer-number check against tool results |
| US-12, US-15, US-17, US-18, US-19 | Manual app check (README checklist) |
| US-20 | Fresh clone test before delivery |
| US-21 AC1–AC6, AC8 | Auth API tests (`tests/test_auth.py`) |
| US-21 AC7 | `mobile/app/src/test/.../data/auth/AuthSessionTest.kt` (token header, 401 → expired, restart, logout) + manual app check with two test users |
