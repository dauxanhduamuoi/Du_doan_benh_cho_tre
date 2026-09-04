# Auto Medical Knowledge V1 — Groq Runtime Stability

## Status

**PASS_WITH_NOTES**

The observed generic-output regression, deterministic numeric matching, and Groq rate-limit cascade have been addressed without changing discovery, Reviewed Medical Knowledge, Parent ranking, or any medical safety gate. No live provider call was needed.

## 1. `LLM_INVALID_RESPONSE` audit

The visible `169 · humidity` failure is not an unmarked pre-pipeline row. Production job `12`, attempt `1`, contains pipeline marker `auto_medical_knowledge_v1_compat` and a persisted `FAILURE_DETAIL` whose exception class is `DraftGeneratorOutputError`. The same pattern exists in other already-stored attempts.

Root cause: parser/schema/source-set failures already used typed `DraftGeneratorStructuredOutputError`, but the final generic provider-envelope branch still passed through `classify_auto_failure()` as `LLM_INVALID_RESPONSE`. Therefore this was a new-path classification gap, not evidence that JSON/schema validation had failed in a particular way.

Fix:

- Typed parser errors remain exact: `AUTO_OUTPUT_JSON_INVALID`, `AUTO_OUTPUT_SCHEMA_INVALID`, `AUTO_OUTPUT_MISSING_REQUIRED_FIELD`, `AUTO_OUTPUT_INVALID_ENUM`, and `AUTO_OUTPUT_SOURCE_SET_MISMATCH`.
- A new attempt that reaches the genuinely untyped provider-envelope fallback is now stored as `AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID`; it no longer collapses to `LLM_INVALID_RESPONSE`.
- Existing `LLM_INVALID_RESPONSE` rows were not rewritten or guessed. API/UI mark the generic record as historical and explain that the old version lacks enough detail for exact classification.
- Frontend continues to hide raw provider output.

## 2. Exact `5.087` evidence investigation

The production failure is job `11`, attempt `1`, topic `169 · wind`, field `detailed_explanation_vi`. Its attempt marker is `11:1:2026-08-30T05:47:50.010794`.

The exact selected set for that attempt contains one source:

- Source ID `60`, PMID `21672424`, evidence content ID `55`
- Content SHA-256: `0d641fc8b1c547e6466b80df7b07de67067d54c43b379ad4b90896aa32eaa7d2`
- Snapshot text contains the count: “A total of 5087 hospitalized children”.

The literal token `5.087` is absent, while the same digit sequence appears as the ungrouped count `5087`. The previous matcher compared raw numeric tokens, so it produced a formatting false positive for a population count.

The replacement matcher is deterministic and does not rewrite generated prose:

- exact numbers, percent/unit suffixes, safe comma/dot decimal variation, spaces, signs, parentheses, and Unicode-dash ranges are supported;
- grouped integers are normalized when syntax is unambiguous;
- a single separator followed by three digits, such as `5.087`, is not globally treated as `5087`;
- that ambiguous form matches an ungrouped integer only when both evidence and generated text identify a count population (for example children, patients, cases, or admissions);
- standalone `5.087` or `5.087%` against evidence `5087` remains rejected;
- ranges must match ranges, preventing two unrelated endpoints from creating support;
- PMID, DOI, publication year, source ID, and disease-group ID are ignored only in recognizable metadata positions; their digits do not whitelist medical statistics;
- age-bucket context must remain age context.

Historical raw LLM prose was intentionally not stored, so its exact adjacent words cannot be reconstructed. The evidence-side count and stored numeric token establish the old raw-token mismatch; the new rule only permits it when the runtime output supplies the missing count context.

## 3. Safety policy

All existing gates remain enabled and unchanged in purpose:

- causal overclaim guard;
- unsupported mechanism guard;
- pediatric relevance gate;
- personalized/certainty guard;
- source-set and source-design provenance guards;
- unsupported-number guard.

No number or medical claim is deleted or rewritten to make output pass. Ambiguous normalization still fails closed, and semantic failures are not automatically resampled.

## 4. Groq cooldown architecture

Before this change, a 429 only set `next_retry_at` on the current job. The next queued topic could be claimed immediately, producing sequential Groq failures.

The new design adds the additive, idempotent migration `v010_auto_medical_knowledge_provider_cooldown` and table `auto_medical_knowledge_provider_cooldowns`, keyed uniquely by provider. It persists:

- `provider`;
- `cooldown_until`;
- stable `reason`;
- `updated_at`.

Behavior:

- Groq 429 parses standard `Retry-After` seconds or HTTP-date.
- If absent or invalid, `AUTO_MEDICAL_KNOWLEDGE_GROQ_RATE_LIMIT_COOLDOWN_SECONDS` is used (default `300`).
- The cooldown upsert never shortens an already longer cooldown.
- Cooldown is checked before provider construction and again inside the atomic job-claim condition.
- While active, queued jobs stay `QUEUED`; they are not claimed, failed, deleted, or sent to Groq.
- The worker uses its normal poll wait, so there is no blocking sleep or busy loop.
- After expiry, the SQL condition becomes claimable automatically; no backend restart is required.
- The rate-limited job retains normal retry/max-attempt semantics, with retry time no earlier than provider cooldown.
- Parent requests still only enqueue and return. Reviewed/Tier-1 reads never consult the Auto cooldown table.
- Admin overview exposes the persisted provider state, shows the resume time, and disables retry while active.

No minimum request interval was added. The default Auto concurrency is already `1`, and the observed failure mode is handled by the persisted 429 cooldown. With explicitly configured concurrency above one, calls already in flight when the first 429 arrives cannot be cancelled; no new claim can pass after the cooldown transaction commits.

## 5. Deterministic E2E results

| Validation | Result |
|---|---|
| `AUTO_NUMERIC_NORMALIZATION_E2E` | PASS — evidence `5087 hospitalized children`, output `5.087 trẻ em`, revision READY, prose unchanged |
| `AUTO_NUMERIC_HALLUCINATION_GUARD_E2E` | PASS — absent `42%` rejected as `AUTO_OUTPUT_UNSUPPORTED_NUMBER`, no revision |
| `AUTO_GROQ_COOLDOWN_E2E` | PASS — job A 429, job B remains queued, two cooldown polls make zero calls, B processes after expiry |
| `AUTO_LEGACY_ERROR_MAPPING_E2E` | PASS — stored generic remains readable/historical; new generic provider-envelope failure uses a specific code |
| `REVIEWED_DURING_AUTO_COOLDOWN_E2E` | PASS — Reviewed Tier-1 result remains available and no Auto job is created for it |

The restart/session and second-session claim tests confirm DB persistence and that a claim cannot bypass an already-committed cooldown.

## 6. Validation results

- Focused backend: **275 passed, 0 failed**.
- Focused frontend: **129 passed, 0 failed**.
- TypeScript typecheck: **PASS**.
- Frontend production build: **PASS** (one build run).
- Python compile/import: **PASS**.
- FastAPI lifespan and migrations on temporary SQLite: **PASS**.
- HTTP `/` smoke on temporary SQLite: **PASS**.
- Temporary and production `PRAGMA foreign_key_check`: **PASS**.
- Live Groq calls: **0 / NOT_RUN**.
- Live PubMed/PMC calls: **0 / NOT_RUN**.

## 7. Production data integrity

Validation used in-memory or temporary SQLite. It did not run processors against `database.db` and did not write Reviewed or Auto business rows.

Reviewed table counts and logical hashes remained identical from the initial audit through final validation:

- publications: `4`, `66ed60385697dac76e92a9845c4c9151c86485593e920c043d6a1839c0f6a173`;
- revisions: `15`, `4ac114ad32be5fa4f6ad56fe6d01440cf46077d575fac0cea83298580087b48f`;
- revision sources: `31`, `c1ef32230c51537ae140586c9daf5ea1d98b57a6340d3cfb68b051a21c3a1d86`.

No job/history row was deleted. Production foreign-key check returned no rows. The locally running reload server applied the additive v010 schema during development; the cooldown table contains zero production rows. No visibility setting or current pointer was changed by task validation.

A concurrently running local UI/backend changed Auto revision/state timestamps or pointers during the broad initial-to-final window, while job and discovery counts/hashes remained stable. A stable final validation window was therefore used for task attribution; the implementation itself made no production business-data call.

## 8. Files changed for this task

Backend:

- `seasonal_disease_backend/app/services/auto_medical_numeric_validation.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_worker.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/app/repositories/auto_medical_knowledge_repository.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/migrations/v010_auto_medical_knowledge_provider_cooldown.py`
- focused backend tests.

Frontend:

- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- focused frontend tests/fixtures.

## 9. Remaining notes

- Historical raw output remains intentionally unavailable; no reason was fabricated or backfilled.
- Already in-flight provider calls cannot be cancelled after another worker commits a cooldown.
- The Admin panel refreshes persisted status on load/manual refresh; backend resume itself is automatic.

No manual safety or release-blocking smoke is required for this change.
