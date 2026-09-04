# Auto Medical Knowledge V2 — Contract Repair Groq Compatibility

## 1. Status

**PASS** — the exact production attempt was audited read-only, the rejected call was proven to be call 2 (`CONTRACT_REPAIR`), the repair user message was corrected to one provider-compatible bounded JSON envelope, all focused deterministic checks passed, and the single permitted live repair-path request returned HTTP 200 and parsed as the V2 proposal model.

## 2. Exact production attempt

Topic and job:

- topic ID: `19`;
- canonical selector: disease group `169`, `WEATHER / wind`;
- job ID: `11`;
- attempt: `1`;
- attempt key: `11:1:2026-08-31T07:48:28.943891`;
- created: `2026-08-31 07:48:25.665563`;
- started: `2026-08-31 07:48:28.920690`;
- finished: `2026-08-31 07:48:39.490925`;
- final status/code: `FAILED / AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED`;
- provider: `groq`;
- HTTP status: `400`;
- provider stage: `http_request_rejected`;
- pipeline version: `auto_medical_knowledge_v2_numeric_claims`;
- selected source count: `1`, PMID `21672424`;
- published revision pointer: `NULL`.

The persisted failure diagnostic is discovery row `1567` and records:

- `generation_calls=2`;
- `max_generation_calls=2`;
- `contract_repair_attempted=true`;
- `contract_repair_reason=AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`;
- `contract_repair_calls=1`;
- `contract_repair_result=FAILED`.

Therefore:

- `CALL_1_INITIAL=SUCCESS` — it returned a parseable V2 proposal and reached full validation, which raised the typed undeclared-number violation required to trigger repair;
- `CALL_2_REPAIR=FAILED` — Groq rejected this request with HTTP 400.

This conclusion comes from persisted control-flow diagnostics, not inference from the final error name alone.

The current configured provider/model/prompt are `groq`, `openai/gpt-oss-20b`, and `medical_knowledge_auto_v2_numeric_claims`. The historical row persists provider and pipeline version, but did not persist model or prompt version. They are reported as current deployed configuration rather than fabricated historical fields.

## 3. Root cause

The strict V2 schema was not the regression. Initial and repair calls already shared the same Groq adapter, model, strict normalized schema, response format, temperature, disabled citations, timeout, roles, and string content type.

The application-level incompatibility was the old repair message construction:

`normal Auto input JSON + "\n\n" + separate repair JSON`

That produced two independent top-level JSON documents in one user message. Normal V2 sent one document. The second document also carried the previous proposal, making the repair path materially different even though its HTTP field types remained serializable. No Python dictionary or Pydantic object leaked directly into `message.content`; the defect was the ambiguous two-document repair instruction shape.

The corrected path builds one complete JSON envelope:

- canonical topic and selected evidence appear exactly once;
- `task` identifies a complete V2 contract repair;
- one `contract_repair` object contains the safe violation and bounded instructions;
- the previous proposal is deterministic JSON text produced by `model_dump_json()`;
- no original prompt is recursively appended;
- no raw provider envelope/reasoning is included.

The repair input now replaces the normal user input through the provider-neutral generator interface. It is not concatenated to it. The production Groq adapter still constructs one shared Chat Completions payload for both purposes.

The historical Groq `error.code` cannot be recovered because the old adapter intentionally discarded the 4xx response body and persisted no safe category. This report does not guess whether Groq internally labeled that old response `json_validate_failed` or another invalid-request subtype. The request-construction root cause is demonstrated by the exact old code path plus a live HTTP 200 after changing only the repair message contract while retaining the same production schema/adapter/model.

## 4. Schema and payload parity

Deterministic tests build the actual production payload twice and assert:

- same model;
- same `response_format.type=json_schema`;
- same `strict=true`;
- identical normalized V2 schema;
- identical provider parameters outside `messages`;
- roles are exactly `system`, `user`;
- every message content is a string;
- repair content parses as exactly one JSON object;
- evidence is present once;
- previous proposal JSON round-trips to the same V2 object;
- input remains below the configured `60000` character bound.

`GROQ_INITIAL_REPAIR_SCHEMA_PARITY=PASS`

`GROQ_REPAIR_MESSAGE_CONTRACT=PASS`

## 5. Diagnostics added

Future safe failure diagnostics now include, when available:

- `call_purpose`: `INITIAL`, `STRUCTURAL_RETRY`, or `CONTRACT_REPAIR`;
- `generation_call_number`;
- `http_status` and `provider_stage`;
- `response_format_type`;
- `provider_validation_stage`;
- bounded Groq `provider_error_category` and `provider_error_type` identifiers;
- `request_body_bytes`, `user_content_chars`, and `message_count`.

The Groq adapter extracts only short allow-listed error code/type tokens. It does not persist the provider message, raw body, `failed_generation`, headers, API key, prompt, evidence, or previous proposal. Auto orchestration adds call purpose/number because it owns repair semantics; Groq-specific transport remains isolated in the adapter.

The Admin API and focused UI expose stage, call number, HTTP status, provider, and safe error category. The UI localizes `INITIAL` as “Tạo nội dung ban đầu” and `CONTRACT_REPAIR` as “Sửa cấu trúc nội dung”.

## 6. Required E2Es

- `AUTO_GROQ_CONTRACT_REPAIR_PATH_E2E=PASS` — call 1 returns an undeclared `3`; call 2 removes it qualitatively; READY, exactly two calls, identical schema, one final revision only.
- `AUTO_GROQ_REPAIR_DECLARE_CLAIM_E2E=PASS` — evidence explicitly supports `3 groups`; call 2 returns a valid COUNT claim and exact provenance/hash is persisted.
- `AUTO_GROQ_REPAIR_REJECTION_DIAGNOSTICS_E2E=PASS` — simulated HTTP 400 on call 2; final provider-request code, `CONTRACT_REPAIR`, call `2`, safe category, and no revision.
- `AUTO_GROQ_INITIAL_REJECTION_DIAGNOSTICS_E2E=PASS` — simulated HTTP 400 on call 1; `INITIAL`, call `1`, no repair, no revision.
- `AUTO_GROQ_REPAIR_SAFETY_REGRESSION_E2E=PASS` — unsupported causal/mechanism-style output remains a semantic failure after one call and is not repaired.

Numeric Claim V2 regression coverage remains passing for undeclared values, exact source/excerpt verification, `5087 ↔ 5.087`, temporal `2004–2009`, generic `3`, age-context exemption, duplicate/unused declarations, and failed repair provenance.

## 7. Focused validation

- Groq provider, schema normalization, payload parity, serialization, and safe error classification: **58 passed, 0 failed**.
- Auto generation, bounded repair, five E2Es, cooldown, Admin diagnostics, and Numeric Claim V2 smoke/regression: **117 passed, 0 failed**.
- Focused Auto Admin frontend: **34 passed, 0 failed**.
- Python compile: **PASS**.
- `import app.main`: **PASS**.
- Whole-project regression was not run by design.

## 8. Single live Groq repair-path smoke

Exactly one live Groq call was made. It used:

- production `GroqMedicalKnowledgeDraftGenerator`;
- production Auto V2 system instructions;
- production strict normalized `AutoMedicalKnowledgeDraftProposal` schema;
- the fixed production repair input builder;
- a local, non-patient `169 / wind` evidence fixture;
- no database write, PubMed call, or PMC call.

Safe result:

- HTTP: `200`;
- choices: `1`;
- finish reason: `stop`;
- `message.content`: string;
- parsed V2 proposal: yes;
- source assessments: `1`;
- repair input size: `3263` characters.

No generated prose was printed or persisted.

`LIVE_GROQ_REPAIR_REQUEST=PASS`

External calls: Groq `1`, PubMed `0`, PMC `0`.

## 9. Architecture and safety preservation

- `MAX_AUTO_CONTRACT_REPAIR_ATTEMPTS=1` remains unchanged.
- `MAX_AUTO_GENERATION_CALLS=2` remains unchanged and shared with structural retry.
- Repairable codes remain undeclared, unused, and duplicate numeric declarations only.
- Numeric Claim V2 semantics were not modified.
- Causal, mechanism, pediatric, personalized/certainty, evidence-level, exact source-set, exact excerpt, claim-kind, offsets/hash, and trusted-source guards were not weakened.
- Reviewed and Parent workflows were not modified.
- No database migration was added.

## 10. Files changed

- `seasonal_disease_backend/app/services/auto_medical_knowledge_prompt.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/tests/test_groq_medical_knowledge_provider.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- The two report artifacts in this directory.

## 11. Production integrity

Production was queried read-only and job `11` was not retried. Before and after validation:

- max discovery ID: `1567`;
- job `11`: `FAILED`, attempt `1`, same timestamps, no `next_retry_at`, same final error;
- topic `19` published pointer: `NULL`;
- Auto revisions: `20`;
- Auto numeric claims: `0`;
- Reviewed revisions: `15`;
- current Auto pointer, visibility, Reviewed rows, and source rows were not changed.

The stable full medical-business row-set SHA-256 immediately before artifact creation is `ff49ef76889e121cbb17b9e4e5eb432dcdb5d1a3ed919b4f57a24f562de2eebe`; it is verified again after artifact creation in the validation JSON.

## 12. Remaining limitation and manual action

The historical HTTP 400's Groq-specific `error.code` is unavailable because that attempt predates safe category persistence. Future attempts will preserve the bounded code/type without raw provider content. This limitation does not prevent identifying the failed call, application request-shape defect, or validating the corrected live request.

No manual test is required for acceptance. The historical production job remains FAILED and unchanged; an operator may explicitly retry it only after deployment through the normal authorized workflow.
