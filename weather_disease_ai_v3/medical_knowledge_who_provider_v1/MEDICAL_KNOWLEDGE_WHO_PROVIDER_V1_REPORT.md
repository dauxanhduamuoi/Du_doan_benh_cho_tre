# Medical Knowledge WHO Provider V1 Report

## Status

**STATUS: PASS**

- Branch: `feature/medical-knowledge-v1-20260820`
- Actual starting commit: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Initial git status: clean
- Commit created: **NO**
- Push performed: **NO**
- Production data changed: **NO**
- All changes remain in the working tree for review.

## Implementation outcome

The existing provider abstraction and registry were reused. No second framework was created. The production registry now contains the real providers `PUBMED` and `WHO`.

`WhoMedicalEvidenceProvider` implements:

- stable provider ID `WHO`;
- display name `World Health Organization`;
- `SEARCH`;
- `DIRECT_LOOKUP` for the WHO REST publication UUID contract;
- normalization to the existing `NormalizedMedicalEvidence` contract;
- typed provider failures, bounded network reads, deterministic parsing and explicit trust/license policy.

It deliberately does **not** declare `FULL_TEXT_ENRICHMENT`. V1 does not download, parse, persist or claim HTML/PDF full text.

Registration remains separate from product enablement and trust:

- production registry: `PUBMED`, `WHO`;
- Auto default provider IDs: `PUBMED` only;
- Reviewed default provider IDs and trust policy: `PUBMED` only;
- registered provider does not become trusted merely by registration.

## Official WHO access verification

Only official WHO surfaces are used:

- [WHO Publications search](https://www.who.int/publications/b/search) exposes the search UI and its public route configuration. Its versioned first-party frontend invokes the relative `Publications` route with `term`, `sort`, `pageSize` and zero-based `pageNumber`. The adapter uses the resulting official same-origin path `/publications/b/search/Publications` and always sends `pageNumber=0` with `pageSize` capped at 25.
- [WHO Publications REST API help](https://www.who.int/api/hubs/publications/sfhelp) documents `GET /api/hubs/publications({key})`, the required `System.Guid` key, response status model, and publication fields including `SystemSourceKey`, `ItemDefaultUrl`, `IRISID`, `Copyright`, `Summary`, `WHOReferenceNumber`, `Title`, dates and download URL.
- [WHO Publications](https://www.who.int/publications) identifies WHO's publication and IRIS surfaces.

The search route was not guessed from a generic Sitefinity/OData convention. It was taken from WHO's own search-page configuration and first-party bundle, then verified with one bounded live call. No `$filter`/`$top` behavior was invented.

One limitation remains: the Biblio UI route is an official page-owned interface but does not have a standalone public API specification comparable to the REST detail API. If WHO changes the page contract, the adapter fails with typed bad-response/unavailable errors; it does not fall back to arbitrary scraping.

## Search and retrieval behavior

- Query input is required, whitespace-normalized and capped at 500 characters.
- Only topic-level terms are sent. The provider has no patient-record input and sends no name, date of birth, user ID, hospital ID or individual health data.
- Results are server-bounded to 1–25 records on the first page.
- Response timeout defaults to 15 seconds and is capped at 30 seconds.
- Response size defaults to 2,000,000 bytes and is capped at 5,000,000 bytes.
- Redirect following is disabled. Redirect responses are rejected; non-WHO redirect locations are explicitly identified as unsafe.
- Transport is fixed to `https://www.who.int`; credentials, userinfo, custom ports and arbitrary hosts are rejected.
- Only JSON or `+json` responses are accepted for the implemented routes.
- There are no adapter retries, preventing double-retry with orchestration.
- `429`, timeouts, 5xx, malformed/empty/oversized content, bad content types and invalid configuration map to the existing typed provider error hierarchy.

The optional live smoke was executed only after offline suites passed:

- provider calls: 1;
- query: `influenza humidity children`;
- requested results: 1;
- WHO total: 330;
- normalized returned: 1;
- first official identity: `73164`;
- first canonical URL: `https://www.who.int/publications/b/73164`;
- missing explicit item license produced no evidence content and trust class `UNTRUSTED`, as designed;
- no database write occurred.

## Normalization and identity

WHO records use the existing generic contract. PMID, PMCID, journal and PubMed abstract are not required.

Stable identity precedence is deterministic:

1. WHO response `Id`;
2. `SystemSourceKey` / `SourceKey`;
3. `WHOReferenceNumber`;
4. `IRISID`;
5. ISBN;
6. official canonical URL.

Canonical URLs must be HTTPS and use an allowlisted official host: `www.who.int`, `who.int` or `iris.who.int`. The provider never fetches a canonical URL supplied by a client.

Source-kind mapping uses only explicit metadata:

- systematic review / meta-analysis → `SYSTEMATIC_REVIEW`;
- guideline → `GUIDELINE`;
- technical or meeting report / exact report → `TECHNICAL_REPORT`;
- health guidance / guidance / fact sheet / manual → `HEALTH_GUIDANCE`;
- missing or unrecognized metadata → `OTHER`.

No LLM or title inference classifies document type. Publication date, year, language, authors/editors, publisher, DOI and official identifiers are preserved only when supplied.

Rich-text summary fields are parsed as text only. Script, style, navigation, footer, noscript and SVG content are excluded; whitespace is normalized. No JavaScript or browser rendering runs.

## Content and license/use policy

Official policy sources audited:

- [WHO copyright policy](https://www.who.int/about/policies/publishing/copyright)
- [WHO open-access policy](https://www.who.int/about/policies/publishing/open-access)
- [WHO website terms of use](https://www.who.int/about/policies/terms-of-use)
- [WHO linking guidance](https://www.who.int/about/policies/publishing/copyright/linking)

WHO explains that publications issued from 12 November 2016 are generally under CC BY-NC-SA 3.0 IGO, while older works were not retroactively reissued and third-party material may have separate rights. Therefore V1 does not infer storage rights from a public URL, WHO ownership or publication date.

Policy implemented:

- metadata, stable identity and official URL may be stored;
- a cleaned metadata summary is retained as bounded discovery metadata;
- evidence content is created only when the individual record explicitly carries the allowlisted `CC BY-NC-SA 3.0 IGO` marker or its canonical license URL;
- the stored evidence is a bounded summary excerpt, never a full document;
- unknown, missing, restricted or permission-required license metadata yields no `evidence_text`, no content kind/origin and trust class `UNTRUSTED`;
- V1 never persists HTML/PDF full text.

Concrete taxonomy additions are intentionally minimal:

- content kind: `OFFICIAL_SUMMARY_EXCERPT`;
- content origin: `WHO_PUBLICATIONS_API`.

For an accepted excerpt, provenance contains provider, provider ID, external ID, canonical official URL, retrieval surface, retrieval time, content policy, license status, allowlist result, metadata storage status and `full_text_stored=false`. The existing canonical SHA-256 behavior provides immutable snapshot identity.

## Trust, qualification and deduplication

The Auto trust policy explicitly permits only the pair `provider_id=WHO` and `trust_class=WHO`. The adapter helper assigns that class only when all of these hold:

- provider is WHO;
- content kind is `OFFICIAL_SUMMARY_EXCERPT`;
- origin is `WHO_PUBLICATIONS_API`;
- evidence text is non-empty;
- license URL is the allowlisted CC BY-NC-SA 3.0 IGO URL;
- provenance records `license_allowlisted=true` and `full_text_stored=false`.

Any failed condition produces `UNTRUSTED`. The Reviewed policy remains PubMed-only, so merely registering WHO does not expose it to the current Reviewed workflow.

Shared Evidence Qualification was not specialized for WHO. Tests prove that trusted WHO pediatric evidence can pass, while wrong disease, wrong factor, adult-only content, unusable content, untrusted class, ownership mismatch and conflicting evidence fail through the existing generic gates. WHO does not bypass pediatric relevance.

Generic dedup remains unchanged and is exercised for:

- WHO provider + external ID;
- canonical URL;
- DOI across WHO and another provider;
- distinct WHO documents;
- sources with no PMID.

## Persistence, migration and portability

WHO source rows persist with `source_type/provider_id=WHO`, generic external ID and source kind, while `pmid` remains null. Licensed excerpts persist in the existing immutable `medical_evidence_contents` repository.

Migration `v016_who_evidence_content.py` extends the two generic content taxonomy constraints. It does not add WHO-only columns or alter historical prose, publication pointers, jobs or visibility.

- SQLite: the migration-only implementation performs a bounded table rebuild because SQLite cannot alter named CHECK constraints in place. IDs and all columns are copied, indexes recreated, and foreign keys validated.
- SQL Server: named CHECK constraints are dropped/recreated in place using SQL Server DDL.
- Application/provider/repository logic remains SQLAlchemy and database-agnostic.

The migration test used an in-memory temporary SQLite database containing an existing content row and a revision reference. It ran V016 twice, preserved both rows/IDs and returned an empty `PRAGMA foreign_key_check`. No real local/business database was migrated.

## Regression validation

Primary focused command covered WHO, provider architecture, PubMed/PMC, persistence, Reviewed, Auto, Parent/publication, visibility, migration and startup:

`565 passed`.

After the final trust-policy separation and parser hardening, the directly affected WHO/provider/Reviewed subset passed `172` tests, then the complete focused command above was rerun:

`565 passed`.

Warnings were pre-existing dependency/deprecation warnings; no test failed.

Validated behaviors include:

- 57 WHO-specific offline cases, with the requested numbered 1–41 scenarios and additional migration/citation/security cases;
- PubMed ESearch/EFetch, direct PMID and PMC enrichment unchanged;
- abstract fallback and PMC license behavior unchanged;
- Reviewed source-library/draft/edit/approval/publication/unpublication paths unchanged;
- Auto Strict/Basic/Safe Template, retry/cooldown, regeneration and visibility behavior unchanged;
- Parent source/citation paths tolerate sources without PMID;
- temporary-database startup passed;
- frontend was not changed, so frontend tests were not applicable.

External runtime calls during tests:

- Groq: 0;
- PubMed: 0;
- PMC: 0;
- WHO: 0 offline + 1 isolated live smoke;
- CDC: 0.

## Remaining limitations

- WHO V1 supports official JSON metadata and explicitly licensed summary excerpts only; it intentionally has no HTML/PDF full-text ingestion.
- Search results may expose a Biblio numeric identity while the formally documented REST detail API uses a GUID. Search metadata remains persistable; detail enrichment occurs only when an official UUID is available in provider metadata or supplied to direct lookup.
- Many real search records do not expose item-level license metadata. Those remain metadata-only and untrusted instead of inheriting a broad website/publication assumption.
- WHO is registered but has no production Auto/Reviewed selection consumer until the settings task.

## Exact next step: Admin Medical Source Settings V1

The next task should:

1. Add a generic persisted provider-setting model keyed by stable `provider_id` and workflow (`AUTO`, `REVIEWED`), with independent enablement flags. Seed `PUBMED` enabled and `WHO` disabled; do not derive settings from registry membership.
2. Build the Admin API from `MedicalEvidenceProviderRegistry.list_descriptors()` plus persisted state. Return display name, real capabilities, enabled state and safe operational status; do not return internal exception stacks.
3. Add Admin UI toggles for PubMed/PMC and WHO. Keep future CDC extensible through registry descriptors rather than hardcoded two-provider UI logic.
4. Replace the current Auto construction point in `app/services/auto_medical_knowledge_worker.py`—which explicitly requests `registry.get("PUBMED")`—with an ordered provider-neutral orchestrator that receives enabled IDs. Preserve the current one-provider default and global search/content/call budgets.
5. Add a WHO topic query builder using canonical disease aliases, factor vocabulary and pediatric terms without PubMed MeSH syntax or patient data.
6. For WHO candidates, call `who_trust_class()` after normalization/enrichment and before selection. Never label metadata-only/unknown-license records as `WHO` trust class.
7. Extend Reviewed search with an explicit provider selector whose default remains PubMed. Route provider IDs through the registry; retain the existing PubMed API contract for compatibility.
8. Add a generic provider-neutral import/persistence service around the current repository methods, keeping exact `provider_id + external_id`, canonical URL, content hash and immutable snapshot behavior.
9. Define UI behavior for unavailable/rate-limited providers and record typed diagnostics without exposing raw HTTP detail.
10. Test independent settings, restart persistence, authorization, concurrent toggles, `[PUBMED, WHO]` orchestration, per-provider failure isolation, dedup across providers and no change to Parent/visibility/regeneration defaults.

## Final working tree

Final `git status --short`:

```text
 M seasonal_disease_backend/app/config.py
 M seasonal_disease_backend/app/main.py
 M seasonal_disease_backend/app/medical_knowledge_draft_schemas.py
 M seasonal_disease_backend/app/medical_knowledge_models.py
 M seasonal_disease_backend/app/services/medical_evidence_provider.py
 M seasonal_disease_backend/app/services/medical_evidence_provider_factory.py
 M seasonal_disease_backend/app/services/medical_knowledge_draft_service.py
 M seasonal_disease_backend/tests/test_medical_evidence_provider_architecture.py
?? seasonal_disease_backend/app/services/who_evidence_provider.py
?? seasonal_disease_backend/migrations/v016_who_evidence_content.py
?? seasonal_disease_backend/tests/test_who_evidence_provider.py
?? weather_disease_ai_v3/medical_knowledge_who_provider_v1/
```

No commit, push, tag, merge, reset or production-data mutation was performed.
