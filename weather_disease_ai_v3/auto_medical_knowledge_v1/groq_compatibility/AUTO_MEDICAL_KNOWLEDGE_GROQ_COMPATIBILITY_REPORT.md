# AUTO MEDICAL KNOWLEDGE V1 — GROQ COMPATIBILITY VALIDATION

## 1. Status

`PASS_WITH_NOTES`

All deterministic compatibility, safety, history, discovery, Reviewed-precedence, frontend, build, startup, and integrity checks passed. The single permitted live Groq generation was structurally valid but was correctly rejected by the provider-independent safety validator as `AUTO_OUTPUT_UNSUPPORTED_MECHANISM` in `limitations_vi`. Per policy, no semantic re-sampling was attempted.

## 2. Exact root cause

The audit found this exact pre-change flow:

```text
Groq native strict JSON Schema
  -> message.content string
  -> MedicalKnowledgeDraftProposal.model_validate_json(...)
  -> generic DraftGeneratorOutputError on any Pydantic failure
  -> LLM_INVALID_RESPONSE
  -> generic AutoMedicalKnowledgeValidationError for all semantic guards
  -> AUTO_OUTPUT_VALIDATION_FAILED
```

Groq was already using `response_format.type=json_schema`, `strict=true`, temperature `0`, one choice, no tools, and disabled citations. The compatibility defect was not missing provider-native structured output. It was the lack of a bounded shared formatting normalizer and the loss of typed parse/schema/source/safety diagnostics after the response arrived.

The prior Auto schema also required all three explanation fields even for `INSUFFICIENT` and `CONFLICTING`, forcing prose when the safe result should permit `null`. Reviewed continues to use its existing strict proposal model; the nullable escape path exists only in the Auto proposal schema.

The earlier live `AUTO_OUTPUT_VALIDATION_FAILED` cannot be narrowed honestly because raw output and typed diagnostic detail were not stored. No reason was fabricated or backfilled. The new live run proved the current structural path works and identified the actual semantic rejection precisely: unsupported mechanism in `limitations_vi`.

## 3. Historical failure audit

Read-only inspection covered 9 recorded failed attempts: 5 current failed jobs plus 4 preserved `FAILURE_HISTORY` records.

| Proven historical class | Count |
|---|---:|
| Legacy structured-output failure class (`DRAFTGENERATOROUTPUTERROR`) | 6 |
| Legacy generic semantic validation (`AUTO_OUTPUT_VALIDATION_FAILED`) | 2 |
| Provider rate limit (`DRAFTGENERATORRATELIMITERROR`) | 1 |

The six output failures cannot be split reliably between JSON parse and schema validation, and the two semantic failures cannot be split into number/causal/mechanism/pediatric categories. Therefore exact historical detail remains unknown for 8 attempts. Historical rows were neither deleted nor rewritten.

## 4. Structural and semantic architecture

The current flow is:

```text
provider adapter/native schema
  -> deterministic formatting normalization
  -> JSON-object validation
  -> required fields and enum validation
  -> exact selected-source set validation
  -> Pydantic schema validation
  -> provider-independent semantic/safety validation
  -> READY / INSUFFICIENT / FAILED
```

Typed structural exceptions carry only safe machine-readable `code`, `field`, and optional `source_id`. Typed safety exceptions additionally allow a safe numeric token and normalized detail. The Admin audit JSON stores these fields plus the provider error class and pipeline version; it does not store raw model output, prompt text, evidence bodies, stack traces, keys, or hidden provider metadata.

Specific codes now emitted are:

- Structural: `AUTO_OUTPUT_JSON_INVALID`, `AUTO_OUTPUT_SCHEMA_INVALID`, `AUTO_OUTPUT_MISSING_REQUIRED_FIELD`, `AUTO_OUTPUT_INVALID_ENUM`, `AUTO_OUTPUT_SOURCE_SET_MISMATCH`.
- Safety: `AUTO_OUTPUT_UNSUPPORTED_NUMBER`, `AUTO_OUTPUT_CAUSAL_OVERCLAIM`, `AUTO_OUTPUT_UNSUPPORTED_MECHANISM`, `AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID`, `AUTO_OUTPUT_PERSONALIZED_LANGUAGE`, `AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT`, `AUTO_OUTPUT_UNSUPPORTED_SOURCE_CLAIM`.
- Provider transient: `LLM_RATE_LIMITED` and existing provider availability handling.

## 5. Safe normalization

The shared normalizer permits only formatting-level changes:

- surrounding whitespace and BOM removal;
- one surrounding `json` Markdown fence;
- extraction of the only unambiguous top-level JSON object;
- casing/whitespace canonicalization only for already-known enum values.

It rejects multiple JSON objects, additional JSON values, unknown enums, missing fields, duplicate/missing/invented source IDs, and invalid schema shapes. It never rewrites medical prose, removes unsafe sentences, edits numbers, changes evidence level, or invents assessments.

## 6. Prompt and Auto schema

`medical_knowledge_auto_v1` now states explicitly:

- return exactly one JSON object without Markdown or prose around it;
- use exact enum values;
- assess every selected source ID exactly once;
- association language is allowed, causal/certain/personalized wording is not;
- never invent a mechanism;
- every numeric claim must occur in evidence or explicit topic context;
- use structured `INSUFFICIENT`/`CONFLICTING` with nullable explanation fields rather than force unsupported prose.

Groq, OpenAI, and Ollama share the parser and proposal-model injection. Groq-specific strict-schema normalization remains inside its adapter. Reviewed uses the original proposal model and its workflow behavior is unchanged.

## 7. Retry and rate-limit policy

- A structural contract failure may trigger exactly one immediate regeneration with the identical evidence set and a short corrective contract instruction.
- A semantic safety failure never triggers automatic regeneration.
- Provider rate limiting keeps the durable queue backoff and exposes `next_retry_at` to Admin when present.
- Admin retry remains deduplicated per active canonical topic and preserves the failed attempt audit before requeueing.

## 8. Validator audit

### Numeric guard

Unsupported medical numbers still fail closed. PMID, publication year, DOI components, source IDs, disease/report identifiers, factor values, and supplied age-bucket numbers are accepted as metadata/context rather than fabricated statistics. Tests cover PMID/year and existing factor-context handling.

### Causality guard

Genuine causal phrases such as `gây ra`, `làm phát sinh`, and `là nguyên nhân` fail with `AUTO_OUTPUT_CAUSAL_OVERCLAIM`. Association wording such as `có thể liên quan đến` remains valid.

### Mechanism guard

Mechanisms absent from selected evidence fail with `AUTO_OUTPUT_UNSUPPORTED_MECHANISM` and the exact output field. Omitting a mechanism is valid. The live response exercised this guard in `limitations_vi`.

### Pediatric and source guards

Parent eligibility still requires the same source assessment to be both `DIRECT` and `PEDIATRIC_DIRECT`. A pediatric-direct label without pediatric evidence text fails specifically. Unsupported source-design claims (for example, calling a source a randomized trial when its evidence does not say so) also fail specifically.

## 9. Admin current/history UX

The overview now returns persisted `pipeline_version`, `legacy`, `is_current_attempt`, safe failure detail, and attempt history. The Admin panel:

- groups jobs by canonical topic;
- makes the latest attempt primary;
- keeps older attempts collapsed;
- labels pre-diagnostic history without inventing a reason;
- ensures an old failure does not dominate a newer READY result;
- offers current/error/insufficient/ready filters and an explicit legacy-history toggle;
- distinguishes structural retry from semantic regeneration;
- shows a safe expandable validator detail without raw output or evidence;
- shows a clear rate-limit message and retry time;
- prevents duplicate clicks while an action is pending.

## 10. Deterministic E2E results

| E2E | Result |
|---|---|
| `AUTO_STRUCTURAL_NORMALIZATION_E2E` | PASS |
| `AUTO_STRUCTURAL_RETRY_E2E` | PASS; exactly two provider calls |
| `AUTO_SAFETY_REJECTION_E2E` | PASS; exact code, zero revision, one call |
| `AUTO_LEGACY_HISTORY_E2E` | PASS; prior failed attempt remains after current READY |
| `REVIEWED_PRECEDENCE_REGRESSION_E2E` | PASS |

## 11. Live Groq validation

The live validation used the required `seasonal_backend` Python, a temporary SQLite database, production PubMed/PMC discovery, the production Auto prompt, Groq adapter, shared structural parser, safety validator, and persistence service.

| Item | Result |
|---|---|
| Topic | `169 Pneumonia + temperature` |
| Live Groq calls | 1 |
| PubMed queries/results | 1 / 15 |
| Disease/factor/pediatric/usable | 7 / 4 / 4 / 4 |
| Selected for generation | 4 |
| Structural processing | PASS |
| Final job | FAILED, `AUTO_OUTPUT_UNSUPPORTED_MECHANISM` |
| Safe field detail | `limitations_vi` |
| Automatic semantic retry | No |
| Revision persisted | No |
| Production visibility changed | No |
| Temporary DB FK check | PASS |

`LIVE_GROQ_AUTO_GENERATION=FAIL` because READY was not produced. Under the task's status policy this is `PASS_WITH_NOTES`: deterministic code and E2Es pass, and the only live failure is a demonstrably correct semantic safety rejection. A second live sample was intentionally not used.

## 12. Tests, build, startup, and integrity

- Focused backend plus discovery and Reviewed regression: **290 passed, 0 failed**.
- Focused frontend Auto/Parent integration: **34 passed, 0 failed**.
- TypeScript typecheck: PASS.
- Production frontend build: PASS, run once.
- `import app.main`: PASS.
- Normal FastAPI lifespan/startup: PASS.
- HTTP root smoke: `200`; no `/health` route exists (`404`).
- Production and temporary SQLite foreign-key checks: PASS.
- `git diff --check`: PASS; only existing line-ending warnings were reported.

The before/after production logical hashes remained identical for all relevant tables:

- Reviewed publications: `218644e27ffa25f3cba9015b725c291035d8c0b87c93f68d1c625a97271c7cc2`
- Reviewed revisions: `a631b6198ae6f6fe85821e0ccb1a438c8dacea4ae3ce0cff7276fa4840c0bd7e`
- Reviewed revision sources: `6afc60d7991e94fb552f191215bda08556be03e2fc929772f1b5d13cbc14750d`
- Auto topic state/current pointers: `3c016314c80c609503d90fd7fc2bbc5c5b21690fb8ab6b033d950e8785731fbc`
- Auto revisions/visibility: `306bde639e506626d3051d000d41258c83b31f651d32e35a643c06980a80933a`
- Auto revision sources: `20c5ccda4982742c06bf7fe1a6c7c16c4776c0ed465d6c1ca80801621393926f`
- Historical jobs: `2b179702ad4c560094599ec1fb17ac469183b360a61ac22688411d824ab90d23`

No Reviewed data, publication pointer, Auto current pointer, Auto visibility, or historical job was changed or deleted.

## 13. Files changed for this task

- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_prompt.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_worker.py`
- `seasonal_disease_backend/tests/test_groq_medical_knowledge_provider.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- The two report artifacts in this directory.

## 14. Remaining limitations and manual check

The only evidence gap is historical: eight old failures do not contain enough safe metadata for a narrower category. The only live note is that the one response chose unsupported mechanism language and was correctly blocked, so no live READY revision exists from this validation.

A short Admin manual smoke is recommended: open Auto Medical Knowledge, confirm the latest result is primary, expand an old legacy attempt, exercise the status filters, and inspect a safe validator-detail panel. If another live generation is intentionally requested later, use a new isolated run; do not repeatedly sample the same semantic rejection.
