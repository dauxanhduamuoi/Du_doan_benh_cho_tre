# Reviewed disease concept matching + exact lookup safety V1

Date: 2026-09-16. Branch: `feature/medical-knowledge-v1-20260820`.
HEAD remained `dca4c7d1d79ab3863601fb24691acafaec965085`.

## Outcome and completed follow-up audit

**Overall status: PASS.** Implementation and offline validation pass. The previously missing exact PubMed normalized metadata for Smart Agriculture was retrieved and inspected in the user-authorized follow-up. Its article-owned MeSH is now verified as empty; its article keywords and complete abstract are preserved in the audit snapshot and replayable EFetch fixture.

The original single live PubMed search unexpectedly returned two versions of the Mpro title (published article and preprint), not both distinct requested titles. Work initially stopped with PARTIAL_AUDIT. The user then explicitly approved exactly one additional EFetch for PMID 38257588 ("Tôi cho phép"). That one POST completed successfully at 2026-09-16T12:34:30.730316+00:00, with retries disabled and no ESearch, enrichment, or fallback. No production implementation change was needed after inspecting the real article.

No commit, push, reset, discard, migration, production DB write, or Groq call was performed. Earlier dirty work, including existing migration files, remains intact.

## First audit: actual observations

Before changing the implementation, the existing runtime/PubMed parser tests passed: 23 tests. Repository searches found only title-only fixtures for the two bad papers; those fixtures did not reproduce the abstract-word ambiguity.

The production `PubMedClient.search` and `normalize_pubmed_record` were then called once, without persistence, retries or enrichment, using:

```text
(temperature-dependent conformational ensemble[Title] AND SARS-CoV-2[Title]) OR (Edge IoT Prototyping[Title])
max_results=2
```

ESearch count was 3; EFetch returned PMIDs 36071812 and 33972941. This is one logical search operation, comprising two HTTP requests (ESearch + EFetch). The earlier malformed shell invocation exited with SyntaxError before any network call.

| Article | Disease-word match source | Humidity match source | Structured metadata actually inspected |
| --- | --- | --- | --- |
| Mpro, PMID 36071812, DOI 10.1107/S2052252522007497, PMCID PMC9438506 | `abstract_text`, ordinary-language verb in “continues to plague the globe” | `abstract_text`, high-humidity crystal structures | `mesh_terms=[]`; `publication_types=[Journal Article]`; `languages=[eng]`; empty journal identifiers |
| Mpro preprint, PMID 33972941, DOI 10.1101/2021.05.03.437411, PMCID PMC8109201 | Same verb use in `abstract_text` | `abstract_text` | `mesh_terms=[]`; publication types Preprint + Journal Article; language eng |
| Smart Agriculture, DOI 10.3390/s24020495, PMID 38257588, PMCID PMC10818290 | Actual EFetch `abstract_text`: “drones for plague detection” | Same actual `abstract_text`: “humidity/temperature/soil sensors” | `mesh_terms=[]`; author keywords: Industry 4.0, analytics, model-driven development, smart agriculture; publication type Journal Article; language eng; empty journal identifiers |

The exact titles supplied in the task contain neither a Plague disease phrase nor humidity. For Mpro the observed journal is IUCrJ (published version) / bioRxiv (preprint). Provider metadata held provider, PMID, DOI, PMCID, publication types, languages, journal identifiers, MeSH; provenance held provider, PMID and PMCID. No request query or disease/factor aliases appeared in the inspected Mpro metadata. Author keywords were **not extracted by the old parser**; their absence in its normalized output does not prove the original XML lacks keywords.

The old classifier independently matched `plague` and humidity in the abstract and could therefore label the Mpro article DIRECT despite its actual SARS-CoV-2 subject. The authorized EFetch now confirms the same lexical mechanism in the real agriculture record, not just a publisher-derived fixture. Its title, MeSH and author keywords supply neither disease-word nor humidity matches: both matches originate in `abstract_text`. The normalized journal is `Sensors (Basel, Switzerland)`, year 2024, provider/external_id/PMID are PUBMED/38257588/38257588. Provenance contains only provider, PMID and PMCID. No search query, requested disease/factor or query level was present. Publisher evidence: [official Smart Agriculture article](https://www.mdpi.com/1424-8220/24/2/495). Published Mpro identity: [PubMed 36071812](https://pubmed.ncbi.nlm.nih.gov/36071812/).

The current classifier evaluated the complete real agriculture response as disease_strength=WEAK, disease_match=false, factor_match=true, classification=REJECT. Exact lookup nevertheless returned that same publication with the requested PMID. Evidence is saved in `pubmed_38257588_exact_audit.json`; the complete XML is replayed by `tests/fixtures/pubmed_38257588_efetch.xml`. Original transport SHA-256: `207b10307bdf4279fd1a22565d9b4b7cf46220d270d6360311bc44dc60930bf5`. The local fixture normalizes its final newline; its separate SHA-256 is recorded in the snapshot.

There was also a potential contamination route: `_metadata_text` recursively flattened arbitrary provider metadata, and journal/publisher text was semantic input. It is removed. Contamination was not observed in the inspected Mpro or agriculture records and is not falsely reported as their actual cause.

## Semantic boundary and disease concept model

New responsibilities are separate:

- Provider normalizers populate `article_mesh_terms`, `article_subject_terms`, `article_keywords` on `NormalizedMedicalEvidence`.
- `ReviewedSemanticEvidence` uses only title, abstract/official summary, evidence excerpt, and those explicit article-owned term fields. Field boundaries are preserved; adjacent fields cannot accidentally form a disease phrase.
- PubMed maps parser-produced article MeSH descriptors and author keywords. The parser now extracts `MedlineCitation/KeywordList/Keyword`. Raw nested metadata, publisher/journal, identifiers, URLs, query strings, pagination, diagnostics and request MeSH are excluded.
- WHO continues to supply official title/summary/excerpt. Its generic `Tag` metadata is not silently promoted into medical headings.
- `DiseaseConceptMatcher` returns STRONG, WEAK or NONE, independently of provider identity. An exact article-owned medical heading can establish STRONG; an unambiguous disease phrase can also establish STRONG. A configured ambiguous alias requires an adjacent clinical phrase or exact medical heading. A bare author keyword is not a medical heading.
- `ReviewedEvidenceRelevance` retains the existing factor vocabulary and computes STRONG + factor = DIRECT_TOPIC, STRONG without factor = RELATED_CONTEXT, WEAK/NONE = REJECT. Factor-only candidates cannot pass.

Catalog audit: both the legacy V2 catalog and deployed `weather_disease_ai_v3/data/processed/disease_catalog.csv` expose group/ICD labels including group 9, A20, `Dịch hạch - Plague`; `build_disease_aliases` supplies catalog-label aliases, not a validated pathogen ontology. No pathogen alias or new medical synonym was invented. `reviewed_disease_concepts.json` is a Reviewed-only ambiguity annotation for the existing canonical label, with generic clinical phrase templates. No disease-ID, provider-ID or title-specific conditional exists in the matcher. An injected second ambiguity configuration is tested to demonstrate the generic mechanism.

This is a bounded deterministic disambiguation layer, not a general natural-language understanding claim. The current ambiguity inventory is intentionally small. Other ambiguous catalog terms need reviewed annotations; conservative rejection of bare unstructured disease words is expected. Positive paging/ranking fixtures now explicitly say `Human plague`, use a clinical phrase, or provide an article-owned heading. Their expected paging/count behavior was not weakened to force passes.

The initial realistic regression fixtures are shortened/adapted from the inspected abstract mechanisms; they are not falsely labelled complete archived provider responses. The authorized follow-up adds a separate test against the complete archived agriculture EFetch response, through the real XML parser and PubMed exact adapter. The production PubMed adapter + actual Reviewed HTTP route also exercise abstracts containing both terms, in PubMed-only and mixed-provider configurations.

## Exact identity workflows

Guided search still discovers and filters; exact lookup is not passed through the relevance gate. The new optional `ExactMedicalEvidenceProvider` protocol and descriptor `exact_identifier_types` let future providers define their exact grammar without modifying shared relevance. `/api/medical-knowledge/providers/lookup` is staff/admin protected and returns `lookup_mode=EXACT`, `relevance=EXACT_LOOKUP`, `query_level=EXACT_IDENTIFIER`.

### PMID

The existing PMID input and endpoint are preserved. The PubMed provider's `lookup_exact` validates the numeric grammar and verifies normalized provider, external_id and PMID. The PMID service independently verifies returned identity, including legacy adapter paths. The frontend verifies envelope/result PMID against the requested PMID, clears prior Guided groups, and displays the exact article even when its topic is unrelated. Its helper explicitly distinguishes a reference from AI Draft eligibility.

Invalid request syntax returns validation error (422); missing PMID returns 404. Identity mismatch returns provider error (502), not an alternative article. No keyword search or Guided fallback occurs. Import rejects substituted/unrequested PMID records before persistence.

### WHO identifier contract

| Identifier form | Exact support | Behavior |
| --- | --- | --- |
| REST publication GUID/UUID | Yes, offline contract verified | Bounded `GET /api/hubs/publications({guid})`; response must contain the same valid `Id`; no manufactured identity; official canonical URL required |
| Official canonical publication URL | No | No verified URL-to-REST-GUID resolver exists here; rejected before network I/O |
| Numeric Biblio/search ID, e.g. 73164 | No | Not interchangeable with a REST GUID; rejected before network I/O |
| Search-result external_id | Only if it is itself a supported REST GUID | No assumption that every result has a REST key |
| WHO reference number, ISBN, IRIS identifier, arbitrary URL | No | No guessed conversion or scraping |

The distinction follows the existing provider's official [WHO REST help contract](https://www.who.int/api/hubs/publications/sfhelp), also audited in the prior local provider reports. No new live WHO lookup was needed or performed; successful lookup of a real current WHO GUID from this environment is **not** claimed. The new exact path is verified with deterministic transport fixtures for matching GUID, uppercase normalization, mismatch/missing Id, unrelated content, 404, unsupported identifiers and HTTP endpoint validation.

The UI exposes GUID only when WHO is enabled for Reviewed. It renders unrelated exact publications, supports reference import, guards response identity, clears stale topic results and reports unsupported identifiers clearly. No URL/numeric lookup UI is offered. The provider's legacy `lookup` behavior remains for existing Auto/enrichment compatibility, but the new `lookup_exact` never enters its non-GUID search fallback. Reviewed import prefers the exact method where available.

## Source Library, Draft, Auto and DB

Exact PMID and Guided/provider import share the existing source/link paths. Tests prove one source and topic link across those paths. WHO GUID import preserves its identity, reuses an existing topic reference on repeat, and keeps metadata-only content Draft-ineligible. Existing DOI/canonical URL dedup and topic ownership tests remain passing; the generic exact response checks the same stored-source identity/dedup lookup.

No Draft qualification, pediatric rule, trust policy, Auto discovery/qualification rule, WHO Guided query or retrieval budget was changed in this task. Auto still consumes its existing title/abstract/MeSH fields and is not wired to the new matcher. Shared normalized fields are additive and the focused Auto regressions pass.

No DB model/schema or migration was added or edited by this task. Persistence remains on existing SQLAlchemy repository paths; no SQLite-specific business logic was introduced. Tests use isolated temporary/in-memory databases, not production data.

## Verification

| Check | Result |
| --- | --- |
| Pre-change runtime/parser baseline | 23 passed |
| New concept/exact/HTTP/library focused file | Originally 35; now 36 including the archived real EFetch regression |
| Authorized follow-up: concept/exact + PubMed client + runtime route tests | 59 passed, offline, after the single authorized live EFetch |
| Concept + shared relevance + real-title HTTP + query quality + WHO paging/execution focused run | 103 passed (before the final 5 additional tests) |
| PubMed API/client, WHO provider, multi-source import, provider architecture, Auto discovery/Auto service, per-provider results | 382 passed |
| Full backend, once | 927 passed, 2829 existing deprecation warnings |
| Focused ResearchPage + WHO exact UI | 133 passed |
| Full frontend, once | 305 passed across 13 files |
| Final WHO component recheck after DTO correction | 8 passed |
| Typecheck | Passed on second invocation; first invocation found missing metadata fields in WHO import DTO, which were corrected |
| Production frontend build, once | Passed, 2310 modules |
| git diff --check, once | Passed; only existing LF/CRLF conversion notices |

The only change after the passing full frontend run supplied the existing required import DTO metadata fields; the affected WHO component tests, typecheck and build were verified after that correction. Full suites were not rerun. No browser visual/E2E verification is claimed; UI verification is component-level.

Live budget: original PubMed 1 logical search (2 HTTP transport requests), plus exactly 1 explicitly authorized EFetch (1 HTTP request). Cumulative PubMed operations=2, HTTP requests=3. WHO 0, Groq 0. One separate publisher web search was used in the original audit; no new web search, PMC enrichment, arbitrary scraping or LLM call was made in the follow-up.

The prior sign-off item is closed. Follow-up changes are limited to the archived XML, one offline regression and audit artifacts; production code and frontend are unchanged. The earlier full-suite/typecheck/build results remain the baseline; only the affected 59-test backend subset was rerun, preserving the requested full-suite cost limits.

**NO COMMIT. NO PUSH.**
