# MEDICAL KNOWLEDGE V1 — PARENT PUBLISHED TIER-2 INTEGRATION

## STATUS

**PASS**

`PARENT_TIER2_E2E_TEST=PASS`

`TIER2_FAILURE_ISOLATION_TEST=PASS`

`USER MANUAL TEST REQUIRED = NO`

## Source audit

- Branch/source of truth: `feature/medical-knowledge-v1-20260820`.
- Parent prediction entry point: `POST /api/public/parent-risk` in `app/routers/public.py`.
- Parent runtime UI: `Frontend/src/app/components/ParentPortal.tsx`.
- Tier 1 is produced by the existing Weather AI response and rendered through `WeatherAIExplanationSections`.
- Canonical disease identifier in the deployed 221-group Weather AI universe is the numeric-string `disease_group_id`/`disease_id` (examples in the manifest include `1`, `4`, `5`, `17`).
- Tier-1 canonical weather factors are `temperature`, `humidity`, `precipitation`, `wind`, and `weather_code`. Medical Knowledge topics use `temperature`, `humidity`, `precipitation`, `wind`, and `weather_condition`.
- Publication source of truth is `MedicalKnowledgeTopic.published_revision_id`, with the referenced `MedicalKnowledgeRevision`, its `parent_display_allowed` flag, and persisted source links.
- Existing publication, approval, PubMed, PMC enrichment, LLM-provider, Weather AI, and authorization behavior was retained.

## Legacy Tier 2 audit and chosen behavior

The existing Weather AI service still computes a legacy Tier-2 response from `medical_knowledge_base.json` through `MedicalKnowledgeService`. It is fail-soft and makes no PubMed, PMC, or LLM runtime call.

The legacy implementation and JSON were not deleted or rewritten. Clinical/internal consumers retain the legacy Tier-2 default. The Parent variant explicitly suppresses that legacy section and renders only the separately fetched published Medical Knowledge V1 section, preventing duplicate Tier-2 UI while preserving backward compatibility.

## Integration architecture

Backend:

`POST /api/public/medical-knowledge/published`
→ `PublishedMedicalKnowledgeReadService`
→ `MedicalKnowledgeRepository.get_parent_published_topics()`
→ bounded database-only lookup.

Frontend:

Parent Weather AI request
→ render ranking and Tier 1
→ build bounded canonical selectors from positive Tier-1 weather factors
→ start a separate, non-awaited public Tier-2 request
→ attach matching safe items if successful.

The public batch is bounded to 1–100 selectors. The repository performs one topic/revision query plus bounded `selectinload` queries for links and sources, avoiding per-card/per-field N+1 access.

## Why failure isolation is guaranteed

- The existing Parent prediction endpoint was not given a Medical Knowledge V1 dependency.
- `setAiResult`, local risk data, and recommendations are completed before the optional request is started.
- Tier 2 is requested with a non-awaited promise and local loading state.
- 404/422/500/timeout/network rejection is caught only in the Tier-2 chain and does not set the Parent page error.
- A runtime sanitizer converts malformed public responses to an empty item list.
- Request IDs discard stale responses after a new prediction/location selection.
- Loading appears only on disease cards that actually had eligible selectors.
- Tests prove ranking, Tier 1, symptoms, prevention, and warning content remain available while Tier 2 is pending, absent, or failed.

## Canonical disease/factor matching

- Disease matching is exact `disease_group_id`; no disease display text, substring, fuzzy, or LLM matching is used.
- Factor selection reads only existing Tier-1 `positive_factors` where `category == WEATHER`, `direction == UP`, and `shap_value > 0`.
- Exact factor mapping is:
  - `temperature` → `temperature`
  - `humidity` → `humidity`
  - `precipitation` → `precipitation`
  - `wind` → `wind`
  - `weather_code` → `weather_condition`
- Unknown/uppercase/display-label values are not inferred.
- Selector order follows disease rank and Tier-1 positive-factor order; duplicate pairs are removed without reordering.
- The frontend also rejects response rows not present in the exact requested disease/factor pair set.

## Publication eligibility and fail-closed behavior

An item is returned only when all checks hold:

1. The exact topic exists.
2. `published_revision_id` is non-null.
3. The loaded revision ID equals that pointer.
4. The revision belongs to the same topic.
5. Status is `APPROVED`.
6. `parent_display_allowed` is true.
7. Evidence level is Parent-displayable.
8. Structured revision text, source assessments, source roles, and citations validate.

DRAFT, APPROVED-but-unpublished, old replaced revisions, false display flags, wrong-topic pointers, malformed assessments, inconsistent source roles, and unsafe evidence levels all return no item. Missing knowledge is a normal `200 {"items": []}` result.

Replacement uses the topic pointer immediately: the E2E reads Revision 1, changes the publication pointer to Revision 2, then reads only Revision 2.

## Evidence-level Parent policy

The existing conservative legacy policy was reused:

- `SUPPORTED` → displayed as “Có cơ sở y khoa tương đối rõ”.
- `LIMITED_OR_INDIRECT` → displayed as “Bằng chứng còn hạn chế / gián tiếp”.
- `INSUFFICIENT` → not returned to Parent.
- `CONFLICTING` → not returned to Parent.

No evidence level is converted into causal or individual-risk language.

## Public read model and data exposure

Parent can receive only:

- exact disease-group and weather-factor identifiers;
- current revision identifier;
- evidence level and scope;
- short explanation, expandable detailed explanation, and limitations;
- bibliographic source summaries: title, journal, year, PMID, DOI, optional PMCID, and safe URL.

Numeric PMID values are linked to the official HTTPS PubMed URL. Unsafe/non-HTTPS fallback URLs are not made clickable.

The endpoint and UI do **not** expose raw abstract, PMC/full evidence text, evidence snapshots, raw metadata, source-assessment reasoning, `DIRECT`/`PRIMARY` internals, provider/model, prompt version, review notes, reviewer/publisher IDs, staff email, JWT/API keys, draft history, or unpublished revisions.

The read path imports/calls no DraftService, ApprovalService, PublicationService, LLM provider, PubMed client, PMC client, or Weather API.

## Parent UI

- Tier 1 remains under the existing ranking explanation.
- V1 uses a distinct “Giải thích y khoa” section and reviewed-evidence helper text.
- Short explanation is shown first.
- Detailed explanation uses native expand/collapse.
- Limitations and a parent-friendly evidence badge are visible.
- Bibliographic references are listed last with secure new-tab attributes.
- A non-diagnostic/non-individual-risk disclaimer is always included in the Tier-2 section.
- No approval, publication, import, edit, or staff control is present.

## Tests and validation

Backend focused safe-read tests: **22 passed, 0 failed**.

Critical backend E2E selection (public read plus atomic Publish E2E): **23 passed, 0 failed**.

Full backend regression: **291 passed, 0 failed** in the exact `seasonal_backend` environment. This includes Weather AI, Parent API, Tier 1, PubMed keyword/direct PMID, evidence enrichment, Draft, Approval, and Publish regressions.

Frontend focused Parent/API/presentation tests: **13 passed, 0 failed**.

Full frontend regression: **116 passed, 0 failed** across 7 files.

TypeScript typecheck: **PASS**.

Vite production build: **PASS** (2,302 modules transformed).

Critical cases:

- Case A — Tier 2 success: **PASS**; ranking + Tier 1 + matching published V1 render.
- Case B — no Medical Knowledge: **PASS**; ranking + Tier 1 + care guidance remain.
- Case C — 500/network/pending Tier 2: **PASS**; ranking and Tier 1 remain, no technical error leaks.
- Case D — DRAFT and APPROVED-but-unpublished: **PASS**; neither is returned.
- Case E — replacement publication: **PASS**; Revision 1 is read first, then only Revision 2.

## Startup sanity

- `sys.executable`: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`
- `sys.prefix`: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`
- Python: `3.11.15`
- `pip check`: **PASS** — no broken requirements.
- `app.main` and published-read imports: **PASS**.
- FastAPI lifespan using a temporary isolated SQLite DB: **PASS**.
- Bounded Uvicorn startup/shutdown using the isolated DB: **PASS**.
- Frontend typecheck/build: **PASS**.

## Production database integrity

No production test topic, revision, source, approval, or publication was created. All backend E2E tests and startup checks used in-memory or temporary SQLite databases.

The user's already-running Uvicorn `--reload` process continuously changed the byte-level hash of `seasonal_disease_backend/database.db`, so a stable whole-file SHA-256 comparison was not technically valid and the process was not stopped without authorization. A controlled read-only before/after snapshot around the focused validation proved all six production Medical Knowledge tables unchanged, including identical row counts and SHA-256 values:

- `medical_evidence_contents`: 1 row, `BEE9EA866BAD3D6F17D1F3F75987480BB4D50A6119E8DAD6909E8DAF7BCBDC7F`
- `medical_evidence_sources`: 4 rows, `5F9BAFB43F5D3DB656CAFA141F0434DEACE29AB242F358EE042932ED8EEFD69F`
- `medical_knowledge_publications`: 0 rows, empty SHA-256
- `medical_knowledge_revisions`: 6 rows, `9F98DAAC449AD44376C2B5DDFA1A4E10BF52BE5D5A8AA4E104A9816EB27FAC3B`
- `medical_knowledge_topics`: 2 rows, `F79C4123546917EDFC18C64E63224D81CB9EAB6AEB13B4EAF19E9F54A4D82525`
- `medical_revision_sources`: 12 rows, `911855AFCA52348026A8C9D2BB227C64F0E5229D11476C595F68493F34663A3A`

The root placeholder `database.db` remained zero bytes with SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

## Integrity confirmations

- Weather AI service/calculation files changed by this task: **NO**.
- LightGBM model/artifacts changed: **NO**.
- SHAP mathematics changed: **NO**.
- Ranking calculation changed: **NO**.
- Tier-1 calculation/presentation logic changed: **NO**.
- 14-day prediction or Weather API behavior changed: **NO**.
- LLM called at Parent V1 read runtime: **NO**.
- PubMed/PMC called at Parent V1 read runtime: **NO**.
- Unpublished/replaced data exposed: **NO**.
- Database migration added for this task: **NO**.

## Files added

- `seasonal_disease_backend/app/published_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/services/published_medical_knowledge_read_service.py`
- `seasonal_disease_backend/tests/test_published_medical_knowledge_public.py`
- `Frontend/src/app/components/weather-ai/publishedMedicalKnowledge.ts`
- `Frontend/src/app/components/ParentPortal.test.tsx`
- `Frontend/src/app/components/weather-ai/publishedMedicalKnowledge.test.tsx`
- `Frontend/src/lib/publishedMedicalKnowledgeApi.test.ts`
- `weather_disease_ai_v3/medical_knowledge_v1_parent_integration/MEDICAL_KNOWLEDGE_PARENT_INTEGRATION_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_parent_integration/medical_knowledge_parent_integration_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/routers/public.py`
- `Frontend/src/lib/api.ts`
- `Frontend/src/app/components/ParentPortal.tsx`
- `Frontend/src/app/components/weather-ai/WeatherAIResults.tsx`

## Remaining limitations

- The current persisted source model does not retain PMCID directly; the safe DTO includes the optional field but returns `null` unless the persistence model later supplies it. PMID/DOI and official PubMed links remain available.
- A stable byte hash of the entire live backend DB cannot be attributed while the user's separate auto-reloading Uvicorn process continues concurrent writes. Medical Knowledge table-level hashes were stable and no production publication/test data was written.

Automated validation is sufficient. No manual Parent workflow test is required for this task.
