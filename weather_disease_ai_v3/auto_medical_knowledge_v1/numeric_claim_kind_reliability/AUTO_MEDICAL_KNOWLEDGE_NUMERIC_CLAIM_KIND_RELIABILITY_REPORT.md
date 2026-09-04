# AUTO MEDICAL KNOWLEDGE — NUMERIC CLAIM KIND RELIABILITY V1

## 1. STATUS

`PASS_WITH_NOTES`

Numeric-kind validation now distinguishes a provable taxonomy-only mismatch from a semantic numeric conflict. A taxonomy-only mismatch receives one bounded contract-repair call; ambiguous or conflicting meaning remains fail-closed. No production job was retried and no production business data was changed.

The note is audit-related: the failed historical proposal was intentionally not persisted, so its exact `claim_kind`, `unit`, `supporting_text`, and Parent-facing sentence cannot be recovered without guessing.

## 2. Exact production attempt audited

Audit was read-only against `seasonal_disease_backend/database.db` using SQLite URI `mode=ro` plus `PRAGMA query_only=ON`.

- Python: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` (3.11.15)
- Topic: ID 34, disease group `87`, factor `WEATHER · temperature`
- Job: ID 27, attempt 1, status `FAILED`
- Attempt key: `27:1:2026-09-02T16:24:22.253687`
- Failure: `AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID`
- Failure field: `numeric_claims.1.claim_kind`
- Source: ID 90
- Normalized diagnostic value: `1.07`
- Generation calls: 1 of 2
- Contract repair: not attempted (`NOT_ELIGIBLE` under the previous policy)
- Pipeline version: `auto_medical_knowledge_v3_safe_fallback`
- Current local configured provider/model at audit time: `groq` / `openai/gpt-oss-20b`
- Historical attempt provider/model: not persisted in the failed-attempt diagnostic and therefore not asserted as exact
- Revisions for job 27: 0
- Persisted numeric claims for job 27: 0

Only the `FAILURE_DETAIL` row contains `1.07`; no discovery row, revision, numeric-claim row, or local log contains the raw failed proposal. Consequently:

- AI-declared `claim_kind`: `NOT_PERSISTED`
- AI-declared `unit`: `NOT_PERSISTED`
- AI `supporting_text`: `NOT_PERSISTED`
- Generated prose sentence using `1.07`: `NOT_PERSISTED`

## 3. What source 90 says about 1.07

Source 90 is PubMed PMID `38969477`, DOI `10.1016/S2542-5196(24)00121-9`, published in 2024:

> The peak association between ambient temperature and risk of acute lymphoblastic leukaemia was observed in gestational week 8, where a 5�C increase was associated with an odds ratio of 1�07 (95% CI 1�04-1�11).

That is the exact sentence as stored in evidence content ID 85; the replacement characters are already present in the persisted NCBI snapshot. Its content SHA-256 is `3574b02579467001463ca6803d1ab0d6174e1b23ab58ca10600b28082ca5c121`.

The semantic kind of `1.07` in the selected evidence is unequivocally `RATIO_OR_EFFECT` (odds ratio), not a temperature measurement and not a rate.

## 4. Production-case classification

The historical proposal cannot be certified as `CONTRACT_KIND_MISMATCH`, because that classification requires evidence that the declared enum was the only defect and that the Parent prose used the same odds-ratio meaning. Those proposal fields were never persisted.

For the historical row, the conservative audit classification is therefore `TRUE_SEMANTIC_ERROR` in the sense required by the fail-closed policy: an unproven historical case is not eligible for taxonomy-only repair. This does not assert that the model definitely changed the meaning; it records that the necessary proof no longer exists.

The exact previous code-path defect was also identified: validation trusted `claim_kind` while checking only `value_text + unit` before comparing the number's meaning across selected evidence and Parent prose. A bare effect estimate such as `1.07` could therefore be rejected even when evidence and prose supplied the ratio semantics. The failed proposal was then discarded, preventing a more specific retrospective diagnosis.

## 5. Numeric-kind classifier design

The backend now has one deterministic, provider-independent classifier. It:

- extracts and normalizes the declared numeric occurrence without trusting the declared enum;
- verifies the exact selected source and exact supporting excerpt first;
- derives bounded kind candidates independently from evidence and Parent prose;
- distinguishes `RATIO_OR_EFFECT` from `RATE` using semantic signals such as relative risk/RR, odds ratio, risk ratio, hazard ratio, versus rate/per-denominator wording;
- supports existing percentage, measurement, count, age, duration, and temporal-period rules;
- treats explicit conflicting units as semantic conflicts;
- accepts a kind only when evidence and prose converge on exactly one compatible meaning;
- returns `TAXONOMY_MISMATCH` only when that unique meaning differs from the declared enum;
- returns `SEMANTIC_INVALID` for ambiguity or evidence/prose disagreement.

There is no special case for value `1.07`, source 90, PMID `38969477`, or topic 87.

## 6. Repair policy

`AUTO_OUTPUT_NUMERIC_CLAIM_KIND_MISMATCH` is the new typed, centrally allow-listed repairable failure. It receives exactly one existing V2 contract-repair call within the unchanged maximum of two generation calls.

The repair prompt permits only either:

- changing the flagged `claim_kind` while retaining the supported number, unit, exact source excerpt, and prose meaning; or
- removing the number from Parent prose and removing its declaration.

The backend never silently rewrites the enum. The complete replacement proposal is revalidated from the start. A changed number, source, excerpt, unit meaning, or prose meaning must independently pass the original safety and provenance gates.

`AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID` remains non-repairable.

## 7. Safe Fallback interaction

Taxonomy mismatch was deliberately not added to the Safe Fallback allow-list. If the one repair repeats the mismatch, the job becomes `FAILED` after two calls; there is no third call and no fallback. True semantic kind invalidity is also ineligible for fallback.

This is stricter than the optional fallback behavior and prevents removal of a numeric claim from masking a meaning conflict.

## 8. Why safety is not weakened

- Exact selected-source validation is unchanged.
- Exact supporting-excerpt validation is unchanged.
- Numeric value equivalence remains required before kind classification.
- Verified provenance remains persisted only after the final proposal passes.
- Unsupported changed numbers remain `AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH`, non-repairable, and non-fallback.
- Ambiguous bare values and evidence/prose semantic conflicts fail closed.
- Causal-overclaim, unsupported-mechanism, pediatric, evidence-level, and source-set guards remain in the same validation path.
- Maximum provider calls remain 2.

## 9. Files changed

- `seasonal_disease_backend/app/services/auto_medical_numeric_validation.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_prompt.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- This report and its validation JSON

No migration, schema, API contract, production database row, reviewed content, publication state, or Auto visibility setting was changed.

## 10. Focused validation

- Focused backend numeric/contract-repair/fallback suite: `61 passed, 81 deselected`
- Focused classifier/E2E subset: `27 passed, 115 deselected`
- Backend compile/import: PASS (`compileall`, `import app.main`, validator import)
- Focused frontend mapping suite: `37 passed`
- Frontend TypeScript typecheck: PASS
- Whole backend/frontend suites: not run, as required

E2E results:

- `AUTO_NUMERIC_KIND_REPAIR_E2E=PASS` — wrong enum repaired to `RATIO_OR_EFFECT`, READY `AI_FULL`, two calls, provenance persisted
- `AUTO_NUMERIC_KIND_REMOVE_E2E=PASS` — repair removed number and declaration, READY `AI_FULL`
- `AUTO_NUMERIC_KIND_SEMANTIC_GUARD_E2E=PASS` — evidence RR versus prose temperature failed in one call, no revision/fallback
- `AUTO_NUMERIC_KIND_SAFE_FALLBACK_E2E=NOT_APPLICABLE` — policy intentionally excludes this failure from fallback
- `AUTO_NUMERIC_KIND_REGRESSION_E2E=PASS` — RR, temperature, percentage, count, rate, age, duration, year-range, wrong-value, and no-third-call paths passed

## 11. External calls and production integrity

- Groq calls: 0
- PubMed calls: 0
- PMC calls: 0
- Production job retry: NO
- Production business data modified: NO
- Reviewed content modified: NO
- Auto visibility modified: NO

Read-only integrity snapshot before and after implementation was identical:

- `page_count=46039`
- `freelist_count=1140`
- jobs: 27
- discoveries: 1695
- revisions: 21
- numeric claims: 0
- Job 27 remained FAILED, attempt count 1, with no revision

The database file is covered by `.gitignore` (`*.db`).

## 12. Remaining limitation and manual test

Remaining limitation: raw failed proposals are intentionally not persisted, so the exact historical declared kind/prose cannot be reconstructed. Future failure diagnostics remain secret-safe but cannot retrospectively prove taxonomy-only eligibility unless the diagnostic model is expanded in a separate, explicitly authorized task.

No user manual test is required for this implementation. A live retry was specifically prohibited and was not performed.
