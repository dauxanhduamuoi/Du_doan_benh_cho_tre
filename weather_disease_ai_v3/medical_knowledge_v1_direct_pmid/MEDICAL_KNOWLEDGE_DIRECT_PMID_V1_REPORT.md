# MEDICAL KNOWLEDGE V1 — DIRECT PMID LOOKUP VALIDATION REPORT

Date: 2026-08-23  
Branch: `feature/medical-knowledge-v1-20260820`  
Status: **PASS**

## Outcome

Medical Knowledge V1 now supports a read-only lookup of exactly one PubMed article by PMID. The lookup does not import or persist anything. Staff/admin can inspect the returned article in the existing `PubMedResultCard`, then explicitly select it and use the existing import, deduplication, PMC enrichment, evidence snapshot, and draft workflow.

Keyword search remains the primary workflow and is unchanged at its existing `/search` API contract.

## Source audit and reused architecture

- `PubMedClient.fetch_records(pmids)` already implemented bounded PubMed EFetch and the shared XML parser.
- Keyword search uses `search_ids()` followed by the same `fetch_records()` parser.
- Existing import accepts PMID values only and already performs source reuse/deduplication, PMC enrichment, and evidence snapshot persistence.
- The repository already exposes source lookup by PMID and preferred evidence-content lookup.
- A distinct thin endpoint was necessary because keyword search requires disease/weather query construction and may return multiple relevance-ranked records.
- No direct-import persistence method or duplicate PMID workflow was introduced.

## Backend implementation

- Added `PubMedLookupRequest` with backend-authoritative validation: trim whitespace, ASCII digits only, length 1–16, one PMID per request.
- Added `PubMedClient.get_article_by_pmid()` as a thin exact-match wrapper over the existing EFetch/parser implementation.
- Added `MedicalKnowledgePubMedService.lookup_pmid()` and `POST /api/medical-knowledge/pubmed/lookup`.
- Valid numeric but absent records map to a safe HTTP 404; timeout/429/5xx reuse existing provider error mapping.
- The service filters EFetch output to the requested PMID and can return at most one record.
- Lookup only reads an existing source/evidence summary for badges; it creates no source, content, or revision.
- Extended the shared PubMed parser/model to retain PMCID from the official PubMed `ArticleIdList` when present. No article metadata is hardcoded.

## Frontend implementation

- Added “Tìm trực tiếp bằng PMID” inside “Tùy chọn nâng cao”, with helper text, numeric UX validation, loading state, and friendly not-found/provider errors.
- Exact results replace keyword results and are labeled “Kết quả theo PMID”, so the two search modes are not mixed.
- Exact lookup uses the existing `PubMedResultCard` and `PubMedResults`; no second card or separate import UI was added.
- Existing-source, evidence-content, and PMCID badges render when applicable.
- Selecting an exact result calls the existing `/import` API; lookup alone does not make the source available to draft generation.

## Regression and automated validation

- Focused backend PubMed tests: **61 passed**.
- Focused Medical Knowledge frontend page tests: **36 passed**.
- Full backend: **243 passed, 0 failed**.
- Full frontend: **90 passed, 0 failed** across 4 test files.
- `npm run typecheck`: **PASS**.
- `npm run build`: **PASS** (2,301 modules transformed).
- Python dependency sanity: **PASS**; `pip check` reported no broken requirements.
- `git diff --check`: **PASS**; only Windows LF→CRLF notices were emitted.
- Keyword search regression: **PASS**.
- Source dedup/re-import regression: **PASS**.
- PMC evidence enrichment regression: **PASS**.
- Draft workflow regression: **PASS**.

The automated coverage includes valid and whitespace-normalized PMID, alphabetic/query/URL/SQL-like rejection, missing input, not-found behavior, maximum one result, EFetch/parser reuse, timeout, 429, 5xx, no lookup persistence, existing-source badge, normal import reuse, loading/error states, keyword-result replacement, and keyword/import/evidence regressions.

## Environment and FastAPI startup sanity

- Actual executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`
- Prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`
- Python: `3.11.15`
- Required changed-path imports, including `defusedxml`, `httpx`, and `fastapi`: **PASS**.
- `python -c "import app.main"`: **PASS**.
- Full FastAPI lifespan/migration startup against isolated in-memory SQLite: **PASS**.
- Bounded Uvicorn bind/start on `127.0.0.1:8765`: **PASS** with lifespan disabled; it was then terminated cleanly. The full lifespan was validated separately against the temporary DB to protect production data.

## Live validation

### Direct PubMed lookup

`DIRECT_PMID_LIVE_TEST=PASS`

- Requested PMID: `34201085`
- Returned records: exactly 1
- Returned PMID: `34201085`
- Title: `Lagged Association between Climate Variables and Hospital Admissions for Pneumonia in South Africa.`
- PMCID from official PubMed EFetch metadata: `PMC8228646`
- Temporary DB source count before/after lookup: `0 / 0`

### PMC content enrichment

`PMC_CONTENT_LIVE_TEST=PMC_FULL_TEXT_EXCERPT`

- PMID → PMCID: `34201085` → `PMC8228646`
- Official PMC EFetch content passed the existing parser and conservative license policy.
- Official license URL: `https://creativecommons.org/licenses/by/4.0/`
- Selected evidence length: 5,943 characters.
- Body content was present and valid.
- Fallback reason: none. The excerpt result is the configured bounded-content behavior, not an abstract fallback.

### Optional Groq end-to-end smoke

`GROQ_E2E_LIVE_TEST=PASS`

- Exactly one Groq draft-generation request was made.
- Normalized evidence sent: `PMC_FULL_TEXT_EXCERPT`.
- The existing production prompt/provider path returned a valid structured proposal with one source assessment.
- No production revision or database record was created.
- No patient data, tools, browsing, or second evaluator LLM was used.

## Integrity

- Final controlled smoke-window production DB SHA-256 before: `07BFDFD7B25A73F73FDF170040A10A9EC0476682A71EFC839859AA366C550EEA`
- Final controlled smoke-window production DB SHA-256 after: `07BFDFD7B25A73F73FDF170040A10A9EC0476682A71EFC839859AA366C550EEA`
- Production database modified by smoke validation: **No**.
- The local IDE Uvicorn reloader was active during source editing, so hashes outside the final controlled smoke window were not used as integrity evidence. All direct PMID/PMC validation used isolated in-memory SQLite and never opened the production engine.
- Weather AI, LightGBM, SHAP, ranking, Tier 1, Parent API/UI, Approval, Publish, prompt medical semantics, evidence grading/scope, and PMC license policy were not modified.

## Files added

- `weather_disease_ai_v3/medical_knowledge_v1_direct_pmid/MEDICAL_KNOWLEDGE_DIRECT_PMID_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_direct_pmid/medical_knowledge_direct_pmid_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/pubmed_schemas.py`
- `seasonal_disease_backend/app/services/pubmed_client.py`
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_pubmed.py`
- `seasonal_disease_backend/tests/test_pubmed_client.py`
- `seasonal_disease_backend/tests/test_pubmed_api_service.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_drafts.py` (stale prompt-version assertion only)
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/PubMedSearchForm.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedResults.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedResultCard.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

## Remaining limitations

- V1 accepts one PMID per lookup by design; batch PMID lookup is not included.
- PMC evidence remains bounded by the existing per-source character limit, so this article is represented as a full-text excerpt rather than an unbounded full article.
- Live PubMed, PMC, and Groq checks depend on external service availability and valid local configuration.

User manual testing required: **No**.

