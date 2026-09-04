# Auto Medical Knowledge V2 — Bounded Contract Repair Report

## 1. Status

**PASS** — Auto V2 now performs one generic, bounded LLM contract-repair attempt for the centralized repairable set, then reruns full validation from the beginning. Medical/evidence safety failures are not resampled.

## 2. Read-only production audit: `169 · wind`

- Canonical topic: topic `19`, disease group `169`, `WEATHER / wind`; `published_revision_id` remains `NULL`.
- Latest job: job `11`, attempt `1`, status `FAILED`.
- Failure diagnostic row: `1542`.
- Exact failure: `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`.
- Field: `detailed_explanation_vi`.
- Numeric value: `3`.
- Selected source: source `60`, PMID `21672424`, publication year `2011`, title `[Correlation between pneumonia and meteorological factors in children from Hohhot].`
- The stored abstract has no standalone numeric occurrence `3`. Therefore Numeric Claim V2 correctly rejected the Parent-facing number: it had no declaration and the selected evidence snapshot cannot justify silently retaining it.
- Operationally, turning every mechanical omission into an immediately visible FAILED job made the automatic pipeline brittle even when the remaining proposal was valid. The new path lets the model remove an unnecessary number or declare a genuinely supported one, exactly once, without weakening the validator.
- The production job was not retried, edited, or requeued during this task.

## 3. Architecture

The implemented flow is:

`initial generation → complete validation → typed eligibility decision → at most one repair generation → complete validation from the first validation step → persist only the final valid proposal`

Key properties:

- `MAX_AUTO_CONTRACT_REPAIR_ATTEMPTS = 1`.
- `MAX_AUTO_GENERATION_CALLS = 2` is shared by initial generation, existing structural retry, and contract repair.
- Normal valid output uses one provider call.
- A structural correction uses at most two calls and leaves no budget for a later contract repair.
- An eligible contract failure uses at most two calls.
- A semantic/evidence safety failure uses one call.
- Repair remains in the Auto orchestration layer. OpenAI, Ollama, and Groq receive the same provider-neutral additional instruction through the existing structured generation abstraction.
- Repair receives the same canonical context, exact selected source IDs, evidence content IDs/text, and prior structured proposal transiently in memory. Discovery, PubMed search, PMC enrichment, and source selection are not rerun.
- The backend never edits medical prose with string replacement.
- The repaired proposal uses the same `AutoMedicalKnowledgeDraftProposal` V2 model and provider-compatible strict schema.

## 4. Repair policy

The single policy helper is `is_auto_output_repairable(failure_code)`.

Repairable:

- `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`
- `AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED`
- `AUTO_OUTPUT_NUMERIC_CLAIM_DUPLICATE`

Not repairable, including:

- `AUTO_OUTPUT_CAUSAL_OVERCLAIM`
- `AUTO_OUTPUT_UNSUPPORTED_MECHANISM`
- `AUTO_OUTPUT_PEDIATRIC_CLAIM_INVALID`
- `AUTO_OUTPUT_PERSONALIZED_LANGUAGE`
- `AUTO_OUTPUT_EVIDENCE_LEVEL_INCONSISTENT`
- `AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID`
- `AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH`
- `AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID`
- trusted-source, source-set, provenance, and other ambiguous failures

No numeric value, including `3`, is special-cased.

## 5. Repair behavior and safety

The initial prompt now asks the provider to rescan all three Parent-facing explanation fields before returning and either create exactly one valid declaration for each medically meaningful number or remove the number.

The dedicated repair instruction requires a complete replacement V2 proposal. For a flagged number it prefers qualitative removal when the detail is unnecessary. A retained number must be materially useful and backed by an exact selected source and exact excerpt. Unsupported content must be removed or use the structured INSUFFICIENT path when appropriate. It forbids new numbers, mechanisms, evidence, source IDs, or stronger certainty.

Every repaired output reruns:

- proposal/schema validation;
- exact selected source-set validation;
- personalized, causal, certainty, and mechanism guards;
- evidence-level and source-design consistency;
- pediatric-direct validation;
- Numeric Claim V2 declaration matching;
- selected-source and evidence-content binding;
- exact excerpt verification;
- numeric kind/value/use validation;
- normal READY/INSUFFICIENT determination and persistence.

A repair that invents a quote, uses an invalid source, retains an undeclared number, introduces a new number, or adds a causal claim fails with the final specific code. There is no third call.

## 6. Structural retry and cooldown coordination

One explicit `AutoGenerationCallBudget` is consumed by both the historical structural retry and the new contract repair. The deterministic combined scenario `structural retry → numeric contract failure` stops after two total provider calls and persists no revision.

Before a repair call, the processor checks the existing provider cooldown. A concurrently active cooldown prevents the repair call. A repair-time `429` follows the existing `DraftGeneratorRateLimitError`, provider cooldown, and queue backoff path; no separate provider lane was added.

## 7. Safe diagnostics and persistence

Existing discovery metadata stores only safe fields:

- `initial_provider_call_occurred`;
- `generation_calls` and `max_generation_calls`;
- `contract_repair_attempted`;
- `contract_repair_reason`;
- `contract_repair_calls`;
- `contract_repair_result` (`SUCCESS`, `FAILED`, `RATE_LIMITED`, `NOT_ELIGIBLE`, or `NOT_REQUIRED`).

The Admin response exposes these bounded diagnostics. Failed repair diagnostics are copied into the existing safe failure detail. No raw initial proposal, raw repaired proposal, full prompt, full evidence, stack trace, or secret is persisted. No intermediate revision is created; only the final fully validated proposal can create one.

## 8. Deterministic E2E results

- `AUTO_CONTRACT_REPAIR_REMOVE_NUMERIC_E2E=PASS` — undeclared unnecessary `3` removed; READY; two calls; zero numeric claims; same evidence; one discovery call; raw sentinel absent from persisted metadata.
- `AUTO_CONTRACT_REPAIR_DECLARE_NUMERIC_E2E=PASS` — selected evidence explicitly says participants were divided into `3 groups`; repair creates a valid COUNT claim; exact source/excerpt and support hash persisted.
- `AUTO_CONTRACT_REPAIR_FAIL_CLOSED_E2E=PASS` — undeclared `27%` repaired with a fabricated excerpt; final `AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH`; two calls; no revision.
- `AUTO_SEMANTIC_FAILURE_NO_REPAIR_E2E=PASS` — causal/mechanism-style safety rejection is not contract-repaired; one call.
- `AUTO_CONTRACT_REPAIR_NUMERIC_REGRESSION_E2E=PASS` — existing `5087 ↔ 5.087`, `2004–2009`, generic numeric declaration, and topic age-bucket behavior remain covered and passing.
- `REVIEWED_CONTRACT_REPAIR_ISOLATION_E2E=PASS` — selected Reviewed generation, approval, and publication regressions pass unchanged.
- Offline Groq E2E confirms both initial and repair requests use the identical strict V2 `json_schema` response format.

## 9. Validation executed

- Focused Auto generation, Numeric Claim V2, retry/cooldown, provider-envelope, Admin diagnostics, and six E2Es: **114 passed, 0 failed**.
- Small Reviewed isolation regression (OpenAI bounded strict context, generation persistence, approval, publication): **4 passed, 0 failed**.
- Python compile for all touched backend modules and focused test module: **PASS**.
- `import app.main`: **PASS**.
- Frontend tests: **NOT_REQUIRED**; no frontend file was changed for this task and existing polling continues to show only the final job state.
- Live application startup/lifespan: **NOT_RUN_NOT_REQUIRED**; deterministic tests and import validation were sufficient, and avoiding production startup prevented unrelated business-data writes.
- Live Groq: **NOT_REQUIRED**. The repaired request uses the same already-validated V2 schema and the offline transport E2E passed.

## 10. Files changed for this task

- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_prompt.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- This report and its JSON validation artifact.

No migration and no frontend change were needed.

## 11. External calls and integrity

- Groq calls: `0`.
- PubMed calls: `0`.
- PMC calls: `0`.
- Tests used temporary in-memory SQLite databases.
- Production medical-business tables had SHA-256 `a6f6154b6de3972839ee665ba404c503ad6eaf95201175668b114c15811a2ce9` before final artifact generation and the same hash after validation.
- Production counts remained: discoveries `1542`, Auto jobs `27`, Auto revisions `20`, Auto numeric claims `0`, Reviewed revisions `15`.
- Topic `19`, job `11`, current Auto pointer, published pointer, visibility, Reviewed data, and production source snapshots were not modified.

## 12. Remaining limitations and manual action

- A provider can still return an invalid repair; the intended behavior is a safe final FAILED state after the second call.
- Only the three audited mechanical Numeric Claim V2 codes are repairable. Expanding the set requires a separate safety audit.
- The existing production failure remains historical and unchanged. This task deliberately did not retry it.

No manual test is required for acceptance. A future operator may explicitly retry a failed production job through the normal authorized workflow after deploying the code, but that is outside this validation.
