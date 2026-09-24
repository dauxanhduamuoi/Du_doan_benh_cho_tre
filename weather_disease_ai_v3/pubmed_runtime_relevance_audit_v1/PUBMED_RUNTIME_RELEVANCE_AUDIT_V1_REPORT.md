# PubMed Reviewed Runtime Relevance Integration Audit V1

## Status

PASS.

- Repository branch: `feature/medical-knowledge-v1-20260820`
- HEAD before and after the audit: `dca4c7d1d79ab3863601fb24691acafaec965085`
- The existing dirty worktree was preserved.
- NO COMMIT. NO PUSH. NO RESET. NO DISCARD.
- Live calls: PubMed 0, WHO 0, Groq 0.
- Database/schema/data changes made by this task: none.

## Exact root cause

The frontend contained a real single-provider optimization in `MedicalKnowledgeResearchPage.runSearch`:

```text
providerModeAvailable = providerSettings contains a non-PubMed provider
useLegacyPubMed = FREE or not providerModeAvailable
```

Consequently, when PubMed was the only globally enabled Reviewed provider, a Guided search called the legacy endpoint `POST /api/medical-knowledge/pubmed/search`. `MedicalKnowledgePubMedService.search` builds a PubMed query and returns every normalized search record directly as `PubMedSearchResponse`; it does not invoke `MedicalEvidenceReviewedService` or `ReviewedEvidenceRelevance`. This was a genuine Guided runtime bypass and was reproduced by a frontend regression that failed before the fix.

The bypass has been removed. Guided search now always calls `POST /api/medical-knowledge/providers/search`, regardless of whether the selection is PubMed-only or PubMed+WHO. Only explicit PubMed FREE search continues to use the legacy endpoint.

## End-to-end runtime path after the fix

```text
PubMedSearchForm submit button
  -> MedicalKnowledgeResearchPage.runSearch
  -> searchMedicalEvidenceProviders
  -> POST /api/medical-knowledge/providers/search
  -> medical_evidence_reviewed.search_providers
  -> MedicalEvidenceReviewedService.search
  -> registry.get("PUBMED")
  -> PubMedMedicalEvidenceProvider.build_reviewed_query_plan/search
  -> PubMed client records
  -> normalize_pubmed_record -> NormalizedMedicalEvidence
  -> ReviewedEvidenceRelevance.classify
  -> accepted DIRECT_TOPIC / RELATED_CONTEXT only
  -> ReviewedProviderSource.relevance DTO
  -> omitRejectedReviewedResults defensive UI boundary
  -> provider-group rendering from item.relevance
```

The deterministic FastAPI TestClient regression uses this same HTTP route and an actual `MedicalEvidenceReviewedService` plus actual `PubMedMedicalEvidenceProvider`; only the external PubMed client is replaced by a local fixture. It therefore covers provider query construction, provider search, PubMed normalization, shared classification, response DTO validation, and HTTP serialization without a live call.

## The two wrong-disease titles

For topic `Plague + humidity`, the exact fixtures now behave as follows through the real UI endpoint:

| Candidate | Final classification | Normal results |
|---|---:|---:|
| `The temperature-dependent conformational ensemble of SARS-CoV-2 main protease (Mpro).` | `REJECT` | absent |
| `Edge IoT Prototyping Using Model-Driven Representations: A Use Case for Smart Agriculture.` | `REJECT` | absent |
| `Plague transmission and relative humidity` | `DIRECT_TOPIC` | present |
| `Plague vaccination` | `RELATED_CONTEXT` | present |

In the current shared orchestration source, the two bad candidates do not become DIRECT anywhere: both reach `ReviewedEvidenceRelevance.classify`, fail the disease anchor, and are removed before DTO assembly. In the pre-shared architecture, a candidate retrieved by a direct query attempt could inherit that attempt's `DIRECT_TOPIC` provenance as final relevance. That historical behavior explains how the observed direct badges were possible, but it is absent from the current service.

The runtime observation could not be reproduced from the current source. The remaining reproducible defect was the PubMed-only Guided legacy bypass described above. The audit does not attribute the defect to cache.

## Query provenance audit

`ReviewedMedicalEvidenceQueryAttempt.relevance` is used only to prioritize bounded retrieval and decide when enough direct candidates have been collected. `attempt.level` is passed into `classify` only for diagnostic call-site clarity; the classifier explicitly discards `query_level` before deriving its result.

The endpoint regression deliberately returns `Plague vaccination` from `DIRECT_DISEASE_FACTOR_PEDIATRIC`. Its final DTO is still `RELATED_CONTEXT`, proving that direct query provenance does not win over content classification. Response assembly uses `assessment.classification.value`, while query provenance remains separately available as `query_level` and in query-attempt diagnostics.

## Frontend relevance and rejection handling

The provider badge reads only `item.relevance`:

- `DIRECT_TOPIC` -> `Bằng chứng trực tiếp`
- accepted non-direct relevance -> `Tài liệu liên quan`

It does not read `query_level`, query-attempt relevance, provider attempt type, or a legacy `is_direct` field. A component regression sends a RELATED result whose `query_level` is DIRECT and verifies the RELATED badge.

The backend normally never serializes rejected candidates in `results`. As a defense-in-depth boundary, `omitRejectedReviewedResults` removes any unexpected `REJECT` item from both flat and grouped response collections before it reaches React state. The component regression supplies both exact bad titles as `REJECT` and verifies neither renders.

## PubMed-only versus PubMed+WHO

The endpoint regression executes both selections with identical PubMed fixtures. The PubMed projection is byte-for-byte equivalent in classification and order:

```text
Plague transmission and relative humidity -> DIRECT_TOPIC
Plague vaccination -> RELATED_CONTEXT
```

Adding WHO does not change PubMed classification. The WHO fixture `WHO guidelines for plague management` remains one plausible `RELATED_CONTEXT` result. No WHO provider, query, paging, trust, license, or relevance code was changed.

## Legacy paths

- `POST /api/medical-knowledge/pubmed/search` still exists for explicit PubMed FREE syntax and legacy compatibility.
- Guided requests no longer reach that endpoint from the real Reviewed search button.
- Direct PMID lookup remains PubMed-specific and unchanged.
- No fallback, DTO compatibility mapping, or single-provider branch now assigns final Guided relevance outside `ReviewedEvidenceRelevance`.

## Runtime and reload audit

- No listeners were present on ports 5173, 5174, 8000, or 8001 during this audit, and no matching Vite/Uvicorn application process was running. There was therefore no active local process whose loaded module version could be compared with disk.
- Backend Python changes require a process restart unless Uvicorn is started with `--reload`. Because the shared relevance files were already changed before this task, a manually started non-reload backend could have continued serving the pre-shared logic until restarted. This is a deployment caveat, not the reproduced root cause.
- Vite development mode normally updates changed React modules through HMR. A production/static frontend requires a new build and redeployment. After deployment, a hard reload is the safest way to discard an old tab's previously loaded bundle.
- Before the fix, a new provider search replaced the response only after completion, so prior provider cards could remain visible while the request was in flight. `runSearch` now clears both legacy and provider result state at request start, then replaces the entire provider response/groups on success.
- A component regression verifies the first provider group disappears immediately when a second search starts and that only the second response renders afterward.
- The in-app browser session was unavailable, so no claim of visible-browser reproduction is made.

## Scope isolation

- WHO: unchanged and still strict.
- Auto Medical Knowledge: unchanged by this task; full backend coverage, including Auto, passed.
- PubMed FREE search: remains separate and covered by existing frontend/backend tests.
- Draft, import, provider settings, database models, migrations, and production data: unchanged by this task.

## Files changed by this audit

- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
  - removed the PubMed-only Guided legacy optimization;
  - clears prior provider results at search start;
  - defensively excludes unexpected REJECT results.
- `Frontend/src/lib/medicalKnowledgeApi.ts`
  - models `REJECT` at the untrusted response boundary so the frontend can filter it explicitly.
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
  - adds PubMed-only routing, exact rejected-title/badge, provenance, and provider-state replacement regressions;
  - moves legacy PubMed UI coverage to explicit FREE mode.
- `seasonal_disease_backend/tests/test_pubmed_runtime_relevance_audit_v1.py`
  - adds deterministic real-endpoint PubMed-only and PubMed+WHO integration regressions.
- This report directory and validation JSON.

## Validation

- Exact real-endpoint runtime regression: 2 passed.
- PubMed endpoint/provider focused group: 83 passed.
- PubMed+WHO Reviewed integration group: 53 passed.
- Shared Reviewed relevance unit tests: 14 passed.
- Frontend Medical Knowledge focused component: 123 passed.
- Full backend suite: 892 passed.
- Full frontend suite: 295 passed.
- TypeScript typecheck: passed.
- Vite production build: passed.
- `git diff --check`: recorded in the companion validation JSON after artifact creation.

Warnings were existing dependency/runtime deprecations; no test failures remain.

## Final conclusion

PASS. PubMed Guided now has one relevance path for both single-provider and multi-provider searches. The exact SARS-CoV-2 and smart-agriculture candidates are REJECT and absent, Plague+humidity is DIRECT, Plague vaccination is RELATED, WHO remains strict, Auto and DB/schema remain unchanged, and no commit or push was performed.
