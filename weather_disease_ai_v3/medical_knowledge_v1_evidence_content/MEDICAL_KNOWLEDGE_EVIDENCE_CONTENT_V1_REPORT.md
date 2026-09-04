# MEDICAL KNOWLEDGE V1 — EVIDENCE CONTENT ENRICHMENT REPORT

## Status

**PASS**

Medical Knowledge V1 now supports normalized, persisted evidence snapshots from PubMed abstracts and eligible PMC article content. PMC retrieval is an optional enrichment at import/re-import time; draft generation has no PMC network dependency and continues to create review-only DRAFT revisions.

## Source audit and confirmed root cause

The source audit confirmed the reported root cause:

- `medical_evidence_sources.abstract_text` was the only persisted scientific text.
- `raw_metadata_json` contained bibliographic metadata such as publication types and identifiers, not article content.
- `MedicalKnowledgeDraftService._source_input()` copied `abstract_text` into `DraftSourceInput`.
- `build_generation_input()` serialized those selected PubMed source objects; OpenAI, Ollama, and Groq all consumed the same abstract-only `DraftGenerationContext`.
- The configured `MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS=60000` check ran after context serialization and rejected oversized input without truncation.
- Import fetched PubMed records and reused an existing source by PMID. Reuse did not enrich the source because no evidence-content model or PMC client existed.
- The project uses SQLAlchemy `create_all(checkfirst)` plus small explicit idempotent migration functions, not Alembic. The V1 migration imports current model tables rather than frozen DDL.
- Prompt provenance came from `MEDICAL_KNOWLEDGE_PROMPT_VERSION`, whose old default was `medical_knowledge_v1`.
- Bibliographic fields and `raw_metadata_json.publication_types` remain reusable; large evidence text is not suitable for `raw_metadata_json`.

## Architecture before

`PubMed ESearch/EFetch → MedicalEvidenceSource.abstract_text → DraftGenerationContext.abstract_text → selected_pubmed_sources → selected LLM provider → DRAFT revision`

## Architecture after

`PubMed source import/re-import → ELink(pubmed_pmc) → optional EFetch(db=pmc) → safe JATS parser → license/body validation → bounded normalized evidence snapshot → MedicalEvidenceContent`

`MedicalKnowledgeDraftService → preferred persisted snapshot (or legacy abstract fallback) → DraftGenerationContext(content_kind + evidence_text) → unchanged provider-swappable generator interface → validated DRAFT revision`

The responsibilities remain separated:

- `PubMedClient`: PubMed search/fetch and shared NCBI request/rate-limit/retry transport.
- `PmcClient`: only PMID→PMCID ELink and PMC EFetch calls.
- `pmc_content_parser`: safe JATS parsing and deterministic section selection.
- `MedicalEvidenceContentService`: license/body policy and abstract fallback.
- `MedicalKnowledgePubMedService`: orchestration and persistence at import time.
- `MedicalKnowledgeDraftService`: database-only evidence selection and business workflow; no PMC HTTP retrieval.
- OpenAI/Ollama/Groq providers: unchanged retrieval responsibility; all receive the same normalized context.

## Files added

- `seasonal_disease_backend/app/services/pmc_client.py`
- `seasonal_disease_backend/app/services/pmc_content_parser.py`
- `seasonal_disease_backend/app/services/medical_evidence_content_service.py`
- `seasonal_disease_backend/migrations/v002_medical_evidence_content.py`
- `seasonal_disease_backend/tests/test_medical_evidence_content.py`
- `weather_disease_ai_v3/medical_knowledge_v1_evidence_content/MEDICAL_KNOWLEDGE_EVIDENCE_CONTENT_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_evidence_content/medical_knowledge_evidence_content_v1_validation.json`

## Files modified

- Frontend Medical Knowledge components: `MedicalDraftReviewForm.tsx`, `MedicalDraftWorkspace.tsx`, `MedicalKnowledgeResearchPage.tsx`, `PubMedResultCard.tsx`, `PubMedResults.tsx` and focused tests.
- Frontend API/types: `Frontend/src/lib/medicalKnowledgeApi.ts`.
- Backend config/bootstrap: `.env.example`, `app/config.py`, `app/main.py`, `requirements.txt`.
- Backend models/schemas/repository: `medical_knowledge_models.py`, `medical_knowledge_schemas.py`, `medical_knowledge_draft_schemas.py`, `pubmed_schemas.py`, `medical_knowledge_repository.py`.
- Backend orchestration/prompt/transport: `medical_knowledge_pubmed.py`, `medical_knowledge_pubmed_service.py`, `medical_knowledge_draft_service.py`, `medical_knowledge_prompt.py`, `pubmed_client.py`.
- Migration compatibility: `migrations/v001_medical_knowledge_v1.py` only adjusts current-model table creation order because the project does not freeze V1 DDL; deployed schema evolution is implemented by V2.
- Provider/workflow/config tests: Groq, Ollama, OpenAI shared-context tests and deterministic service configuration tests.

## Database and migration changes

`MedicalEvidenceContent` stores immutable evidence snapshots with:

- source relationship;
- explicit `content_kind`;
- `content_origin`;
- PMCID/external identifier;
- normalized evidence text;
- retrieval timestamp;
- truncation flag;
- license name/URL when available;
- bounded provenance metadata;
- SHA-256 content identity.

`medical_revision_sources.evidence_content_id` is nullable for backward compatibility and pins each new revision source link to the exact snapshot supplied to the LLM. Old revisions remain unchanged and retain a null snapshot link.

Migration `v002_medical_evidence_content` is idempotent, creates the new table/index, and adds the nullable foreign key column without dropping or resetting data. Startup invokes it after `Base.metadata.create_all`. It was tested on a simulated existing schema, including repeated upgrade and downgrade. It was **not** run against the user's production `database.db` during this task. The production DB SHA-256 remained `007D9C94DB8D87AD516B550CDBF619DA83BD9C99345319AEFC574E86C07DCF74` before and after validation.

## PubMed and PMC retrieval behavior

PubMed search behavior is unchanged. Import/re-import now performs bounded enrichment outside the database write transaction:

1. Fetch PubMed bibliographic data through the existing production client.
2. Reuse a persisted eligible PMC snapshot without another PMC fetch.
3. Otherwise use official NCBI ELink with `dbfrom=pubmed`, `db=pmc`, and `linkname=pubmed_pmc`.
4. If a PMCID exists, use official NCBI EFetch with `db=pmc` and XML mode.
5. Parse, validate license/body availability, bound content, and persist a snapshot.
6. On any normal PMC absence/unavailability/parse/policy failure, persist or reuse the PubMed abstract instead.

This matches official NCBI documentation for [PMID↔PMCID ELink](https://pmc.ncbi.nlm.nih.gov/tools/xref-ids/) and [EFetch with `db=pmc`](https://www.ncbi.nlm.nih.gov/sites/books/NBK25499/#chapter4.EFetch). The legacy PMC OA Web Service, HTML scraping, publisher scraping, browser automation, Google, and ResearchGate are not used. The legacy OA service was intentionally avoided because this workflow only needs current Entrez E-utilities and because legacy PMC distribution paths are being retired, as described by [NCBI's current PMC dataset distribution notice](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/).

## Content parser and content kinds

The parser uses `defusedxml` so normal PMC JATS DTD declarations are accepted while entity expansion and external entity resolution remain blocked. It:

- extracts abstract and scientific body paragraphs;
- preserves section headings;
- prioritizes Results, Discussion, Conclusion, Abstract, Methods, Introduction, then other body sections;
- excludes the `<back>` reference list from primary evidence;
- ignores tables, figures, scripts, navigation, and HTML UI;
- normalizes whitespace;
- never executes article content.

Kinds are truthful:

- `ABSTRACT`: PubMed abstract fallback.
- `PMC_FULL_TEXT`: all usable extracted scientific body content fits the per-source bound.
- `PMC_FULL_TEXT_EXCERPT`: deterministic section/sentence-bounded selection was required.

An abstract-only PMC EFetch response cannot be labeled as PMC full text because `has_body_content` is required.

## Input bounding and fallback logic

`MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE` defaults to 6,000 characters. Oversized PMC articles become sentence-bounded excerpts with headings preserved. The final serialized generation envelope is still checked against `MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS` (60,000 by default); nothing bypasses the existing safe limit.

Fallback behavior:

- no PMCID → `ABSTRACT`;
- ELink/EFetch timeout, 429 after bounded retry, 5xx, invalid XML, or unusable body → `ABSTRACT`;
- missing/non-allowlisted license metadata → `ABSTRACT`;
- PMC content over bound → `PMC_FULL_TEXT_EXCERPT`;
- no usable PMC content and no abstract → existing validation error before provider call;
- PMC failure does not delete a source, create an empty revision, or switch LLM provider.

## Persistence and reuse strategy

Evidence snapshots are immutable and deduplicated by `(source_id, content_sha256)`. Existing PubMed sources can be enriched on re-import without creating duplicate bibliographic sources or modifying old revisions. Once a PMC full-text/excerpt snapshot exists, re-import reuses it and does not perform another PMC enrichment fetch. Draft generation never fetches PMC; it prefers persisted `PMC_FULL_TEXT`, then `PMC_FULL_TEXT_EXCERPT`, then `ABSTRACT`. Legacy sources with no evidence-content row use their existing abstract without network access.

Full article text is never stored in `raw_metadata_json`, never returned to the frontend, and never exposed to Parent.

## License and provenance handling

PMC presence alone is not treated as permission. Richer PMC text is eligible only when:

- PMCID and official NCBI PMC origin are recorded;
- usable scientific body content exists;
- an official PMC license URL is present;
- the conservative allowlist recognizes CC BY or CC0 URL families.

All other cases fall back to PubMed abstract. This is a conservative project policy, not a legal guarantee. License name/URL and provenance are persisted for staff audit.

## Prompt and provenance changes

The prompt now says “selected evidence content” rather than “selected abstracts”, describes all three content kinds, retains selected-source-only/no-tools/no-web/no-patient/no-causality/no-fabrication/group-scope rules, and adds the required abstract absence rule:

> When only an abstract is supplied, “not reported in the supplied abstract” must not be transformed into “not studied in the paper.”

The default prompt version is now `medical_knowledge_v2_evidence_content`. The user's real `.env` was not modified and currently overrides this with a different value. Before creating a new real revision, manually set:

`MEDICAL_KNOWLEDGE_PROMPT_VERSION=medical_knowledge_v2_evidence_content`

`MEDICAL_KNOWLEDGE_EVIDENCE_MAX_CHARS_PER_SOURCE` is absent from the real `.env`; this is safe because the tested default `6000` is used. Add it only if explicit local configuration is desired.

## Evidence-scope invariant

Structured proposal validation now rejects `WHOLE_GROUP` unless at least one source assessment is `DIRECT`. Prompt rules require subtype-, pathogen-, age-subgroup-, and uncertain-scope evidence to be assessed conservatively and use `PARTIAL_GROUP`. Draft edits also reject a transition to `WHOLE_GROUP` if persisted source assessments contain no DIRECT source. Invalid output fails before revision persistence; it is not silently rewritten.

## Frontend transparency

The Medical Knowledge workspace was not redesigned. It now displays only:

- `AI sử dụng: Toàn văn PMC`;
- `AI sử dụng: Trích đoạn toàn văn PMC`;
- `AI sử dụng: Tóm tắt PubMed`;
- PMCID when available.

Badges appear after import and in revision review. No normalized evidence text or full article is sent to the browser.

## Security and privacy

- Article text is explicitly untrusted data.
- No patient/child attributes, JWT, account data, hospital data, or secrets are added to provider input.
- No LLM tools, web search, remote MCP, or provider fallback chain is added.
- NCBI API key remains only in POST transport configuration and is not persisted/logged.
- Groq/OpenAI/Ollama continue using the same normalized provider-neutral context.

## Automated validation

- Backend: **220 passed, 0 failed**.
- New focused PMC/evidence suite: **25 passed, 0 failed**.
- Frontend: **82 passed, 0 failed**.
- Frontend Medical Knowledge focused tests: **50 passed, 0 failed**.
- TypeScript typecheck: **PASS**.
- Production frontend build: **PASS** (2,301 modules transformed).
- Python compile/import: **PASS**.
- `git diff --check`: **PASS** (line-ending conversion warnings only; no whitespace errors).
- Weather AI/SHAP/ranking/training/tuning: no changed files and no training/tuning run.
- Approval, Publish, and Parent integration: not added.

## Live PMC test

`PMC_LIVE_TEST=PASS`

Bounded live validation used production `PubMedClient`, `PmcClient`, parser, and resolver with PMID `22884022`; it did not use the database or an LLM.

- ELink resolved `PMC9151886`.
- Official EFetch returned valid XML but only front/abstract content: no scientific `<body>` and no license URL in that response.
- Production policy correctly returned `content_kind=ABSTRACT` with `fallback_reason=pmc_no_body_content`.
- Input remained bounded.

This live result is intentionally not relabeled as PMC full text. Mocked official-response tests prove eligible body+license content uses full text/excerpt; the live record demonstrates safe fallback behavior.

## Regression status

PubMed search/import, Groq, Ollama, OpenAI, DRAFT creation, `parent_display_allowed=false`, `generated_by_llm=true`, revision-source links, DRAFT editing, published revision pointer preservation, authorization, and provider error mapping all pass. No automatic provider fallback was introduced.

## Remaining limitations

- Official PMC EFetch availability/body/license metadata varies by record. PMID `22884022` safely remains abstract-backed under the current response.
- The conservative CC BY/CC0 allowlist may reject other licenses that could be usable after a future policy/legal review.
- Tables and figures are intentionally excluded; evidence reported only in tables may not enter the V1 normalized text.
- Enrichment refresh is explicit through source re-import; there is no separate refresh endpoint in this task.
- The real `.env` prompt version requires the one-line manual update above; it was not overwritten by Codex.

## Exact manual test required

1. Set `MEDICAL_KNOWLEDGE_PROMPT_VERSION=medical_knowledge_v2_evidence_content` in `seasonal_disease_backend/.env`.
2. Restart backend so migration V2 and the prompt version are active.
3. Open **Kho kiến thức y khoa**.
4. Select **Pneumonia** and **humidity**.
5. Search/import PMID `22884022`.
6. Confirm the UI displays the evidence badge and PMCID. With the currently observed official EFetch response, the expected badge is **AI sử dụng: Tóm tắt PubMed** and PMCID is `PMC9151886`.
7. Create one AI draft and capture the new Revision for medical review. Do not approve or publish it as part of this task.
