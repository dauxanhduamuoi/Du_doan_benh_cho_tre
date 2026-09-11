# AUTO MEDICAL KNOWLEDGE — MULTI-TIER GENERATION V2

## 1. Status

PASS. The deterministic implementation and focused validation suite satisfy the requested multi-tier architecture without live provider or production-data mutations.

## 2. Git branch and commit audited

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting commit: `b72a9594fd265d67b988ae3b03ec316c1e2061bb`
- Working tree was clean before this task.

## 3. Existing Auto architecture discovered

The existing pipeline already separated Auto revisions from Reviewed revisions and provided bounded PubMed discovery, evidence persistence, Numeric Claim Contract V2, semantic safety validation, one Strict repair, deterministic Safe Fallback, durable jobs/cooldown, admin diagnostics, publication precedence, and Parent-safe reads. The implementation extends those boundaries instead of replacing them.

## 4. Shared evidence qualification design

`auto_evidence_qualification.py` adds one provider-independent gate after discovery persistence and before any generation call. It validates the canonical disease/factor, trusted PubMed/PMC class, disease and factor relevance, pediatric support, non-empty evidence text, unique source/content IDs, and exact source/content/input ownership. Its immutable snapshot is the only qualification basis shared by Strict, Basic, and Safe Template; no generated prose contributes to qualification.

## 5. Strict tier behavior

Strict retains the existing V2 proposal, Numeric Claim Contract V2, exact excerpt/source validation, numeric-kind checks, pediatric policy, causal/mechanism/personalization guards, provider abstraction, structural retry, and bounded contract repair. Successful Strict revisions persist as `STRICT / AI`.

## 6. Basic tier behavior

After qualified evidence, an unsuccessful Strict output/provider path may make one fresh Basic call using the same selected evidence. Basic never receives or reuses failed Strict prose. A valid supported response persists as `BASIC / AI`; a valid `INSUFFICIENT` response persists as an insufficient terminal revision.

## 7. Basic output schema

The provider contract contains only:

```json
{
  "result": "SUPPORTED|INSUFFICIENT",
  "summary_vi": "string|null",
  "source_ids": []
}
```

Extra fields are forbidden. Supported output requires a summary and at least one unique positive source ID; insufficient output requires both to be empty.

## 8. Basic prompt

The dedicated Basic prompt requests at most two or three short Vietnamese sentences, qualitative association wording only, exact supplied source IDs, and an insufficient result when evidence cannot support a cautious statement. It explicitly prohibits numbers, statistics, dates, ratios, measurements, mechanisms, causation, diagnosis, treatment, personalized advice, browsing, and invented evidence.

## 9. Basic validation

The bounded validator checks schema/type, result path, summary length and sentence count, absence of Arabic digits/statistical tokens, absence of causal/mechanism/diagnostic/treatment/personalized phrases, source-ID subset membership, and retained pediatric provenance. It does not reuse the Strict numeric-claim contract.

## 10. Safe Template reuse

The existing deterministic renderer remains the zero-provider-call stability floor and is classified as `BASIC / SAFE_TEMPLATE`. Its Parent-facing limitation is now generic and does not reveal internal downgrade or provider details.

## 11. Exact downgrade policy

The order is evidence qualification → Strict initial/optional bounded Strict repair → one Basic attempt → deterministic Safe Template if Basic output/provider validation fails. Failed Strict prose is discarded. Turning off the persisted Basic fallback setting restores fail-closed behavior after Strict failure.

## 12. Evidence failures that stop generation

Missing/invalid canonical disease or factor, no usable evidence, untrusted source class, absent disease relevance, absent factor relevance, absent pediatric evidence, provenance/ownership mismatch, and conflicting evidence terminate as `INSUFFICIENT` with zero Strict, Basic, or Safe Template generation.

## 13. Strict output failures that may downgrade

After evidence qualification, provider-response/configuration failures, exhausted structural/schema failures, numeric-contract failures, and semantic output failures can downgrade. A Strict rate limit is excluded from immediate downgrade and follows cooldown/retry handling.

## 14. Provider call maximum

- Strict: maximum 2 calls total, including structural retry or contract repair.
- Basic: maximum 1 call with no repair loop.
- Job total: hard maximum 3 calls.
- Safe Template: 0 calls.

## 15. Rate-limit behavior

A Strict rate limit propagates immediately and never triggers Basic in the same attempt. A Basic rate limit persists the durable provider cooldown and propagates until the final allowed job attempt; on that final attempt only, the qualified deterministic Safe Template may complete the job while the cooldown remains persisted. Workers continue to respect active cooldown before provider construction.

## 16. Data-model changes

Auto revisions add nullable `auto_tier`, `generation_method`, `strict_failure_code`, and `strict_failure_stage`. Settings add non-null `basic_fallback_enabled`. Fresh schemas constrain tier/method/settings values. Admin schemas and diagnostics expose tier/method and safe Strict/Basic orchestration metadata; Parent schemas do not expose generation method or Strict failure fields.

## 17. Legacy AI_FULL mapping

Legacy ready `AI_FULL` revisions map at read time to `STRICT / AI`; their medical prose is unchanged.

## 18. Legacy SAFE_FALLBACK mapping

Legacy ready `SAFE_FALLBACK` revisions map at read time to `BASIC / SAFE_TEMPLATE`; their medical prose is unchanged.

## 19. Current revision priority

The centralized pointer policy is `READY STRICT` > `READY BASIC` > `INSUFFICIENT`. A newer lower-tier revision cannot replace an existing higher-tier current revision; a newer same-tier revision may replace it.

## 20. Parent priority

Existing Reviewed-first publication selection remains unchanged. Auto is considered only under the persisted fallback display mode, and within Auto the current revision policy prefers Strict over Basic.

## 21. Admin labels and settings

Admin displays and filters `Kiểm tra nâng cao`, `Giải thích cơ bản`, and `Không đủ bằng chứng`, while also showing `AI` versus `Bản rút gọn an toàn`. The persisted runtime checkbox is `Cho phép Giải thích cơ bản khi Kiểm tra nâng cao không hoàn thành`. It defaults to true because the prior architecture implicitly enabled deterministic fallback; this is the least-surprising compatible migration default and remains changeable without restart.

## 22. Parent labels and warnings

- Reviewed: `Đã kiểm duyệt y khoa`
- Strict: `Tự động – Kiểm tra nâng cao`
- Basic: `Tự động – Giải thích cơ bản`

Strict and Basic retain distinct plain-language unreviewed warnings. Parent receives explanation fields, bibliographic citations, tier label metadata, and warning metadata only; it receives no legacy generation mode, generation method, Strict failure reason, provider detail, diagnostics, numeric-claim records, or internal fallback subtype.

## 23. Files changed

- Backend models/schemas/startup: `medical_knowledge_models.py`, `auto_medical_knowledge_schemas.py`, `published_medical_knowledge_schemas.py`, `main.py`
- Backend pipeline: `auto_evidence_qualification.py`, `auto_medical_knowledge_basic.py`, `auto_medical_knowledge_prompt.py`, `auto_medical_knowledge_service.py`, `auto_medical_knowledge_safe_fallback.py`, `auto_medical_knowledge_worker.py`, `medical_knowledge_draft_generator.py`, `published_medical_knowledge_read_service.py`
- Repository/migration: `auto_medical_knowledge_repository.py`, `v013_auto_multi_tier_generation.py`
- Frontend: `medicalKnowledgeApi.ts`, `api.ts`, `AutoMedicalKnowledgePanel.tsx`, `WeatherAIResults.tsx`
- Tests: `test_auto_medical_knowledge.py`, `AutoMedicalKnowledgePanel.test.tsx`, `publishedMedicalKnowledge.test.tsx`
- Reports: this file and `auto_medical_knowledge_multi_tier_v2_validation.json`

## 24. Migration

Migration V013 is additive and idempotent. A temporary SQLite test runs it twice, verifies legacy content and nullable metadata remain unchanged, checks the new setting, and passes `PRAGMA foreign_key_check`. Startup lifespan applies V013 and serves the root endpoint successfully. No Reviewed, publication, visibility, pointer, or historical prose rewrite occurs.

## 25. Backend tests

`165 passed` in the focused Auto suite. The combined Auto, Parent-publication, Groq adapter, and Ollama adapter selection passed `264` tests after the final changes. Tests use deterministic fakes/transports only.

## 26. Frontend tests

Three focused files passed: `79 passed`, `0 failed`. TypeScript typecheck passed, and the production Vite build passed.

## 27. E2E results

- Strict: PASS
- Basic AI: PASS
- Basic Safe Template: PASS
- Insufficient with zero generation calls: PASS
- Strict-over-Basic current priority: PASS
- Reviewed precedence: PASS
- Parent Basic safe DTO: PASS
- Legacy mapping: PASS
- Rate-limit/cooldown paths: PASS

## 28. Live Groq Basic smoke

NOT RUN. The task was validated through mocked Groq transport and deterministic generators to avoid quota use and nondeterministic medical output.

## 29. PubMed/PMC calls

No live PubMed or PMC calls were made. Discovery and evidence-content behavior used deterministic fixtures.

## 30. Production integrity

No production database was migrated or edited, no production job was retried, and no Reviewed or historical Auto business content was rewritten. Only source files, tests, and the two requested report artifacts changed.

## 31. Remaining limitations

Live provider behavior and real PubMed/PMC availability remain environment-dependent and were intentionally not exercised. Provider-specific output quality is still bounded by the new validation and deterministic template floor.

## 32. Manual test required

No manual test is required for acceptance. An optional staging smoke test can verify visual labels and a real configured provider without changing the deterministic PASS result.
