# Shared Reviewed Relevance V1 Report

## STATUS

PASS.

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting and final HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Initial git state: substantial pre-existing uncommitted Medical Knowledge work, including modified and untracked files.
- Final git state: the pre-existing work is preserved and the files listed below remain uncommitted alongside it.
- NO COMMIT.
- NO PUSH.
- No merge, rebase, reset, checkout-over, clean, discard, or unrelated revert.

Porcelain status summary recorded at audit start: `27 M`, `24 ??`. Final porcelain status summary after artifacts: `27 M`, `28 ??`. The four added untracked paths are the shared classifier, its two new test modules, and this report-artifact directory; other dirty paths existed before this task and were preserved.

## Old relevance architecture

PubMed and WHO correctly owned different retrieval strategies, but final relevance was inconsistent. PubMed query attempts supplied `DIRECT_TOPIC` or `RELATED_CONTEXT`, and those provenance labels could become final result labels even when normalized content did not match the disease. WHO query attempts separately enabled disease-and-factor gate flags. The Reviewed service contained the final text matcher, so query provenance and provider-specific flags affected final acceptance differently.

This allowed a candidate found by a PubMed “direct” query to be shown as direct despite missing the selected disease, while WHO rejected the equivalent normalized content.

## New architecture

The flow is now:

`Provider retrieval → NormalizedMedicalEvidence → ReviewedEvidenceRelevance → DIRECT / RELATED / REJECT → Reviewed UI / Source Library`

Module ownership is explicit:

- PubMed provider: PubMed syntax, MeSH/Title-Abstract queries, bounded Guided fallback, fetch, and normalization.
- WHO provider: official endpoint, bounded pagination, metadata transport, fetch, and normalization.
- `reviewed_evidence_relevance.py`: provider-neutral local text normalization, canonical disease/factor matching, pediatric signal tracking, and final classification.
- Reviewed service: orchestration, bounded retrieval, deduplication, ordering, diagnostics, and response assembly.
- Draft services: existing source usability, content, trust, provenance, pediatric safety, and 10-source rules.
- Auto services: existing unattended discovery and Auto Evidence Qualification; not replaced or modified by this layer.

The shared classifier has no HTTP/provider client, registry networking, database access, provider-ID branch, or special disease/factor example branch.

## Classification contract

- `DIRECT_TOPIC` (`DIRECT`): sufficient disease match and selected factor match on the same normalized candidate.
- `RELATED_CONTEXT` (`RELATED`): sufficient disease match but no sufficient selected-factor match.
- `REJECT`: no sufficient disease match. Factor-only, pediatric-only, and wrong-disease records are rejected.

Query level remains diagnostic retrieval provenance. It cannot override normalized content. A direct PubMed query does not make missing-disease content direct, and a related query cannot make wrong-disease content relevant.

## Deterministic matching

The classifier uses only already-normalized local fields: title, abstract/summary, safe evidence excerpt, publisher/journal, and bounded explicit provider metadata. It performs Unicode NFKC normalization, `casefold`, punctuation and hyphen normalization, whitespace normalization, and whole normalized phrase boundaries.

Disease terms come from the current canonical Reviewed request context and the existing deployed catalog alias builder. Factor terms come from the existing canonical factor vocabulary plus the existing Reviewed-only extensions such as humidity `moisture`. No production example values are hardcoded.

Metadata traversal is bounded to 64 string leaves, three nested levels, 4,000 characters per metadata string, and 50,000 combined semantic characters.

## Pediatric role

The classifier separately reports `PEDIATRIC_MATCH` or `UNKNOWN`. Pediatric text does not decide `DIRECT`, `RELATED`, or `REJECT`; those represent disease/factor relevance. Existing downstream Draft pediatric safety remains authoritative and unchanged.

## PubMed integration

PubMed retains its three provider-owned Guided retrieval levels:

1. disease + factor + pediatric;
2. disease + factor;
3. disease + pediatric/context.

Every normalized candidate from every level now passes through the shared classifier. SARS-CoV-2 temperature and smart-agriculture humidity fixtures are rejected for a Plague/humidity topic; Plague/humidity is direct; Plague vaccination and pediatric Plague without humidity are related.

Direct retrieval attempts remain ahead of the related fallback, but their query labels are not final relevance truth.

## WHO integration

WHO retains its official search endpoint, zero-based progressive pagination, current page/raw budgets, cross-page deduplication, partial-failure handling, disease-anchored query construction, and trust/license rules.

The old WHO final gate flags and the Reviewed service's old matcher were removed. WHO normalized records now use the same final classifier as PubMed. WHO disease-and-factor is direct, disease-only is related, and child/factor-only or child-only material is rejected.

## Ordering and N semantics

`N` remains the maximum visible accepted results per provider, with `DIRECT + RELATED` counting together. Direct candidates are considered first within a fetched batch, direct-oriented retrieval attempts are completed before the related fallback can fill the remaining display target, and the final stable order is DIRECT first then RELATED while preserving provider order within each class. Rejected candidates never enter the normal result list.

## Future provider acceptance

A fake `FAKE_CDC` provider uses the existing provider registry and normalized evidence contract. Without any CDC branch in the classifier:

- disease + factor → DIRECT;
- disease only → RELATED;
- factor only/wrong disease → REJECT.

Identical semantic content from PubMed, WHO, and fake CDC produces identical classifications.

## Diagnostics and frontend

Provider and query-attempt diagnostics now include direct, related, and rejected counts in addition to raw/normalized/retrieval diagnostics. Technical details remain collapsed and expose no provider body or secret.

The normal UI shows only accepted sources with distinct badges:

- `Bằng chứng trực tiếp`
- `Tài liệu liên quan`

Provider tab counts use final visible accepted results. Frontend coverage verifies badges, direct-before-related order, rejected content absence, diagnostics, provider tabs/selections, mixed-provider import, and the unchanged Draft cap through the existing component suite.

## Source Library, Draft, and Auto isolation

Both DIRECT and RELATED accepted records can still be selected and stored in the Topic Source Library. Relevance classification is transient; it does not make a source Draft-eligible. Existing content availability, provider trust, WHO license, pediatric support, provenance, ownership, and maximum 10 exact Draft-source rules are unchanged.

Auto discovery, Auto Evidence Qualification, Strict, Basic, Safe Template, numeric claims, provider budgets, Parent resolution, visibility, and regeneration were not changed. Auto focused regression passed.

## Database and portability

- Database/schema change: none.
- Migration added by this task: none.
- Production DB/data write: none.
- SQLite-specific business logic: none.
- SQL Server portability: preserved.
- Provider settings and routing: unchanged.

## Files changed by this task

- `seasonal_disease_backend/app/services/reviewed_evidence_relevance.py` — new shared classifier.
- `seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py` — shared classification integration, diagnostics, filtering, and ordering.
- `seasonal_disease_backend/app/services/medical_evidence_provider.py` — removed obsolete WHO final-gate flags from query provenance.
- `seasonal_disease_backend/app/services/who_evidence_provider.py` — removed obsolete final-gate flags; retrieval/query behavior retained.
- `seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py` — additive direct/related/rejected diagnostics.
- `Frontend/src/lib/medicalKnowledgeApi.ts` — matching DTO fields.
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx` — distinct related badge and collapsed diagnostics.
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx` — UI regression updates.
- `seasonal_disease_backend/tests/test_shared_reviewed_relevance_v1.py` — 14 classifier tests.
- `seasonal_disease_backend/tests/test_shared_reviewed_relevance_integration_v1.py` — 5 provider integration tests.
- Existing Reviewed execution/search/bounded fixtures were updated to assert the new shared semantics.

## Validation

- Shared classifier unit tests: 14 passed.
- New shared integration tests: 5 passed.
- Shared + Reviewed integration group: 86 passed.
- Reviewed/WHO/PubMed/Library/Settings focused group: 307 passed.
- Auto focused regression: 221 passed.
- Frontend focused component: 120 passed.
- Full backend: 890 passed.
- Full frontend: 292 passed.
- TypeScript typecheck: passed.
- Production build: passed.
- `git diff --check`: passed; only existing line-ending notices were emitted.

External calls: PubMed 0, WHO 0, Groq 0, CDC 0.

## Remaining limitations

Classification is intentionally deterministic and lexical. It can only recognize disease aliases and factor terms present in the canonical local context/vocabulary and normalized metadata supplied by a provider; it does not infer unlisted medical synonyms or semantic relationships. Provider retrieval ranking still determines which candidates enter bounded evaluation. These limits avoid LLM/network classification and keep behavior auditable.

Final repository state remains intentionally dirty and uncommitted. NO COMMIT and NO PUSH were performed.
