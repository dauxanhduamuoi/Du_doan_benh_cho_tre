# Auto Medical Knowledge — Groq V2 Response Compatibility

## 1. Status

`PASS_WITH_NOTES`

Groq V2 compatibility is fixed and validated. All deterministic checks passed, all five required E2Es passed, and the single permitted live Groq call returned HTTP 200 with a V2 object that the production adapter and internal Pydantic proposal model parsed successfully. No PubMed or PMC call was made.

The note is operational: the already-running Uvicorn/WatchFiles development server reloaded after backend source edits and ran its idempotent startup path. This changed the byte-level hash of the open SQLite file even though the audited Auto topic/job/pointers, global Auto maxima, and Reviewed rows remained unchanged. No production job was retried and no production business row was intentionally written by this validation.

## 2. Exact failed production attempt

Production DB was queried through SQLite `mode=ro`.

| Field | Audited value |
|---|---|
| Canonical topic | DB topic `19`; disease group `169`; `WEATHER · wind` |
| Job ID | `11` |
| Job status | `FAILED` |
| Attempt | `1` |
| Attempt key | `11:1:2026-08-31T05:36:12.562366` |
| Attempt timestamp | `2026-08-31 05:36:12.562366` |
| Finished timestamp | `2026-08-31 05:36:17.921430` |
| Failure code | `AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID` |
| Pipeline version | `auto_medical_knowledge_v2_numeric_claims` |
| Prompt version | `medical_knowledge_auto_v2_numeric_claims` |
| Provider | `groq` |
| Model | `openai/gpt-oss-20b` |
| Discovery | 3 queries; 18 raw; 6 deduplicated; 1 factor-relevant; 1 pediatric-relevant; 1 usable; 1 selected |
| Selected source count | `1` |
| Persisted provider error class | `DraftGeneratorOutputError` |
| Persisted safe detail | `The pipeline rejected this output safely.` |

The attempt marker persists the pipeline version but the failed job has no revision on which to persist prompt/model data. Prompt, provider, and model above are the exact worker configuration loaded from the current production code/config path; their secret values were not printed. The old safe failure record did not preserve HTTP status or response shape.

## 3. Root cause and exact failure stage

The failure occurred at the Groq request/schema boundary, before completion parsing:

`Auto V2 internal model → old Groq strict transport schema → Groq HTTP 4xx request rejection → old _post() generic DraftGeneratorOutputError → AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID`

Numeric Claim V2 added the nested `AutoNumericClaimProposal`. In the old payload, `unit` appeared in that object's `properties` as `string | null`, but was absent from the nested object's `required` array and carried a Pydantic `default: null`. Groq strict mode requires every property at every object level to be required; nullable values must remain required keys whose value may be `null`. The request was therefore not a valid Groq strict schema.

The old adapter collapsed every otherwise-unhandled HTTP 4xx into `DraftGeneratorOutputError`, discarding status/stage metadata. That explains the persisted generic code. This was not a numeric validator failure and not a JSON parser failure.

For the failed attempt:

- usable completion content existed: **NO** — the request failed before a completion envelope;
- medical JSON existed: **NO**;
- `choices`, `message`, and `message.content` were available to the parser: **NO**;
- provider response stage: **strict JSON-schema request rejection (HTTP 4xx branch)**;
- exact old numeric HTTP status: **not persisted by the old adapter**.

The current Groq documentation lists `openai/gpt-oss-20b` as supporting `json_schema` with `strict: true`, and requires all fields plus `additionalProperties: false`: [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs), [GPT-OSS 20B on Groq](https://console.groq.com/docs/model/openai/gpt-oss-20b).

## 4. Compatibility fix

The fix stays in the provider boundary:

1. Groq transport-schema normalization now visits every object, makes every property required, and enforces `additionalProperties: false`.
2. Nullable internal fields keep their `anyOf: [string, null]` representation; Groq must emit the key, while the internal model still represents it as optional.
3. Pydantic-only defaults/constraints are removed only from the transport schema and remain enforced by the unchanged internal proposal model after parsing.
4. `$defs`/`$ref`, nested arrays, enums, `source_assessments`, and `numeric_claims` remain intact.
5. Core `AutoMedicalKnowledgeDraftProposal`, prompt V2, pipeline V2, and the numeric validator were not changed.

Architecture remains:

`Groq strict transport schema → deterministic envelope extraction → existing JSON/parser normalization → internal Auto proposal → Numeric Claim Contract V2 → semantic safety`

No alternate model, provider fallback, migration, or safety relaxation was added.

## 5. Provider envelope and typed classification

The Groq adapter now has one deterministic extraction path. It validates:

- HTTP success versus request rejection;
- `choices` presence and exactly one choice;
- `message` presence;
- documented `finish_reason` presence;
- non-success `length`, `tool_calls`, or `function_call` completion;
- null/empty/whitespace content;
- unsupported content type;
- usable text content before handing it to the existing parser.

New stable codes:

| Code | Meaning | Structural retry |
|---|---|---|
| `AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED` | Groq rejected the structured-output request at HTTP 4xx | No |
| `AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY` | HTTP success/stop but content is null or blank | No |
| `AUTO_OUTPUT_PROVIDER_INCOMPLETE` | Non-success finish reason or tool/function path | No |
| `AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID` | Malformed provider envelope: choices/message/content type/finish metadata | No |

Content that exists but is invalid JSON remains `AUTO_OUTPUT_JSON_INVALID`. Valid JSON with an invalid model shape remains a schema/missing-field/enum/source-set code. Those `DraftGeneratorStructuredOutputError` cases retain the existing maximum of one structural retry. Rate limit and semantic/numeric/causal/mechanism failures remain non-structural and were not changed.

The current Groq Chat Completions response contract documents `content`, `reasoning`, role, tool fields, and finish reasons but not a dedicated `refusal` field. No speculative refusal code was invented. Tool/function/non-stop paths are classified as incomplete.

## 6. Safe diagnostics

Provider errors now carry and persist only allow-listed metadata through existing `FAILURE_DETAIL` storage:

- provider;
- HTTP status;
- provider stage;
- finish reason;
- choices count;
- message/content presence;
- content length;
- incomplete/refusal indicator;
- detected structured field;
- provider exception class.

Raw response, medical prose, prompt, evidence, headers, API key, and stack trace are not persisted.

## 7. Deterministic and focused validation

Final focused results:

- Groq adapter/schema/parser tests: **55 passed**;
- Auto V2 generation, retry, numeric/count/year-range regression selection: **42 passed, 58 deselected**;
- focused backend total: **97 passed, 0 failed**;
- Auto panel localized provider-code tests: **33 passed, 0 failed**;
- Python compile/import (`import app.main`): **PASS**;
- `git diff --check`: **PASS** (line-ending notices only).

Required E2Es:

| E2E | Result | Observed classification/result |
|---|---|---|
| `AUTO_GROQ_V2_ENVELOPE_E2E` | PASS | production Groq adapter mock → V2 parser → Numeric contract → READY |
| `AUTO_GROQ_EMPTY_CONTENT_E2E` | PASS | FAILED; `AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY`; no revision; 1 call |
| `AUTO_GROQ_INVALID_JSON_CLASSIFICATION_E2E` | PASS | `AUTO_OUTPUT_JSON_INVALID`, not provider-response-invalid; exactly 1 structural retry |
| `AUTO_GROQ_V2_NUMERIC_CONTRACT_E2E` | PASS | supported `5087`/`5.087` claim → READY with persisted offsets/hash |
| `AUTO_GROQ_PROVIDER_VS_SAFETY_E2E` | PASS | valid envelope/schema then `AUTO_OUTPUT_CAUSAL_OVERCLAIM`; no revision; no retry |

Numeric regression also preserved `2004–2009`, generic `3`, exact selected-source matching, declaration usage, support excerpt verification, and Parent internal-claim hiding. `auto_medical_numeric_validation.py` was not edited.

## 8. Single live Groq validation

Calls:

- Groq: **1**;
- PubMed: **0**;
- PMC: **0**.

The call used the production Groq adapter, real Auto V2 prompt builder, real V2 proposal model, a local non-patient evidence fixture for `169 · Pneumonia · wind`, and an isolated temporary SQLite DB that was removed after validation.

Sanitized real response shape:

```json
{
  "status": 200,
  "choices_count": 1,
  "message_keys": ["content", "reasoning", "role"],
  "content_type": "str",
  "content_length": 845,
  "finish_reason": "stop"
}
```

Result: one source assessment, zero numeric claims, and a valid `AutoMedicalKnowledgeDraftProposal`. No generated prose was printed or stored in the report. This proves the fixed transport schema is accepted and the adapter understands the real Groq envelope.

## 9. Production integrity

- production job `11` was not retried;
- job remained `FAILED`, attempt `1`, with the original error/timestamps;
- topic `19` remained unpublished with no Auto current revision and no Auto revision;
- topic request count/pointers remained unchanged;
- global latest discovery stayed ID `1517`, job max ID `27`, Auto revision max ID `20`;
- Reviewed revision count remained `15`, latest ID `15`;
- Auto visibility and Reviewed content were not modified;
- no migration was added;
- no production business-data change was detected.

Raw file SHA-256 was not stable across the task because the database was already open by Uvicorn/WatchFiles and source edits triggered its startup/reload path. The file length stayed `188575744` bytes; three consecutive final shared-read hashes then stabilized. This operational byte-level churn is why the overall status is `PASS_WITH_NOTES`, while logical business integrity is PASS.

## 10. Files changed

- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py` (diagnostics response only; core proposal unchanged)
- `seasonal_disease_backend/tests/test_groq_medical_knowledge_provider.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- this report and its validation JSON.

## 11. Remaining limitations and manual test

The historical job cannot retroactively reveal the exact old HTTP status because the old adapter intentionally persisted only a generic safe exception class. New attempts will retain safe status/stage metadata.

A single user-initiated manual retry of production `169 · wind` is still required because this task explicitly prohibited retrying that production job. Expected compatibility outcome: it must no longer end as generic `AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID`; READY, INSUFFICIENT, or a later precise semantic safety code are all valid downstream outcomes.

