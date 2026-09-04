# AUTO MEDICAL KNOWLEDGE — DETERMINISTIC SAFE FALLBACK V1

## 1. STATUS

**PASS**

Auto Medical Knowledge now produces a deterministic, conservative Vietnamese `SAFE_FALLBACK` revision when—and only when—a structurally valid first proposal has already established a validated evidence/safety snapshot and the remaining repair failure is on the explicit mechanical/provider allow-list. No external call was made during implementation or validation.

## 2. Previous failure behavior

The previous orchestration propagated a second-call contract/provider exception to the worker. The worker marked the job `FAILED`, even when call 1 had passed the independent semantic, provenance, pediatric, disease and factor gates and failed only Numeric Claim Contract mechanics.

Read-only production audit confirmed topic `19` (`169 · WEATHER · wind`) remains unchanged: job `11` is `FAILED`, attempt count `1`, last error `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`, `current_revision_id=NULL`, and `published_revision_id=NULL`. It was not retried.

## 3. Safe Fallback architecture

The feature is centralized in `auto_medical_knowledge_safe_fallback.py`:

- `evaluate_safe_fallback_eligibility(...)` owns the fail-closed evidence policy.
- `SafeFallbackEligibilitySnapshot` stores only canonical topic fields, allowed evidence level/scope, validated source/content IDs, trust class, relevance and population classifications.
- Failed AI explanation text and assessment notes are not copied into the snapshot.
- `is_safe_fallback_trigger(...)` owns the stage-aware allow-list.
- `AutoSafeFallbackRenderer` creates the Vietnamese explanation locally and deterministically.
- The rendered proposal is run through the normal provider-independent validation again before persistence.

The generation-call budget is unchanged: normal AI uses one call; contract repair uses at most two calls; fallback adds no call.

## 4. Exact fallback eligibility rules

All conditions are required:

1. The initial provider call returned an `AutoMedicalKnowledgeDraftProposal` with an exact, unique selected-source assessment set.
2. Full semantic validation reached Numeric Claim Contract V2 and the only observed initial failure was `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`, `AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED`, or `AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE`.
3. Canonical disease and factor normalization succeeds.
4. Evidence level is Parent-displayable under the existing code-truth policy: `SUPPORTED` or `LIMITED_OR_INDIRECT`.
5. The source set is non-empty and unique; source ID, evidence-content ownership, Draft input ID and selected assessment ID match exactly.
6. Every selected source is `PUBMED` or `PMC`, has usable evidence text, and passed deterministic disease and factor relevance signals.
7. Pediatric discovery relevance exists.
8. At least one source is both `DIRECT` and `PEDIATRIC_DIRECT`, using the existing Parent-safe rule.
9. No `INSUFFICIENT`, `CONFLICTING`, trusted-source, provenance, evidence-set, or medical semantic failure has been observed.

## 5. Failures that may trigger fallback

After a valid snapshot exists, repair-stage fallback is allowed for:

- `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`
- `AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED`
- `AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE`
- `AUTO_OUTPUT_PROVIDER_REQUEST_REJECTED`
- `AUTO_OUTPUT_PROVIDER_CONTENT_EMPTY`
- `AUTO_OUTPUT_PROVIDER_INCOMPLETE`
- `AUTO_OUTPUT_PROVIDER_RESPONSE_INVALID`
- `AUTO_OUTPUT_JSON_INVALID`
- `AUTO_OUTPUT_SCHEMA_INVALID`

If a structurally retried valid proposal consumes call 2 and has only an allow-listed numeric-contract error, fallback may run locally instead of attempting call 3.

## 6. Failures that can never fallback

Initial provider/JSON/schema failure cannot fallback because no validated snapshot exists. The allow-list excludes causal overclaim, unsupported mechanism/source claims, invalid pediatric claims, personalized language, inconsistent evidence level, source-set/provenance mismatch, untrusted sources, and Numeric Claim source/kind/evidence mismatch. `INSUFFICIENT` and `CONFLICTING` never fallback. Repair rate limiting and generic provider unavailability remain fail-closed because they are not in the conservative V1 allow-list.

If repair produces any semantic/evidence safety failure after a snapshot was established, the snapshot is not used.

## 7. Snapshot creation

The snapshot is created in memory immediately after call 1 fails an allow-listed numeric-contract mechanic. It is constructed only after the earlier semantic checks have completed and then independently rechecks canonical topic, evidence status, exact provenance, discovery relevance, trust and pediatric-direct support. It contains no failed short/detail/limitations prose and no LLM assessment notes.

## 8. Deterministic template design

The fallback contains:

- a short association-only statement;
- a group-level explanation that explicitly avoids individual diagnosis;
- a limitation stating that association does not prove causality and that the content is an automatic shortened explanation.

It contains no biological mechanism, recommendation, diagnosis, effect size, sample size, percentage, study period or other medical evidence statistic. `numeric_claims=[]`. Failed AI prose is discarded rather than edited, truncated or regex-cleaned.

## 9. Factor formatter

The formatter reuses canonical factor normalization and `FACTOR_LABELS_VI`. It produces deterministic phrases for all supported types:

- WEATHER: canonical label such as `nhiệt độ`, `độ ẩm`, `mưa / lượng mưa`, or `gió`;
- AGE: `nhóm tuổi {canonical factor_value}`;
- SEX: `giới tính {canonical factor_value}`;
- SEASONALITY: `thời điểm trong năm`.

Canonical AGE numbers are the only possible numeric context in fallback V1.

## 10. Generation mode persistence

Additive migration `v012_auto_safe_fallback.py` adds nullable `generation_mode` and `fallback_reason_code` columns. Successful new revisions persist `AI_FULL` or `SAFE_FALLBACK`; insufficient revisions use null. A historical READY row with null mode is read safely as legacy `AI_FULL`. No historical row is rewritten.

## 11. Fallback reason persistence

Only one bounded code is stored:

- `CONTRACT_REPAIR_EXHAUSTED`
- `REPAIR_PROVIDER_FAILURE`
- `REPAIR_STRUCTURAL_FAILURE`

Raw provider objects, failed output and failed AI prose are not stored or sent to Parent.

## 12. Parent behavior

Parent receives normal `knowledge_type=AUTO`, exact safe citations, `generation_mode=SAFE_FALLBACK`, the existing unreviewed warning, and the additional non-technical message: `Nội dung tự động rút gọn từ các nguồn y khoa đã tìm được.` The UI shows `Giải thích tự động rút gọn`. Internal failure codes, repair details, numeric-claim internals and failed AI content are absent.

## 13. Admin behavior

The Auto revision card shows `AI đầy đủ` or `Bản rút gọn an toàn`. For fallback it explains that the full output did not pass the output contract and that a shortened explanation was built from eligible evidence. The technical fallback reason is retained in the admin API for auditability but is not rendered as raw code.

## 14. Reviewed precedence

Resolution remains unchanged: eligible Reviewed publication wins over visible Auto content, including `SAFE_FALLBACK`. The E2E also confirms that withdrawing Reviewed restores the existing eligible Safe Fallback when the configured display policy permits Auto.

## 15. Source provenance

Fallback persistence uses the exact selected sources and evidence-content rows from the validated snapshot. Normal immutable revision-source links, source roles, population relevance, safe citations and retrieval timestamps are preserved. No source is fabricated or added.

## 16. Numeric behavior

Numeric Claim Contract V2 is unchanged. Full AI output still requires declaration, exact excerpt/source validation, safe normalization and compact provenance. Safe Fallback V1 always persists zero numeric claims and never copies a failed statistic. Existing `5087 ↔ 5.087`, `2004–2009`, generic numeric, claim-kind, source and evidence-mismatch regressions passed.

## 17. Provider call maximum

- AI_FULL valid initially: 1
- AI_FULL after repair: 2
- SAFE_FALLBACK: at most 2
- No call 3
- No fallback PubMed/PMC rediscovery

## 18. Files changed

- `seasonal_disease_backend/app/services/auto_medical_knowledge_safe_fallback.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/published_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/services/published_medical_knowledge_read_service.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/migrations/v012_auto_safe_fallback.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/lib/api.ts`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- `Frontend/src/app/components/weather-ai/WeatherAIResults.tsx`
- `Frontend/src/app/components/weather-ai/publishedMedicalKnowledge.test.tsx`

## 19. Migration

An additive migration was necessary because mode/reason must remain auditable independently of mutable diagnostics. It is idempotent, adds nullable columns only, and does not alter Reviewed data, old Auto content, pointers, visibility or source links. Migration, temp startup/lifespan, root HTTP smoke and `PRAGMA foreign_key_check` passed. Production migration was intentionally not run during this read-only audit.

## 20. Backend tests

Focused suites: **294 passed, 0 failed**.

Covered Auto generation/repair, fallback policy and renderer, Numeric Claim V2, Groq boundary behavior, public Parent read, source library/provenance, general factors, Reviewed unpublish/precedence, temp migration/startup and foreign keys. Two pre-existing Pydantic deprecation warnings were emitted; they are unrelated to this change.

## 21. Frontend tests

Focused suites: **47 passed, 0 failed** across Auto Admin, Parent published Medical Knowledge and public response handling. TypeScript typecheck passed.

## 22. E2Es

- `AUTO_SAFE_FALLBACK_CONTRACT_E2E=PASS`
- `AUTO_SAFE_FALLBACK_PROVIDER_E2E=PASS`
- `AUTO_SAFE_FALLBACK_SEMANTIC_GUARD_E2E=PASS`
- `AUTO_SAFE_FALLBACK_INSUFFICIENT_E2E=PASS`
- `REVIEWED_OVER_SAFE_FALLBACK_E2E=PASS`
- `PARENT_SAFE_FALLBACK_E2E=PASS`
- Reviewed unpublish restores eligible Safe Fallback: `PASS`

## 23. Safety regressions

PASS: Numeric Claim Contract V2, exact excerpt/source validation, locale/year-range normalization, generic numeric handling, causal guard, mechanism guard, pediatric gate, personalized language, evidence-level consistency, trusted sources and Reviewed precedence.

## 24. External calls

- Groq: 0
- PubMed: 0
- PMC: 0

## 25. Production integrity

Production audit was read-only. Stable Medical/Auto business-table hash before and after validation:

`f526dcf09a8b1113d41e8fc8fc83bddc1c0559988c816d4ef00d0dea933288c0`

No production job was retried. No production Auto revision, visibility, current pointer, Reviewed revision/publication, source library row or business record was modified.

## 26. Remaining limitations

- V1 is intentionally qualitative and cannot reproduce the richness of a fully valid AI explanation.
- It requires a structurally valid initial proposal and an approved numeric-contract-only initial failure; initial provider/structural failures remain `FAILED`.
- Repair rate limiting and generic provider unavailability remain fail-closed in V1.
- Existing failed production jobs are not retroactively converted; a future explicitly authorized retry after deployment would use the new policy.

## 27. Manual test required

**NO.** Deterministic focused validation is complete. A normal deployment smoke may still be performed operationally, but no user action or external-quota validation is required for this task.
