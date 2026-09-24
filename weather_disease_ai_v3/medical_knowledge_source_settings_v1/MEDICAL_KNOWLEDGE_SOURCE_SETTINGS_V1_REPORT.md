# MEDICAL KNOWLEDGE SOURCE SETTINGS V1 — VALIDATION REPORT

## STATUS

**PASS**

The persisted, workflow-specific provider settings, generic Admin UI, bounded Auto multi-provider orchestration, and Reviewed provider selection are implemented. Safe deployment defaults are preserved: PubMed is enabled for both workflows; WHO is disabled for both workflows.

Visual browser QA remains a manual follow-up because the in-app browser runtime was unavailable in this session. Automated frontend component tests, TypeScript validation, and the production build all pass.

## Git safety

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Final HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- `git_commit_created=false`
- `git_push_performed=false`
- No tag, merge, rebase, reset, checkout overwrite, or discard was performed.
- All WHO Provider V1 work found in the initial dirty worktree was preserved.

### Initial git status

Recorded before Source Settings V1 implementation:

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

### Final git status

All entries remain uncommitted for review:

```text
 M Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx
 M Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx
 M Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx
 M Frontend/src/app/components/medical-knowledge/MedicalTopicSourceLibrary.tsx
 M Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.test.tsx
 M Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.tsx
 M Frontend/src/lib/medicalKnowledgeApi.ts
 M seasonal_disease_backend/app/auto_medical_knowledge_schemas.py
 M seasonal_disease_backend/app/config.py
 M seasonal_disease_backend/app/main.py
 M seasonal_disease_backend/app/medical_knowledge_draft_schemas.py
 M seasonal_disease_backend/app/medical_knowledge_models.py
 M seasonal_disease_backend/app/pubmed_schemas.py
 M seasonal_disease_backend/app/services/auto_evidence_discovery.py
 M seasonal_disease_backend/app/services/auto_medical_knowledge_service.py
 M seasonal_disease_backend/app/services/auto_medical_knowledge_worker.py
 M seasonal_disease_backend/app/services/medical_evidence_provider.py
 M seasonal_disease_backend/app/services/medical_evidence_provider_factory.py
 M seasonal_disease_backend/app/services/medical_knowledge_draft_service.py
 M seasonal_disease_backend/app/services/medical_knowledge_topic_source_service.py
 M seasonal_disease_backend/app/services/pubmed_evidence_provider.py
 M seasonal_disease_backend/tests/test_medical_evidence_provider_architecture.py
?? seasonal_disease_backend/app/medical_evidence_provider_settings_schemas.py
?? seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py
?? seasonal_disease_backend/app/routers/medical_evidence_provider_settings.py
?? seasonal_disease_backend/app/routers/medical_evidence_reviewed.py
?? seasonal_disease_backend/app/services/medical_evidence_provider_settings_service.py
?? seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py
?? seasonal_disease_backend/app/services/who_evidence_provider.py
?? seasonal_disease_backend/migrations/v016_who_evidence_content.py
?? seasonal_disease_backend/migrations/v017_medical_evidence_provider_settings.py
?? seasonal_disease_backend/tests/test_medical_evidence_provider_settings_v1.py
?? seasonal_disease_backend/tests/test_who_evidence_provider.py
?? weather_disease_ai_v3/medical_knowledge_source_settings_v1/
?? weather_disease_ai_v3/medical_knowledge_who_provider_v1/
```

## Persisted settings model and defaults

`MedicalEvidenceProviderSetting` uses a generic `(provider_id, workflow)` identity with a portable unique constraint. It stores `enabled`, `updated_at`, and `updated_by`; workflow is restricted to `AUTO` or `REVIEWED`. `MedicalEvidenceProviderSettingAudit` is append-only and records provider, workflow, old/new state, actor, action, and timestamp.

Migration V017 is additive and idempotent. It creates the settings and audit tables and deterministically seeds:

| Provider | AUTO | REVIEWED |
|---|---:|---:|
| PUBMED | ON | ON |
| WHO | OFF | OFF |

No CDC row is created. Registry providers missing persisted settings are reconciled with both workflows disabled, so a new provider cannot become active accidentally.

Migration validation used a temporary SQLite database only. Repeated application succeeded, seeded rows remained unique, `PRAGMA foreign_key_check` returned no violations, and `PRAGMA integrity_check` returned `ok`. Existing V015/V016-era business tables and data are not rewritten or deleted.

## Registry reconciliation, API, authorization, and audit

- Available providers come from `MedicalEvidenceProviderRegistry.list_descriptors()`; persistence contributes only workflow enablement.
- Registration, enablement, operational status, and trust are independent states.
- Descriptors supply friendly names, descriptions, capabilities, and deterministic order.
- `GET /api/medical-knowledge/providers/settings` returns reconciled provider/workflow settings. Staff and Admin can read it for Reviewed availability; Parent/general users cannot access it.
- `PATCH /api/medical-knowledge/providers/settings/{provider_id}/{workflow}` accepts a strict enablement DTO and changes only the exact provider/workflow row.
- Mutation is Admin-only. Staff and Parent cannot change global provider settings.
- Every actual state transition writes an enable/disable audit record without credentials or internal exception bodies.

## Admin UI

The existing **Cấu hình dịch vụ** area now includes **Nguồn kiến thức y khoa**. Provider cards are rendered from the backend descriptor list rather than a frontend provider array or a fixed provider count. Each card shows its friendly name, description, capabilities/registered state, and independent Auto/Reviewed switches. Admin changes receive inline success or safe failure feedback and refresh only provider state; Staff receives read-only availability. The page performs no browser-side live provider probes.

Product names are supplied by descriptors:

- `PUBMED`: **PubMed / PMC** — research discovery with permitted PMC full-text enrichment.
- `WHO`: **World Health Organization (WHO)** — official WHO guidance, reports, and documents; no claim of general full-text availability.

Operational/registration display is separate from persisted enablement, so a temporary provider failure never silently flips a setting to OFF.

## Auto multi-provider orchestration

The Auto worker retains the authoritative global Auto and cooldown pre-checks, then snapshots enabled `AUTO` providers at discovery start. A job is therefore deterministic if settings change while it is running; the next job or explicit regeneration reads the new setting snapshot.

Provider construction is behind a generic adapter factory and registry order. The worker contains no PubMed/WHO selection branch. V1 order is deterministic: `PUBMED`, then `WHO`.

The existing global discovery budget is split across enabled providers; enabling WHO does not grant each provider the previous full budget. The global candidate cap and selected evidence cap remain bounded. LLM budgets are unchanged: Strict maximum 2 calls, Basic maximum 1, Safe Template 0. Provider count never creates extra generation calls.

PubMed keeps its existing query builder. WHO uses a dedicated provider-appropriate builder based on canonical disease aliases, factor vocabulary, and pediatric terms, without PubMed MeSH syntax or patient data.

Provider failures are isolated. Successful results remain usable when another provider times out or rate-limits. If every enabled provider is disabled or fails, discovery raises typed provider-search failure semantics instead of producing false `INSUFFICIENT EVIDENCE`. Provider errors are not used to disable settings globally.

Merged candidates use provider-neutral deduplication across DOI, canonical URL, provider/external identity, and a conservative normalized-title fallback. Unrelated documents are not fuzzy-merged. Persisted Auto source DTOs retain `provider_id`, `source_kind`, URL, and external attribution so Admin diagnostics can identify the source mix.

## Trust and Evidence Qualification

Enablement only allows discovery; it does not confer trust. Shared disease, factor, pediatric, provenance, ownership, conflict, and usability gates remain active.

WHO evidence can qualify only when the exact WHO provider/content-origin rules pass, an eligible licensed `OFFICIAL_SUMMARY_EXCERPT` exists, the license allowlist passes, and provenance is present. Metadata-only or unknown-license WHO records may remain references but are not selected as trusted generation evidence. This behavior applies even when an Admin enables WHO.

No patient name, date of birth, user/hospital/medical-record ID, individual diagnosis, exact personal location, or full Parent form input is sent in provider queries.

## Reviewed provider selection and Source Library

Additive generic Reviewed endpoints support enabled-provider selection while all existing PubMed-specific endpoints remain compatible. PubMed is the default. WHO is absent/disabled as a choice until its global `REVIEWED` setting is enabled. Staff may select PubMed only, WHO only, or both, with at least one enabled provider required.

Each selected provider receives its own query syntax. Results are normalized, merged, deduplicated, and retain provider attribution. Partial provider failure returns the other provider's usable results plus a safe provider-specific warning; all-provider failure uses provider failure semantics.

The Source Library now shows provider, source kind, date/year, official URL, license/usability, and Draft eligibility. A metadata-only WHO result can be retained as a reference but cannot support a Draft. Human selection does not bypass WHO trust or common Evidence Qualification.

## Interaction with existing behavior

- Current resolution priority remains `Reviewed > Auto Strict > Auto Basic`.
- Enabling a provider does not bulk-regenerate historical topics.
- Explicit regenerate and future discovery use the settings snapshot current at job start.
- Disabling a provider does not delete evidence, revisions, jobs, source history, visibility, or publication pointers.
- Topic hide/unhide and Parent display configuration remain separate and unchanged.
- Global Auto OFF remains authoritative regardless of individual provider switches.
- Strict, Basic, Safe Template, approval/publication, Weather AI ranking, SHAP, Forecast AI, and Parent safe DTO semantics are unchanged.

## SQL Server portability

- The settings model and services use SQLAlchemy ORM/Core, portable primary keys, booleans, timestamps, unique constraints, and equality queries.
- No SQLite-specific business SQL was added.
- Provider orchestration is database-independent.
- SQLite inspection used for temporary migration validation is isolated to validation/migration concerns.
- A future SQL Server migration maps the same two tables, unique key `(provider_id, workflow)`, boolean/bit field, timestamps, and foreign-key/index definitions without changing application services.

## Files changed for Source Settings V1

Backend implementation:

- `seasonal_disease_backend/app/medical_evidence_provider_settings_schemas.py`
- `seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py`
- `seasonal_disease_backend/app/routers/medical_evidence_provider_settings.py`
- `seasonal_disease_backend/app/routers/medical_evidence_reviewed.py`
- `seasonal_disease_backend/app/services/medical_evidence_provider_settings_service.py`
- `seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py`
- `seasonal_disease_backend/migrations/v017_medical_evidence_provider_settings.py`
- Updates to models, provider descriptors/factory, Auto discovery/worker/service/DTOs, Draft trust validation, Source Library DTO/service, application routing/startup, and WHO direct lookup.

Frontend implementation:

- `Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalTopicSourceLibrary.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- Focused component tests for provider settings and Reviewed provider selection.

Validation and documentation:

- `seasonal_disease_backend/tests/test_medical_evidence_provider_settings_v1.py`
- This report and `medical_knowledge_source_settings_v1_validation.json`.

The final worktree also contains the pre-existing uncommitted WHO Provider V1 files, intentionally preserved and jointly regression-tested.

## Validation results

| Check | Result |
|---|---|
| Source Settings V1 scenario suite | 63 passed |
| Full backend suite | 779 passed |
| Focused frontend settings + Reviewed suite | 121 passed |
| Full frontend suite | 266 passed |
| TypeScript `tsc --noEmit` | PASS |
| Vite production build | PASS |
| Migration/startup/FK validation | PASS |
| `git diff --check` | PASS (line-ending notices only; no whitespace errors) |

All automated tests used deterministic fixtures/fakes. Live calls: Groq 0, PubMed 0, PMC 0, WHO 0, CDC 0. No production database was migrated or written, no production job was retried, and no historical production record was changed.

## Limitations and manual check

The in-app browser capability was attempted twice and reported `Browser is not available: iab`; therefore a final human visual pass of the Admin provider cards and Reviewed selector at common responsive widths is still recommended. This does not affect automated component behavior, type safety, or production-build validation.

## CDC V1 extension points

Do not add CDC until a separate task defines its source and trust policy. CDC V1 can plug in without schema or core UI redesign by:

1. Implementing `MedicalEvidenceProvider` plus CDC-owned search/direct-lookup and query builders.
2. Registering its descriptor, friendly presentation metadata, capabilities, and deterministic order.
3. Adding a factory adapter for Auto and generic normalization for Reviewed.
4. Defining exact CDC content-origin, license, provenance, and trust rules.
5. Letting reconciliation create `CDC/AUTO` and `CDC/REVIEWED` as OFF/OFF by the safe unknown-provider default.
6. Adding offline provider, orchestration, qualification, failure-isolation, and UI regression fixtures.

No CDC provider, setting seed, or UI toggle was implemented in this task.
