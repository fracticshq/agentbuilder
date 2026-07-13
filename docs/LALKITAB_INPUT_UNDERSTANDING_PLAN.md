# Implementation Plan — Robust Birth-Detail & Question Understanding (Lal Kitab agent)

**Status:** proposed · **Owner:** agentbuilder/api · **Written:** 2026-07-13

## 1. The reported failure, reproduced

User message:

> Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026

Agent reply:

> I understood birth date 1975-01-25, birth time 11:00:00, **birth place Sandeep Amar**. I could not find "Sandeep Amar" on the map yet…

Running both extraction layers against this exact message on current `main`:

| Layer | date | time | place | verdict |
|---|---|---|---|---|
| `lalkitab_runtime.extract_lalkitab_birth_input` | 1975-01-25 ✓ | 11:00:00 ✓ | `None` | missed "New Delhi" |
| `conversation_policy.extract_inputs_for_policy` (planner fallback) | 1975-01-25 ✓ | 11:00:00 ✓ | `"How is my health going to be in"` | extracted the *question* as the place |

And the user's correction turn — "Sandeep Amar is my name, Birth place - Delhi, India" — extracts **nothing** in either layer (dash-separated label `Birth place - …` is unrecognized; the "place-only reply" fallback rejects messages longer than 6 words).

## 2. Root causes, ranked

1. **The user's name is not modeled anywhere.** No `name` field exists in the extraction schema, required-inputs policy, or prompts. A name-first message (the most natural Indian phrasing: "Name, DOB, time, place. Question?") leaves a free-text fragment that both extractors misattribute to `birth_place`.
2. **Two divergent regex extractors.** `conversation_policy._extract_place` and `lalkitab_runtime.extract_lalkitab_birth_input` implement similar-but-different heuristics. Which bug you hit depends on which code path ran — inconsistent, untestable behavior.
3. **The question is never separated from the details.** "How is my health going to be in 2026" leaks into place scrubbing ("2026" also collides with date/time digit patterns), and the extracted question is not used to drive endpoint selection (health + 2026 → `lalkitab_varshphal`).
4. **Anchor gaps in place inference.** Place-after-time inference only anchors on `HH:MM` and `NNNN hrs` forms — not `11 AM`. Labels only accept `:`/`=` separators — not `-` ("Birth place - Delhi").
5. **The LLM planner is a silent single point of failure.** When the `gpt-5.5-low` planner deployment is missing/slow, the code silently falls back to the regex path (`source="deterministic_fallback"`) with no operator visibility. The regex path was only ever meant as a guardrail, but it's likely serving real traffic.
6. **Clarifications echo unvalidated garbage.** "I understood … birth place Sandeep Amar" asserts understanding of a value that geocoding just failed to validate. The reply should never present an unvalidated extraction as understood fact.

## 3. Design principle

**One understanding layer, LLM-first, schema-validated, observable.** Regex stays only as an offline fallback and as *validators* (date/time normalization), never as the primary parser. This matches the earlier direction: no keyword hardcoding to understand the customer.

## 4. Workstreams

### WS1 — Birth-profile extractor service (core fix)

New `app/services/birth_profile_extractor.py`:

- Single async entry point `extract_birth_profile(message, *, prior_profile, llm_provider) -> BirthProfile` with a strict output schema:

  ```json
  {
    "name": "Sandeep Amar",
    "birth_date": "1975-01-25",
    "birth_time": "11:00:00",
    "birth_place": "New Delhi",
    "question": "How is my health going to be in 2026",
    "language": "en",
    "ambiguities": [],
    "confidence": {"birth_date": "high", "birth_place": "high"}
  }
  ```

- Prompted with few-shot examples covering the real failure shapes: name-first, DD/MM vs MM/DD, `11 AM` times, dash/pipe/newline separators, Hinglish, question-embedded, corrections ("X is my name, birth place - Y").
- `ambiguities[]` is the only trigger for clarifying questions (e.g. `03/04/1990` day-month order, city with no country that geocodes to multiple countries). Everything else proceeds.
- Post-validation: dates/times re-normalized by the existing deterministic normalizers; out-of-range or unparseable values are dropped, never guessed.
- Merge semantics with `prior_profile`: new turn only overwrites fields it explicitly provides; corrections ("X is my name") *move* a value between fields (name ↔ place) rather than adding a second place.
- Fallback: if the LLM call fails, use the current regex extractor — but tagged (`source="regex_fallback"`) so it is visible (WS5).

Call sites: replaces the extraction internals of `AgentTurnPlanner` resolved-inputs for lal-kitab agents, and `build_lalkitab_runtime_context` consumes the resulting profile via the existing pending-state bridge. `conversation_policy.extract_inputs_for_policy` and `lalkitab_runtime.extract_lalkitab_birth_input` stop being alternative sources of truth.

### WS2 — Model the name as a first-class field

- Add optional `name` to the astrology policy's `required_inputs` (`required: false`) and to the pending-state / `connector_inputs` persistence so it survives turns.
- Name is **excluded** from geocoding candidates by construction (it has its own slot).
- Use it: kundali artifact header ("Sandeep Amar · 25 Jan 1975 · 11:00 · New Delhi"), astrologer reading addresses the user by name, Strapi conversation metadata.

### WS3 — Question separation & routing

- The extractor's `question` field (details stripped) becomes the input to `select_lalkitab_endpoint_ids` and the reading prompt's "User Query", instead of the raw message.
- Year/timeframe detection: a question referencing a specific year ("in 2026") adds `lalkitab_varshphal`; health terms add the health-relevant endpoints. This mapping stays in the tool-recipe config (admin-editable), not hardcoded keywords in code.
- Details-without-question keeps the current behavior: build + show the chart, invite the question.

### WS4 — Deterministic fallback hardening (small, tested patches)

Only for the offline fallback path, all covered by the WS6 corpus:

- Anchor place-after-time on `\d{1,2}\s*(am|pm)` forms too ("11 AM, New Delhi").
- Accept `-`/`–`/`|` as label separators ("Birth place - Delhi, India", "DOB - 25/01/1975").
- Strip the trailing question clause (sentence starting with what/how/when/will/…?) *before* fragment scrubbing so it can never become a place; never emit a question-like fragment as place (port `lalkitab_runtime`'s guard into `conversation_policy`, which currently lacks it).
- Exclude 4-digit years that belong to the question span from time/scrub collisions.
- Relax `_extract_place_only_reply`'s 6-word cap when the message contains an explicit place label.

### WS5 — Observability & planner reliability

- Emit `planner_source` (`llm` / `deterministic_fallback` + error) and `extractor_source` in activity metadata and `observability_service` events; surface in the Agent Console trace so ops can see when the regex path served a turn.
- Startup/admin check: validate the configured `planner_model` deployment resolves; show a warning chip in Agent Studio when it doesn't (today the override fails silently to the agent model — RUNBOOK behavior).
- Add a counter metric: `extraction_fallback_total` to alert on sustained fallback usage.

### WS6 — Regression corpus & evals (gate for everything above)

- `tests/test_birth_input_corpus.py`: one parametrized table of ~30 real utterances with expected `{name, date, time, place, question}`, run against (a) the deterministic fallback and (b) the LLM extractor with a `FakeLLM`. Must include verbatim:
  - `Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026`
  - `Sandeep Amar is my name, Birth place - Delhi, India`
  - `16 july 1987, 15:26, Delhi India` (already covered)
  - name-first / place-first / Hinglish / `03/04/1990` (ambiguity expected) / newline-separated form-style inputs.
- Live smoke script (manual, uses the real planner model) to score the corpus end-to-end before releases.

### WS7 — Clarification UX correctness

- Never claim "I understood birth place X" for a value that failed geocoding — phrase as: "I have your birth date 25 Jan 1975 and time 11:00 AM. Which city were you born in?"
- If geocoding returns zero results for an extracted place that equals the extracted `name`, silently drop the place instead of asking the user to confirm their own name as a city.
- When a correction turn renames fields, acknowledge it: "Thanks, Sandeep — noted Delhi, India as the birthplace."

## 5. Sequencing & effort

| Phase | Contents | Effort | Risk |
|---|---|---|---|
| 1 | WS6 corpus (failing tests first) + WS4 fallback fixes | ~½ day | low |
| 2 | WS1 extractor service + WS2 name field + WS7 UX | ~1–1.5 days | medium (LLM prompt iteration) |
| 3 | WS3 question routing + WS5 observability | ~½–1 day | low |

Acceptance criteria: the two verbatim failing turns produce a one-shot correct chart (no clarification needed for turn 1; turn 2 resolves Delhi immediately); corpus passes on both extractor paths; Agent Console shows extractor/planner source per turn; zero occurrences of a name or question fragment reaching the geocoder in the corpus.

## 6. Explicit non-goals (this iteration)

Multi-person charts in one message, non-Latin script parsing (Devanagari dates), voice input normalization, and historical timezone edge cases before 1947 — noted for a later pass.
