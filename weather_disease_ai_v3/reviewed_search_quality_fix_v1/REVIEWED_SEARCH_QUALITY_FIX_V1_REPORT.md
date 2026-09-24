# Reviewed Medical Knowledge — Multi-Provider Search Quality Fix V1

Date: 2026-09-13
Branch: `feature/medical-knowledge-v1-20260820`
Validation topic: disease `Plague`, weather factor `humidity`, providers `PUBMED` and `WHO`, requested limit `N=10` per provider.

## Outcome

The Reviewed Medical Knowledge search now keeps disease/factor relevance ahead of result count. PubMed uses a bounded, deterministic three-level fallback plan when the strict query cannot supply enough results. WHO keeps the disease anchor in its query and applies a deterministic local disease-and-factor relevance gate before results reach the UI.

The response and admin UI expose direct/contextual provenance plus raw, normalized, relevant, and per-attempt counts. Empty successful searches remain distinct from provider failures. Provider tabs and the per-provider limit contract are preserved.

No database migration or schema change was introduced. Draft eligibility, WHO trust/license handling, PubMed FREE search, direct PMID lookup, and Auto Medical Knowledge behavior were not relaxed or redesigned.

## Root-cause audit

### PubMed zero-result behavior

The existing Guided query builder generated this strict conjunction for the exact validation topic:

```text
("Plague"[Title/Abstract]) AND ("humidity"[Title/Abstract]) AND ("Infant"[MeSH Terms] OR "Child"[MeSH Terms] OR "Adolescent"[MeSH Terms] OR "pediatric"[Title/Abstract] OR "paediatric"[Title/Abstract])
```

Before this fix, Reviewed search executed only that one query. It did not have a post-normalization relevance filter capable of deleting records, and it did not run a broader fallback. One isolated live PubMed ESearch on 2026-09-13 returned `provider_match_count=0` and `returned_id_count=0`. Therefore, the observed zero starts at the provider result for the strict conjunction; it is not a merge, normalization, filtering, or API serialization regression.

### WHO irrelevant-result behavior

The shared alias builder intentionally discarded most one-word disease aliases. In the Reviewed WHO path this removed `Plague`, leaving a query equivalent to:

```text
humidity relative humidity absolute humidity children pediatric
```

The Reviewed orchestration then accepted normalized WHO search records without a local topic relevance gate. Consequently, child-related results could pass even when neither plague nor humidity was present as the complete topic.

This fix preserves explicit, validated Reviewed disease terms when constructing the WHO query. For the validation topic the query is now:

```text
Plague humidity relative humidity absolute humidity children pediatric
```

WHO candidates must additionally match at least one requested disease term and one factor-vocabulary term in locally available title/summary text. This is deterministic and does not use an LLM, scrape pages, or make extra WHO requests. WHO transport, official-origin validation, metadata-only import behavior, trust class, and license rules are unchanged.

## Implemented search strategy

PubMed attempts are ordered by evidence quality and hard-bounded to three:

1. `DIRECT_DISEASE_FACTOR_PEDIATRIC` — disease + factor + pediatric constraint; classified `DIRECT_TOPIC`.
2. `DIRECT_DISEASE_FACTOR` — disease + factor; classified `DIRECT_TOPIC`.
3. `RELATED_DISEASE_PEDIATRIC` — disease + pediatric constraint; classified `RELATED_CONTEXT`.

Fallback runs only while the provider has fewer than its effective limit. It stops immediately at `N`, deduplicates strong identities across attempts, and retains direct results before contextual results. Returning fewer than `N` is valid; the implementation does not pad results with unrelated evidence.

WHO has one `DIRECT_DISEASE_FACTOR` attempt. It keeps the disease anchor and filters locally for both disease and factor. A raw fixture transition of 10 candidates to 2 relevant results is reported honestly as raw `10`, normalized `10`, relevant `2`, returned `2`.

## API and UI diagnostics

Each provider group now reports:

- requested and effective limits;
- returned, raw/fetched, normalized, and relevant counts;
- direct and contextual counts;
- provider status (`SUCCESS`, `NO_RESULTS`, or `PROVIDER_ERROR`);
- every executed query attempt, its relevance class, provider match count, fetched/normalized/relevant counts, status, and optional warning.

Each result carries `relevance` and `query_level`. The admin UI presents direct versus related-context badges and keeps raw query/count details under technical disclosure. A partial fallback failure is visible without discarding records already collected from successful earlier attempts.

## Safety and compatibility checks

- The requested `N` remains a limit per provider, not a total shared across providers.
- Provider groups/tabs remain independent; cross-provider results are not silently collapsed inside a provider group.
- `NO_RESULTS` means successful attempts produced no accepted records. `PROVIDER_ERROR` means no records survived and a provider attempt failed.
- WHO metadata-only records remain ineligible for draft generation unless the existing official-origin and allowlisted-license content path makes them eligible.
- PubMed FREE search still executes the user's exact query once.
- Direct PMID lookup is unchanged.
- Auto Medical Knowledge query generation, budgets, and behavior are unchanged.
- No patient data, production data, background jobs, or database writes were used during validation.
- No commit, push, reset, merge, rebase, or discard operation was performed.

## Validation evidence

All validation was run after implementation.

| Check | Result |
|---|---:|
| New backend quality-fix tests | 19 passed |
| Existing focused backend provider/PubMed/WHO tests | 120 passed |
| Full backend suite | 838 passed |
| Full frontend suite | 287 passed |
| Frontend TypeScript typecheck | passed |
| Frontend production build | passed (2309 modules transformed) |
| `git diff --check` | passed; only existing line-ending conversion notices |
| Live PubMed searches | 1 isolated ESearch |
| Live WHO calls | 0 |
| Live Groq calls | 0 |

The new backend tests cover strict-query construction, fallback trigger and stop rules, the three-attempt ceiling, cross-attempt deduplication, direct-before-context ordering, WHO disease/factor filtering, raw-to-relevant counts, empty-versus-error status, per-provider limits, draft safety, exact FREE search, direct PMID compatibility, and Auto query compatibility. Frontend tests cover relevance labels/counts and technical diagnostics disclosure.

## Files central to this fix

- `seasonal_disease_backend/app/services/pubmed_query_builder.py`
- `seasonal_disease_backend/app/services/pubmed_evidence_provider.py`
- `seasonal_disease_backend/app/services/who_evidence_provider.py`
- `seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py`
- `seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py`
- `seasonal_disease_backend/tests/test_reviewed_search_quality_fix_v1.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
