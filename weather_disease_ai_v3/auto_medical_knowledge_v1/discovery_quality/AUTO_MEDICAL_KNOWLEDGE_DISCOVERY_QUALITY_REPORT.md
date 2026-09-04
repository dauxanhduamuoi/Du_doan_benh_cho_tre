# AUTO MEDICAL KNOWLEDGE V1 — DISCOVERY QUALITY REPORT

## 1. Status

`PASS_WITH_NOTES`

Evidence discovery, deterministic relevance protection, persisted diagnostics, Admin UI diagnostics, focused regression, three bounded live PubMed/PMC cases, build, and startup all passed. The note is material: the one permitted live Groq generation reached the safety-validation stage but was rejected with `AUTO_OUTPUT_VALIDATION_FAILED`; no Auto revision was persisted and no second LLM call was made.

## 2. Audit of current production jobs

The production database was inspected read-only before implementation. No historical rows were deleted or rewritten.

- Jobs inspected: 19.
- `FAILED`: 7.
- `INSUFFICIENT`: 12.
- Group 6: four `INSUFFICIENT` jobs (age 1–5, seasonality, gender Nam, wind), all with zero selected sources.
- Group 41: four `INSUFFICIENT` jobs (age 1–5, humidity, wind, seasonality), all with zero selected sources.
- Group 32: three `INSUFFICIENT` jobs (age 1–5, seasonality, wind); the seasonality job selected one false-positive source and the other two selected none.
- Group 169: four `FAILED` jobs (age 1–5, seasonality, wind, humidity).
- Group 87: three `FAILED` jobs (age 1–5, seasonality, wind) and one `INSUFFICIENT` job (`weather_condition`).

Exact historical `FAILED` root causes:

| Stage | Stored code | Count |
|---|---|---:|
| LLM structured output parsing/validation | `DRAFTGENERATOROUTPUTERROR` | 6 |
| LLM provider rate limit | `DRAFTGENERATORRATELIMITERROR` | 1 |
| PubMed search / PMC retrieval | none | 0 |

The historical audit therefore does not support attributing these seven failures to PubMed, PMC, source filtering, or database persistence. Six failed after source selection at structured LLM output, and one failed at provider rate limiting.

The excessive historical `INSUFFICIENT` rate had two demonstrated causes: the old search used a narrow pair of near-identical queries and then applied weak token/sub-string filters; eleven of twelve insufficient jobs selected no source and had only the generic limitation. The remaining job exposed the false disease match described below. Historical rows do not contain enough stage counts to invent more specific retrospective reasons, so none were backfilled.

## 3. Disease group 32 investigation

Group 32 is the deployed ICD range `A90-A94,A96-A99`: other arthropod-borne viral fevers and viral haemorrhagic fevers. Its deployed child catalog includes Dengue, Chikungunya, West Nile virus infection, Rift Valley fever, Lassa fever, Ebola virus disease, and related viral diagnoses. It is not a malaria group.

PMID `14636983`, “Impact of alphacypermethrin treated bed nets on malaria…”, was therefore a real false positive. The old implementation parsed the incomplete suffix `Other arthropod`, removed generic words, and accepted the single token `arthropod`; this allowed a malaria/vector-control article through. The fix does not hardcode malaria or this PMID. It rejects incomplete/generic group aliases and builds exact aliases from deployed child ICD English names. The regression source now fails the disease gate.

## 4. Query strategy and Guided Search reuse

Before:

- one group suffix was treated as the disease term;
- two near-identical queries were executed;
- disease, factor, and pediatric checks used naïve substrings;
- every surviving result was ranked by a single additive score;
- no per-stage counts or safe query audit were returned.

After:

1. `STRICT`: specific deployed disease aliases + pediatric clause + strict factor phrases.
2. `EXPANDED_FACTOR`: same disease representation + broader safe factor vocabulary.
3. `BROADER_DISEASE`: additional exact child ICD aliases + pediatric clause + expanded factor vocabulary.

The stages are configurable and bounded at three. Each query is bounded at 25 results, evidence resolution is capped, and selection remains capped at 10. Search stops early only after enough pediatric-relevant usable candidates exist.

Reviewed Guided Search is unchanged. The existing pediatric clause, query-component formatting, and domain vocabulary remain in `pubmed_query_builder`; Auto adds an additive phrase-oriented vocabulary and Auto-specific staged builder. Reviewed lifecycle, explicit source selection, Draft/Approve/Publish, and Parent Reviewed precedence were not coupled to Auto.

## 5. Disease aliases and factor vocabulary

Disease aliases come only from project truth:

- the structured English group name/suffix when it is complete and specific;
- English child diagnosis names from `disease_codes` for the same deployed group;
- deduplication and bounded query size.

No LLM creates aliases and no medical synonym is inferred from model knowledge.

Centralized Auto factor vocabulary now covers ambient/air temperature, environmental hot/cold exposure, relative/absolute humidity, wind speed/velocity, rainfall/precipitation, seasonality/time-of-year/monthly patterns, age comparisons, sex/gender comparisons, and safe age-bucket query hints. Male/female terms may broaden a query but cannot alone satisfy the SEX result gate.

## 6. False-match and relevance protections

Matching is normalized, phrase-aware, and token-boundary-aware. `cold agglutinin` does not satisfy `cold weather`. Clinical humidification does not satisfy meteorological humidity.

Each candidate has separate deterministic signals:

- disease relevance from title, abstract, and PubMed MeSH;
- factor relevance using factor-specific semantics;
- pediatric relevance from title, abstract, and MeSH;
- evidence availability and exact PubMed/PMC provenance;
- trust class and evidence-content richness.

The final gate also requires a disease–factor relationship in a result/conclusion sentence. It rejects two important live false-positive patterns:

- disease and factor appear independently but the paper studies another outcome;
- the selected factor appears only as an adjustment/covariate while a different exposure has the reported effect.

AGE requires an age comparison/distribution signal; SEX requires a sex/gender comparison signal. Merely enrolling an age or both sexes is insufficient. Mixed/adult evidence may supplement a pediatric source, but nothing is selected when there is no pediatric-relevant candidate, and Parent eligibility still requires `PEDIATRIC_DIRECT` from the LLM assessment.

Ranking is deterministic: disease signal, factor signal, pediatric signal, evidence kind/trust, then recency as a small secondary bonus. PMID dedup is mandatory and near-duplicate titles do not consume all ten slots. There is no per-result LLM call or LLM reranker.

## 7. Diagnostics and status semantics

The existing discovery audit table is reused; no migration or duplicate diagnostics table was added. Every new attempt stores:

- `queries_run`;
- `raw_results`;
- `deduplicated`;
- `disease_relevant`;
- `factor_relevant`;
- `pediatric_relevant`;
- `usable_evidence`;
- `selected_for_generation`;
- stage, safe query string, and returned count;
- selected/rejected bibliographic metadata and reason codes.

An attempt key distinguishes retries even when the same durable job resets its retry counter. Retrying a failed job stores the prior safe failure code in audit history before requeueing. No API key, raw prompt, filesystem path, or raw evidence body is returned to Admin.

`FAILED` is now reserved for technical/process failure and maps to stable safe codes including `PUBMED_SEARCH_FAILED`, `PMC_ENRICHMENT_FAILED`, `LLM_PROVIDER_FAILED`, `LLM_INVALID_RESPONSE`, `AUTO_OUTPUT_VALIDATION_FAILED`, `PERSISTENCE_FAILED`, and `UNKNOWN_INTERNAL_ERROR`.

`INSUFFICIENT` means the pipeline worked but evidence did not support generation. Specific outcomes include `NO_SEARCH_RESULTS`, `NO_DISEASE_RELEVANT_SOURCE`, `NO_FACTOR_RELEVANT_SOURCE`, `NO_PEDIATRIC_RELEVANT_SOURCE`, `NO_USABLE_EVIDENCE`, `NO_DIRECT_SUPPORT`, and `CONFLICTING_EVIDENCE`. All `NOT_SUPPORTIVE`, no pediatric-direct support, and conflicting evidence remain hidden `INSUFFICIENT`; explanations are not invented.

## 8. Admin UI

The Admin panel now shows simple Vietnamese failure and insufficiency explanations instead of only `Lỗi`. It uses “Chưa tìm đủ bằng chứng phù hợp” and explicitly avoids claiming that no evidence exists anywhere.

The expandable `Chi tiết tìm kiếm` section shows pipeline counts, safe queries, and selected/rejected bibliography. It never displays full raw evidence. `Thử lại` remains limited to failed jobs; `Tạo lại` creates a fresh Admin attempt for insufficient content; runtime ON/OFF and Parent display mode are unchanged.

## 9. Files changed for this task

- `seasonal_disease_backend/app/services/auto_evidence_relevance.py`
- `seasonal_disease_backend/app/services/auto_evidence_discovery.py`
- `seasonal_disease_backend/app/services/pubmed_query_builder.py`
- `seasonal_disease_backend/app/services/pubmed_client.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/repositories/auto_medical_knowledge_repository.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/tests/test_auto_evidence_discovery.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`

The worktree already contained earlier Medical Knowledge V1 changes; they were preserved and not reverted.

## 10. Automated validation and E2Es

- Focused backend: `137 passed`, `0 failed`.
- Focused frontend: `103 passed`, `0 failed`.
- TypeScript typecheck: PASS.
- Production frontend build: PASS; executed once.
- `git diff --check`: PASS (line-ending warnings only).

Deterministic E2Es:

- `AUTO_DISCOVERY_STRICT_E2E=PASS`
- `AUTO_DISCOVERY_FALLBACK_E2E=PASS`
- `AUTO_IRRELEVANT_SOURCE_GUARD_E2E=PASS`
- `AUTO_TRUE_INSUFFICIENT_E2E=PASS`
- `AUTO_FAILURE_CLASSIFICATION_E2E=PASS`

Focused tests cover catalog aliases, factor vocabulary, all three stages, early stop, bounded queries, dedup, disease/factor/pediatric gates, malaria rejection, cold-agglutinin collision, clinical humidification, covariate-only humidity, independent disease/factor mentions, evidence availability, max 10, specific status reasons, all-NOT_SUPPORTIVE handling, provider failure, retry history, provenance, pediatric/trust gates, Reviewed regression, and Parent isolation.

## 11. Final live PubMed/PMC smoke

The exact production PubMed client, PMC enrichment service, deployed catalog, and final deterministic gates were used with three stages and ten results per query. No secrets were printed.

| Case | queries | raw | dedup | disease | factor | pediatric | usable | selected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 168 Influenza + humidity | 3 | 30 | 10 | 5 | 1 | 1 | 1 | 1 |
| 169 Pneumonia + temperature | 3 | 30 | 22 | 13 | 2 | 2 | 2 | 2 |
| 169 Pneumonia + humidity | 3 | 30 | 12 | 5 | 1 | 1 | 1 | 1 |

Final selected sources:

- Influenza + humidity: PMID `41102740`, a longitudinal influenza A analysis reporting nonlinear associations with mean relative humidity and pediatric age strata.
- Pneumonia + temperature: PMID `29037396`, maternal ambient-temperature exposure and early childhood pneumonia; PMID `20135749`, cold-weather/hypothermia evidence and pneumonia in young children.
- Pneumonia + humidity: PMID `34650108`, spatio-temporal childhood pneumonia analysis in Bhutan.

Manual abstract review removed articles where humidity was only a model covariate, where influenza and humidity were independent asthma exposures, and where the paper's reported relationship concerned another pathogen/factor. `LIVE_PUBMED_PMC_DISCOVERY=PASS`.

## 12. Live LLM smoke

Exactly one live Groq generation was attempted in a temporary SQLite database for group 169 + temperature, using the production discovery, prompt, generator, validator, and persistence path. It returned to the processor but failed the deterministic safety/output validator:

- Job: `FAILED`.
- Failure code: `AUTO_OUTPUT_VALIDATION_FAILED`.
- Auto revision persisted: no.
- Parent visibility: false.
- Production database write: none.

The provider was configured and reachable, so this is not reported as provider unavailable. No second LLM request was made. `LIVE_AUTO_GENERATION=FAIL_AUTO_OUTPUT_VALIDATION`.

This note requires a separate focused investigation of the actual validation category/provider output compatibility. The validator was intentionally not weakened in this discovery-quality task.

## 13. Startup and integrity

- Required Python: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`.
- Python: 3.11.15.
- `import app.main`: PASS.
- FastAPI lifespan/migrations/startup: PASS.
- HTTP `/`: 200 PASS.
- SQLite `integrity_check`: `ok`.
- Foreign-key violations: 0.

The bounded live discovery and temporary live generation left the production DB SHA-256 unchanged during that smoke (`e9dc3d8e...` before and after). A subsequent required normal FastAPI lifespan ran startup-maintained database operations while the user's backend process also had the shared SQLite file open, so the raw file hash later changed. Business integrity remained stable: 15 Reviewed revisions, 4 publication events, and 19 Auto jobs before and after; no production Auto visibility, Reviewed publication, Weather AI, or Forecast AI data was changed by the smoke.

The local `.env` and `database.db` remain git-ignored. No secret value was printed or added to an artifact.

## 14. Remaining limitations and manual test

1. The single live Groq output was rejected by the safety validator; because the task capped LLM calls at one, the precise provider-output remediation was not attempted here.
2. Historical attempts retain their real old audit but do not receive fabricated new stage counts.
3. Deterministic metadata/text relevance is intentionally conservative and cannot replace final source assessment or medical review.
4. Provider scope remains PubMed/PMC only; WHO/CDC were not added.

`USER_MANUAL_TEST_REQUIRED=YES`

Recommended manual check: open Admin Auto Medical Knowledge, expand `Chi tiết tìm kiếm` for a newly regenerated non-production-visible topic, verify Vietnamese reason text/counts/queries, and separately investigate a single captured `AUTO_OUTPUT_VALIDATION_FAILED` run without weakening the pediatric, provenance, causality, numeric, or mechanism validators.
