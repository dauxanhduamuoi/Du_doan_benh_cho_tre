# MEDICAL KNOWLEDGE V1 — GENERAL EXPLANATION FACTORS

## 1. STATUS

**PASS** — Medical Knowledge V1 now supports AGE, SEX, SEASONALITY, and WEATHER through one canonical factor selector while preserving the reviewed/published Weather workflow.

## 2. Old topic architecture

Topics were identified by `disease_group_id + weather_factor`. Staff PubMed discovery, source libraries, drafts, revision history, publication pointers, and Parent safe-read were consequently weather-specific.

## 3. New generic factor architecture

The canonical topic selector is now:

```text
disease_group_id + factor_type + factor_key + nullable factor_value
```

The supported types are `WEATHER`, `AGE`, `SEX`, and `SEASONALITY`. A null-safe unique index prevents duplicate canonical topics. Flat DTO fields were retained because they integrate cleanly with the existing API. `weather_factor` remains a compatibility field for legacy callers and records.

## 4. Migration/backward compatibility

Migration `V007` is non-destructive and idempotent. Existing weather topics were backfilled as `WEATHER + existing weather_factor + null`. Topic IDs, source links, revision IDs/content, publication history, and current published pointers were preserved. The migration was applied twice successfully and `PRAGMA foreign_key_check` returned no rows.

## 5. Factor types supported

- `WEATHER`: temperature, humidity, precipitation, wind, and the existing supported weather keys.
- `AGE`: canonical key `age_group` with values from the deployed Weather AI category mapping.
- `SEX`: canonical key `gender`, matching the current Tier-1 feature name, with values from the deployed category mapping.
- `SEASONALITY`: canonical key `time_of_year`, with null value in V1.

## 6. AGE value behavior

AGE requires a value. The UI and backend use the current deployed buckets: `Dưới 1 tuổi`, `1-5 tuổi`, `6-10 tuổi`, `11-15 tuổi`, `Trên 15 tuổi`, and `Không rõ`. Missing or unsupported values receive a specific validation error. Different buckets form different topics and source libraries.

## 7. SEX value behavior

SEX requires a value from the deployed Weather AI contract: `Nam` or `Nữ`. Male and female topics are distinct. A source is DIRECT only when the selected evidence reports a meaningful result for the selected sex; merely enrolling both sexes is not sufficient.

## 8. SEASONALITY behavior

SEASONALITY uses `time_of_year` with `factor_value = null`. It has no second selector and does not invent a rain/dry-season classifier. The prompt requires evidence of a seasonal/month/time-of-year pattern and prohibits causal wording.

## 9. WEATHER compatibility

The existing weather UX remains one selection with no value. Legacy `weather_factor` inputs are normalized into the generic selector, existing weather histories/libraries/publications remain reachable, and the Parent public API still accepts the compatibility form.

## 10. Guided PubMed queries

Guided queries retain English disease terms and the existing pediatric population clause, then add bounded vocabulary appropriate to exactly one selected factor. WEATHER preserves the prior weather behavior; AGE uses age-distribution/age-specific terms plus a safe selected-bucket hint; SEX uses sex-difference terms plus a non-overconstraining value hint; SEASONALITY uses seasonal-pattern terms without injecting current weather.

## 11. Free PubMed search

Staff can enter a non-empty bounded PubMed query with useful quotes, parentheses, and field tags preserved. Null/control characters and invalid request/result bounds are rejected. Free search changes discovery only: imported sources enter the currently selected generic topic through the same global-dedup, enrichment, and Topic Source Library pipeline.

## 12. Direct PMID behavior

Direct PMID lookup is preserved and feeds the same source import and topic-library pipeline as Guided and Free search.

## 13. Source Library behavior

Topic Source Library queries and ownership checks use the full canonical selector. Sources for AGE `1-5 tuổi` cannot leak into another AGE bucket, SEX, SEASONALITY, WEATHER, or another disease. Switching to an incompatible factor clears the current topic/source selection in the staff UI.

## 14. Draft/Approval flow

Staff collects sources, explicitly selects a source basket, and requests one DRAFT. Generation receives the exact disease group, factor type/key/value, pediatric target, and immutable selected-evidence snapshots. Existing revision review, APPROVE, PUBLISH, and UNPUBLISH gates remain unchanged.

## 15. Why article-level approval was NOT added

Articles are collected, selected, and assessed as evidence; formal clinical approval remains at the complete medical-explanation revision. Adding per-article approval would duplicate workflow state without replacing the required review of the composed explanation and its source assessments.

## 16. Parent generic Tier-2 matching

Parent creates lookup selectors only from actual positive/upward Tier-1 contributions. AGE uses the normalized current `age_group`; SEX uses the normalized current `gender`; SEASONALITY requests `time_of_year + null`; WEATHER maps the existing positive weather feature. The current V1 direction rule remains **positive `UP` contributions with SHAP value greater than zero only**. Lookup remains fail-closed through the published pointer, APPROVED status, `parent_display_allowed`, safe evidence level, pediatric support, source ownership, and valid-content gates.

## 17. Parent failure isolation

Targeted frontend tests simulate generic knowledge endpoint HTTP and network failures. Ranking, Tier-1 factor cards, age/sex/seasonality information, and the usable Parent page remain present; only unavailable Tier-2 sections are omitted. Parent runtime never calls PubMed, PMC, Groq, OpenAI, Ollama, or draft generation.

## 18. Files added

Implementation files added for this task:

- `seasonal_disease_backend/app/medical_knowledge_factors.py`
- `seasonal_disease_backend/app/medical_knowledge_factor_schemas.py`
- `seasonal_disease_backend/migrations/v007_medical_knowledge_general_factors.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_general_factors.py`
- `Frontend/src/lib/medicalKnowledgeFactors.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeGeneralFactors.test.tsx`

This report and its validation JSON are the only artifacts created in this task's report directory.

## 19. Files modified

Relevant backend changes cover the Medical Knowledge models/schemas/repository, staff PubMed and Draft routers/services, generic prompt/generator context, public safe-read service/API, startup migration registration, prompt configuration, and focused tests. Relevant frontend changes cover the research page, factor/search form, Draft workspace, Topic Source Library, Medical Knowledge APIs, published-knowledge selector mapping, Parent presentation, and focused regression tests. No model-training or prediction-engine files were changed.

## 20. Migration result

**PASS** — V007 ran twice; all six pre-existing topics remain and all six were backfilled to `WEATHER`, with `factor_key = weather_factor` and null `factor_value`. Foreign-key validation is clean. Nullable-value uniqueness and factor-specific checks are active.

## 21. Focused backend tests

**PASS — 221 passed, 0 failed** in the final broad Medical Knowledge-focused run. This includes 55 general-factor tests and the existing Draft, public read, source-library, and PubMed API suites. Two existing Pydantic deprecation warnings were emitted; they are unrelated to this feature.

## 22. Focused frontend tests

**PASS — 136 passed, 0 failed across 5 files.** Coverage includes factor selectors, topic/source isolation, all three search modes, Draft payloads, generic Parent Tier-2 rendering, missing-knowledge behavior, and failure isolation.

## 23. Targeted E2E

`GENERAL_EXPLANATION_FACTORS_E2E=PASS`. Deterministic isolated-DB/provider flows covered AGE, SEX (including the unmatched female case), SEASONALITY, and legacy-compatible WEATHER from source-library association through Draft, Approve, Publish, and Parent safe-read.

## 24. Typecheck/build

**PASS** — `tsc --noEmit` passed. The production Vite build was run exactly once and passed (2,304 modules transformed; 5.07 seconds).

## 25. Startup

**PASS** — backend import, complete FastAPI lifespan/migrations, and HTTP root smoke returned 200 using `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` (Python 3.11.15).

## 26. Live PubMed call

`GENERAL_FACTOR_PUBMED_LIVE_SMOKE=NOT_RUN`. The optional call was not needed because deterministic query and common-pipeline tests passed. No result was imported. No live Groq/OpenAI/Ollama call was made.

## 27. Production DB integrity

**PASS** — before/after counts and SHA-256 hashes match for all legacy business columns/content: topics 6, revisions 14, topic sources 14, revision sources 29, publications 4, evidence sources 17, and evidence contents 14. V007 added/backfilled only generic topic metadata. No old revision content, source evidence snapshot, or publication state was rewritten.

## 28. Remaining limitations

- SEASONALITY V1 intentionally has topic-level null scope; it does not distinguish individual months or invented seasons.
- Free PubMed search is staff-directed discovery and does not imply relevance or trust; evidence still requires selection, AI assessment, and revision approval.
- Parent retains the established positive/upward-only Tier-2 enrichment policy; negative/downward explanations are outside this task.

## 29. Manual test required or not

`user_manual_test_required = false`. Automated focused tests, deterministic E2E, migration/integrity validation, production build, typecheck, and startup/HTTP smoke all passed. An optional visual staff walkthrough may still be useful but is not a release blocker.
