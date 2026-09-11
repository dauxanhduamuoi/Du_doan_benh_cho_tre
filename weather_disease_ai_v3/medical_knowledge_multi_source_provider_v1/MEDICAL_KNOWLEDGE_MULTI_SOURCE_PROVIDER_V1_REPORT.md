# Medical Knowledge Multi-Source Provider V1 Report

## Status

**PASS** — provider abstraction, normalized evidence, explicit trust policy, provider-agnostic dedup foundation, PubMed/PMC integration, and additive V015 persistence are implemented. Existing Reviewed, Auto, Strict, Basic, Safe Template, publication, visibility, regeneration, and Parent behavior remain covered by regression tests.

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting commit: `fc01bc361c0cef0156daffc84fa2f5a90f5d8a05`
- Initial git status: clean
- Production data changed: no
- Production jobs retried: no

## Architecture audit

Before this change, `PubMedClient` was constructed independently by the Reviewed router, Auto worker, and service-status router. Reviewed and Auto passed `PubMedArticleRecord`/`ResolvedEvidenceContent` directly. `MedicalEvidenceSource.source_type` represented the provider (`PUBMED`, `WHO`, `CDC`, `OTHER`) rather than an independent source taxonomy. Auto qualification and Parent eligibility trusted the hard-coded classes `PUBMED`/`PMC`. Existing `MedicalEvidenceContent` rows were already append-only snapshots selected by content hash, and the PMC resolver already enforced allow-listed licenses with abstract fallback.

The existing relationship was confirmed and preserved:

- PubMed is the discovery/index provider.
- PMID lookup, PubMed ESearch/EFetch, query construction, ranking, and request throttling remain owned by the existing PubMed client.
- PMC is optional full-text enrichment reached through PMID → PMCID and EFetch; it is not a separate discovery provider.
- Unsafe, unavailable, or unlicensed PMC content falls back to the PubMed abstract under the existing policy.

## Provider boundary and registry

`MedicalEvidenceProvider` is a small protocol exposing a stable descriptor plus `search`, `lookup`, `fetch_many`, `enrich`, and `close`. Its V1 capabilities are `SEARCH`, `DIRECT_LOOKUP`, and `FULL_TEXT_ENRICHMENT`.

`MedicalEvidenceProviderRegistry` supports registration, deterministic descriptor listing, stable-ID lookup, duplicate rejection, clean unknown-provider errors, and lifecycle close. `create_medical_evidence_provider_registry()` is now the single production construction point. It registers only the real `PUBMED` adapter; there are no WHO, CDC, scraper, or fake production providers.

Reviewed search/import/lookup, Auto worker discovery, and the PubMed service-status check obtain PubMed through this registry. Existing legacy-client injection remains supported at the adapter edge for tests and compatibility.

## Normalized evidence and provenance

`NormalizedMedicalEvidence` is provider-neutral and immutable at the object boundary. It requires only:

- stable `provider_id`;
- provider-owned `external_id`;
- independent `source_kind`;
- title.

PMID, PMCID, DOI, journal/publisher, abstract, year, authors, language, canonical URL, and provider metadata are optional. Evidence snapshot fields include content kind/origin/text, retrieval time, truncation, license, provenance, and deterministic content hash.

The PubMed adapter maps ordinary articles to `RESEARCH_ARTICLE` and deterministic systematic-review/meta-analysis publication types to `SYSTEMATIC_REVIEW`. No AI classification was added. PubMed/PMC provenance retains PMID, PMCID, content origin, retrieval details, license fields, and allow-list decision. Existing immutable content rows continue to be reused by `(source_id, content_sha256)` and are never overwritten.

## Persistence and migration

V015 additively adds nullable `provider_id`, `external_id`, and `source_kind` columns plus lookup indexes to `medical_evidence_sources`. The legacy `source_type` field remains untouched for API and historical compatibility.

Backfill is deliberately conservative:

- known legacy `PUBMED`, `WHO`, and `CDC` source types map to the same provider ID;
- PubMed PMID maps to external ID;
- known PubMed rows map to `RESEARCH_ARTICLE`;
- ambiguous `OTHER` rows remain null rather than being guessed.

The migration is idempotent. SQLite-specific DDL is isolated in the migration; application repository and service logic use SQLAlchemy ORM/Core and do not depend on SQLite row IDs or PRAGMA behavior. A future SQL Server deployment needs the equivalent idempotent `ALTER TABLE`/index migration, without changes to provider or business services.

Validation against a temporary copy of the current local database succeeded twice: all 134 source rows, 15 Reviewed revisions, and 65 Auto revisions were preserved; all 134 certain PubMed rows were backfilled; foreign-key violations remained zero. The real `database.db` was opened read-only and was not migrated or modified.

## Dedup and trust policy

Normalized dedup now uses any available stable identity:

- PMID;
- PMCID;
- normalized DOI;
- canonical URL;
- provider ID + provider external ID.

It does not require PMID and retains identifiers from duplicate rows so transitive identity matches also collapse. Existing bounded Auto near-title filtering remains unchanged and separate.

Trust is explicit through `MedicalEvidenceTrustPolicy`. V1 allows only provider `PUBMED` with trust classes `PUBMED` or `PMC`. Being present in the registry does not confer trust. Auto pre-checks, persistence, Evidence Qualification, Safe Template eligibility, Reviewed draft source validation, and Parent Auto eligibility consume this policy rather than embedding WHO/CDC branches.

## Workflow integration and compatibility

- Reviewed guided/free search keeps the existing query builder and result semantics.
- Exact PMID lookup and source import keep their API contracts.
- Source Library selection and immutable PMC/abstract snapshot persistence are unchanged.
- Auto still enables only `PUBMED`, keeps the same search/enrichment limits, and makes no additional retries.
- Evidence Qualification receives persisted evidence derived from the normalized candidate and verifies canonical disease/factor, disease relevance, factor relevance, pediatric relevance, ownership, usable text, and explicit trust.
- Strict, Basic, Numeric Claim Contract V2, Safe Template rendering, tier priority, visibility, hide/unhide, and regenerate semantics were not changed.
- LLM tiers still receive only exact selected persisted evidence; no browsing, provider selection, provider calls, or tools were added to LLM access.
- Parent DTO and citation resolution were not changed. Existing historical rows remain readable through deterministic legacy fallbacks.

## Validation

Focused offline test scope:

- provider registry/descriptor and unknown provider;
- fake second provider without PMID;
- explicit non-trust and explicit policy opt-in;
- PubMed normalization, source kind, search, lookup, and call count;
- PMC full-text provenance/license and abstract fallback;
- typed configuration/rate-limit/timeout/malformed/unavailable failures;
- PMID, DOI, canonical URL, and provider/external-ID dedup;
- generic source persistence;
- V015 idempotence/backfill/foreign-key integrity;
- PubMed client, PMC parser/content license policy;
- Reviewed search/import/Source Library/Draft/Approve/Publish/Unpublish;
- Auto discovery, qualification, Strict/Basic/Safe Template/cooldown/visibility/regeneration;
- Parent reviewed/auto resolution and safe citations;
- service configuration and application startup.

Final focused result: `559 passed` (warnings are pre-existing deprecation warnings). Backend compile/import/startup sanity passed. `git diff --check` passed. Frontend was not changed, so frontend typecheck/tests were not applicable.

External calls during validation:

- Groq: 0
- PubMed: 0
- PMC: 0
- WHO: 0
- CDC: 0

## Files changed

- `seasonal_disease_backend/app/services/medical_evidence_provider.py`
- `seasonal_disease_backend/app/services/pubmed_evidence_provider.py`
- `seasonal_disease_backend/app/services/medical_evidence_provider_factory.py`
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- `seasonal_disease_backend/app/services/auto_evidence_discovery.py`
- `seasonal_disease_backend/app/services/auto_evidence_qualification.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_safe_fallback.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_worker.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_service.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_pubmed.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_service_status.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/migrations/v015_medical_evidence_providers.py`
- `seasonal_disease_backend/tests/test_medical_evidence_provider_architecture.py`
- this report and its validation JSON.

## Remaining V1 limitations

- The production registry intentionally contains only PubMed/PMC.
- Reviewed public endpoints and direct lookup DTOs remain PubMed-named and PMID-oriented because no second live provider exists yet.
- Persisted evidence content kinds/origins retain the currently used PubMed/PMC taxonomy. A live document provider must introduce only the concrete generic document/web content values it actually needs, with an additive/portable migration and license rules.
- Provider enable/disable settings and Admin UI are intentionally deferred; no fake WHO/CDC controls were added.
- No live provider smoke test was required or run. Manual testing is not required for V1 acceptance; an optional configured PubMed smoke may be run separately outside quota-free validation.

## Exact WHO Provider V2 extension steps

1. Implement a dedicated WHO adapter that satisfies `MedicalEvidenceProvider`; keep WHO transport, parsing, timeouts, and typed failure translation inside that adapter.
2. Assign stable `provider_id="WHO"`, declare only real capabilities, and normalize WHO document IDs/URLs into `NormalizedMedicalEvidence` without inventing PMID, PMCID, journal, or abstract.
3. Map real WHO documents deterministically to `GUIDELINE`, `TECHNICAL_REPORT`, `HEALTH_GUIDANCE`, or `OTHER`; do not use AI classification.
4. Implement bounded WHO document retrieval and an explicit WHO license/use policy. Preserve canonical URL, document identifier/version, retrieval time, language, content hash, license, and full provenance.
5. Add only the concrete generic evidence content kind/origin values required by the live WHO implementation, with an additive idempotent migration and SQL Server equivalent.
6. Register the WHO adapter in `create_medical_evidence_provider_registry()` only after it is functional; registration alone must not enable use.
7. Add `WHO` and its allowed trust classes to an explicit trust-policy configuration only after medical/product review.
8. Add provider enablement settings, then let Reviewed provider selection and Auto enabled-provider orchestration read those settings. Do not add UI toggles before the provider is live.
9. Add offline fixtures for WHO search/lookup/content/license/failure behavior, cross-provider DOI/URL dedup, persistence, qualification, generation ownership, and Parent-safe citations.
10. Run the same Reviewed, Auto multi-tier, migration, startup, foreign-key, and Parent regression suites with all live network calls disabled by default.
