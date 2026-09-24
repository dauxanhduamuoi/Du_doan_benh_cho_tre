# Reviewed Medical Knowledge — Disease–Factor Relation Context V1

Date: 2026-09-23
Branch: `feature/medical-knowledge-v1-20260820`
Starting and final HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
Status: **PASS**

## Git and production integrity

The initial worktree was substantially dirty with stacked Medical Knowledge work: tracked frontend/backend files were modified and many provider, migration, test, fixture and report paths were untracked. The task began only after recording `git status --short`, branch and HEAD. No existing change was reset, discarded, overwritten from Git, cleaned, committed or pushed.

The final worktree remains intentionally dirty and uncommitted. At final inspection it contained 30 modified tracked files and 43 untracked status entries, most of which predated this task. The additional relation-specific files and changes are listed below. No production database was read or written.

**NO COMMIT. NO PUSH.**

## Root-cause audit

The old Reviewed final classifier did exactly this:

```text
STRONG disease + factor anywhere in semantic evidence -> DIRECT
```

`ReviewedSemanticEvidence` preserved field boundaries but did not expose sentence/clause units. Factor matching was a single article-wide `contains()` scan. There was no `DiseaseFactorRelationMatcher`, proximity rule, clause reasoning or incidental-context result.

For PMID 30017148, the user-authorized single EFetch established the complete mechanism:

- exact title: `Dual route vaccination for plague with emergency use applications.`
- disease evidence: PubMed article-owned MeSH includes `Plague`, `Plague Vaccine` and `Yersinia pestis`; the title/abstract also contain genuine Plague concepts;
- factor evidence: `abstract_text` contains `75% relative humidity for 6 weeks`;
- actual local context: exceptional stability of the primary vaccine formulation in vialled form under thermostressed conditions, followed by the statement that no cold chain is needed for storage or distribution;
- article-owned keywords: Dual route, Emergency use, Mucosal, Plague, Protection, Systemic, Vaccine;
- provenance: provider, PMID and PMCID only; no query/request contamination was observed.

The old result was DIRECT because genuine disease evidence and the humidity token independently existed in the article. It never asked what humidity described. The new result is disease=STRONG, factor=true in abstract, relation=INCIDENTAL, reason=`STORAGE_FORMULATION_CONTEXT`, final=RELATED.

The EFetch was one POST for PMID 30017148 after offline relation tests passed, with retries disabled, no search, enrichment or persistence. The original response SHA-256 is `d87bc9b2dac00080c4a81b570f5fb40c3f3005aad3c1766ade0f01a8507f5004`. The complete response is archived as `tests/fixtures/pubmed_30017148_efetch.xml`; its newline-normalized fixture SHA-256 is `c51476f261b3d7816ec15aa1517c87621c927a299c88899cb0aa6a4692a3a733`. The bounded normalized audit is in `pubmed_30017148_exact_audit.json`.

## New architecture and ownership

The existing architecture remains intact and gains one explicit stage:

```text
Provider -> NormalizedMedicalEvidence -> ReviewedSemanticEvidence
         -> DiseaseConceptMatcher -> ReviewedFactorMatcher
         -> DiseaseFactorRelationMatcher -> ReviewedEvidenceRelevance
         -> DIRECT / RELATED / REJECT
```

- `reviewed_semantic_evidence.py` owns normalization and bounded article-owned semantic units. It labels title, abstract, evidence excerpt, author keyword, article MeSH and article subject units. Abstract/excerpt text is segmented at sentence and selected scientific clause boundaries. It returns bounded match spans with field, unit index and matched term. It does not traverse arbitrary metadata.
- `disease_concept_matcher.py` still decides whether the article is about the disease and now retains bounded match spans. The canonical ambiguity configuration gained general clinical suffixes such as epidemiology, outbreak, incidence, risk and transmission. It contains no disease-ID branch.
- `reviewed_factor_matcher.py` locates configured factor terms and returns a typed factor result plus match spans. It reuses the existing Reviewed factor vocabulary.
- `disease_factor_relation_matcher.py` owns the new provider-neutral relation decision: `RELATED_TO_TOPIC`, `INCIDENTAL` or `UNRESOLVED`.
- `reviewed_evidence_relevance.py` remains the single final Reviewed classifier and combines disease, factor and relation results.

Internal diagnostics now retain `factor_match_field`, `relation_status` and bounded `relation_reason`. The public result DTO/UI was deliberately not expanded: existing DIRECT and RELATED badges remain sufficient, and raw provider payloads/large abstracts are not exposed as diagnostics.

## Relation model

The policy is centralized around semantic roles, not disease names or providers.

`RELATED_TO_TOPIC` can be established by:

- local outbreak/incidence/occurrence/prevalence/risk/transmission/epidemiology/infection/severity/timing/seasonality/mortality context;
- vector survival/development/activity/abundance context;
- pathogen, host or reservoir ecology/survival/growth context;
- disease and factor occurring together in a non-ancillary title;
- both disease and factor being genuine article-owned controlled topic terms.

`INCIDENTAL` covers bounded storage/formulation/stability/shelf-life/cold-chain/manufacturing context and procedural assay/sample/incubation/calibration context. An immediately preceding clause is considered for ancillary context, which is important when a long scientific sentence places the numeric humidity condition in a separate parenthetical clause.

`UNRESOLVED` is used when the factor exists but deterministic local evidence does not prove a topic relationship. It is conservatively displayed as RELATED, not DIRECT.

Final contract:

- STRONG disease + factor + RELATED_TO_TOPIC → DIRECT;
- STRONG disease + factor + INCIDENTAL/UNRESOLVED → RELATED;
- STRONG disease without factor → RELATED;
- WEAK/NONE disease → REJECT;
- factor alone → REJECT.

No causal claim is introduced. DIRECT means directly relevant to the disease–factor topic, including non-causal epidemiological associations and vector/pathogen ecology.

## Regression outcomes

- PMID 30017148 actual archived PubMed record: RELATED. Exact PMID still returns external_id/PMID `30017148` with one EFetch and no Guided fallback.
- PMID 32517609-like realistic climate/outbreak evidence: DIRECT. The title establishes plague epidemiology and the abstract locally relates relative humidity to occurrence, timing and severity of outbreaks.
- Flea vector development/survival under temperature/humidity: DIRECT.
- Disease-only plague guideline/vaccination evidence: RELATED.
- Factor present but relation unproven: RELATED with `UNRESOLVED`.
- SARS-CoV-2/Mpro humidity fixture: REJECT.
- Actual archived Smart Agriculture PMID 38257588 fixture: REJECT. Its exact PMID path remains visible independently.
- Equivalent PUBMED, WHO and FAKE_CDC normalized evidence produces the same relation/final classification.
- Query provenance and arbitrary provider metadata cannot produce a factor or relation.
- A long sentence mentioning outbreaks before a separate vaccine-stability humidity clause remains RELATED.

## Preserved boundaries

- PubMed Guided query construction, attempts, fallback and candidate budgets: unchanged.
- PubMed FREE search: unchanged.
- WHO Guided query, paging and result budgets: unchanged.
- Exact PMID service/UI semantics: unchanged; exact identity is never hidden by Guided relevance.
- WHO GUID exact lookup and identifier contract: unchanged.
- Source Library identity, topic links, metadata-only handling and dedup: unchanged.
- Draft trust, licensing, pediatric safety, eligibility and 10-source maximum: unchanged.
- Auto discovery, Evidence Qualification, Strict/Basic/Safe Template, numeric claims, job state, parent visibility and regenerate: unchanged.
- Database models/schema and migrations: unchanged by this task.
- No SQLite-specific business logic was added; SQLAlchemy persistence and SQL Server portability remain unchanged.
- Frontend production files: unchanged by this task. Existing badges already render DIRECT and RELATED correctly.

## Files changed by this task

- `seasonal_disease_backend/app/services/reviewed_semantic_evidence.py`
- `seasonal_disease_backend/app/services/disease_concept_matcher.py`
- `seasonal_disease_backend/app/services/reviewed_disease_concepts.json`
- `seasonal_disease_backend/app/services/reviewed_factor_matcher.py` (new)
- `seasonal_disease_backend/app/services/disease_factor_relation_matcher.py` (new)
- `seasonal_disease_backend/app/services/reviewed_evidence_relevance.py`
- `seasonal_disease_backend/tests/test_disease_factor_relation_matcher_v1.py` (new)
- `seasonal_disease_backend/tests/fixtures/pubmed_30017148_efetch.xml` (new)
- this report directory and its validation/audit JSON files (new)

No provider adapter, search orchestration, exact lookup service, frontend component, DB model or migration was changed for this task.

## Validation

| Validation | Result |
| --- | --- |
| New relation unit tests before live call | 15 passed |
| Final relation unit tests | 18 passed |
| Shared relevance + PubMed real-title + exact-identity focused group | 73 passed before final bounded refinements |
| Final Reviewed relation/shared/PubMed/WHO/provider focused group | 141 passed |
| Provider/retrieval/exact/import focused group | 295 passed |
| Auto-focused regression | 202 passed |
| Full backend suite, once | 946 passed; 2829 existing warnings |
| Full frontend suite, once | 305 passed across 13 files |
| TypeScript typecheck, once | Passed |
| Production frontend build, once | Passed; 2310 modules |
| Final diff check, once | Recorded in validation JSON after report creation |

Live calls for this task: PubMed 1 EFetch/1 HTTP request; WHO 0; Groq 0. No production DB write occurred.

## Maintainability review and remaining limitations

Production code contains none of the three test PMIDs, test article titles, disease ID 9, provider-specific relation conditions, or a `Plague + humidity` branch. Normalization and segmentation are not duplicated in providers. Relation logic does not call retrieval, exact lookup, Draft or Auto code and creates no circular import.

The matcher is intentionally deterministic and conservative. Scientific phrasing outside the centralized role vocabulary may be downgraded from DIRECT to RELATED; the article remains visible. This is the intended safe failure mode. PMID 32517609 was validated with the realistic evidence specified by the task, not an additional live fetch, because the live policy allowed only the vaccine EFetch and that call was sufficient to close the reproduced bug.

**NO COMMIT. NO PUSH.**
