# MEDICAL KNOWLEDGE V1 — PUBLISH WORKFLOW REPORT

## Status

**PASS**

Medical Knowledge V1 now supports a separate, audited `APPROVED → Publish` action. Publication selects one approved revision as the current official revision of a topic without changing the revision status or any approved medical content.

## Source audit

- `MedicalKnowledgeTopic.published_revision_id` already existed on the topic model. It is a nullable foreign key to `medical_knowledge_revisions.id` with `ON DELETE SET NULL`.
- `MedicalKnowledgeRevision.parent_display_allowed` already existed on the revision model with a Boolean check constraint.
- The schema did not previously contain `published_by`, `published_at`, or a publication event table.
- The database does not have a cross-table constraint proving that the pointed revision belongs to the same topic and is approved; the service/repository transaction enforces those rules.
- Topic-history API already exposed `published_revision_id`; revision readback already exposed `parent_display_allowed`.
- Approval audit uses direct reviewer/time fields on the revision. Publication needs append-only history because a topic can replace its current revision, so direct revision fields were not reused.
- Parent/public routers did not read the published pointer or parent-display flag. No Parent runtime integration was present or added.
- Migrations use small idempotent SQLAlchemy `upgrade`/`downgrade` functions plus the project's `create_all` startup convention.
- Existing roles are `staff`, `admin`, and non-medical `viewer`; authenticated user identity is resolved from JWT `sub` to the current database user.

## Publication architecture

```text
POST /api/medical-knowledge/revisions/{revision_id}/publish
  → MedicalKnowledgePublicationService
  → MedicalKnowledgeRepository
  → one database transaction
```

The new append-only `MedicalKnowledgePublication` audit event stores:

- publication event ID;
- topic ID;
- revision ID;
- authenticated publisher ID;
- publication timestamp.

No generic workflow engine was introduced.

## Why no `PUBLISHED` revision status was added

Publication and approval remain independent concepts. The revision stays `APPROVED`; current publication is represented by:

```text
topic.published_revision_id = revision.id
revision.parent_display_allowed = true
```

This preserves an old approved revision's status when a newer revision replaces it. The UI derives the separate `ĐANG XUẤT BẢN` badge from the published pointer/readback flag.

## Source of truth and invariant

`MedicalKnowledgeTopic.published_revision_id` is the source of truth for the current topic publication. A successful transaction guarantees:

- the target belongs to the topic;
- the target status is `APPROVED`;
- the target has `parent_display_allowed=true`;
- every other revision in the topic has `parent_display_allowed=false`;
- one append-only publication event is persisted with the pointer/flag changes.

DRAFT publication returns HTTP 409. Publish never auto-approves.

## Atomic replacement and race behavior

The service locks the topic row where supported and also uses a compare-and-swap update against the previously observed published pointer. The same transaction then conditionally verifies/updates the approved target, clears every other topic revision's visibility flag, and inserts the audit event. Any failure is rolled back.

A stale competing writer fails its pointer compare-and-swap before changing flags, rolls back, and retries up to three times. A focused stale-race test confirms that a losing request cannot leave the pointer and visibility flags inconsistent.

Publishing the already-current revision is an idempotent success. It returns the original publisher/timestamp and creates no duplicate event or timestamp.

## Replacement behavior

When a newer approved revision is published:

- the previous revision remains `APPROVED`, readable, immutable, and present in history;
- its `parent_display_allowed` becomes false;
- the new revision's flag becomes true;
- the topic pointer changes to the new revision;
- a new publication event is appended;
- content, evidence links, source snapshots, prompt/model metadata, reviewer, and `reviewed_at` remain unchanged.

Creating, editing, or approving a later DRAFT does not change the current publication.

## Permissions

- `staff`: allowed;
- `admin`: allowed;
- `viewer`: blocked with HTTP 403;
- anonymous: blocked with HTTP 401.

The backend authorization dependency is authoritative. Publisher ID is never accepted from the frontend or request body.

## API

Endpoint:

```text
POST /api/medical-knowledge/revisions/{revision_id}/publish
```

The V1 request has no body. The response contains revision/topic IDs, status `APPROVED`, current-publication/visibility flags, publisher identity/name, publication timestamp, and the previous published revision ID.

Errors are mapped to safe 404, 409, or 422 responses without secrets or tracebacks.

Revision readback now exposes `is_published`, current publisher name/ID, and publication time. Topic history marks exactly the revision matching the current pointer as published.

## Frontend UX

- DRAFT revisions never show Publish.
- Authorized users see `Xuất bản bản này` only for an APPROVED revision that is not current.
- Confirmation explains official selection, Parent eligibility, and that approved content is unchanged.
- If another revision is current, the dialog warns that it will be replaced while remaining in history.
- Loading disables repeat action.
- Success reloads both revision readback and topic history.
- Current publication displays `APPROVED — Đã duyệt` plus a separate `ĐANG XUẤT BẢN` badge, reviewer/time, and publisher/time.
- Approved content remains read-only.
- A replaced old APPROVED revision no longer displays the current-publication badge.
- Authorization/provider details are mapped to safe Vietnamese messages.

## Migration

`v003_medical_knowledge_publication.py` idempotently creates only the append-only audit table and indexes. It does not reset the database, modify old revisions/approval metadata, drop data, or backfill fabricated publication events. Upgrade was called twice against an isolated database and remained idempotent; downgrade removed only the new table.

## Files added

- `seasonal_disease_backend/app/services/medical_knowledge_publication_service.py`
- `seasonal_disease_backend/migrations/v003_medical_knowledge_publication.py`
- `weather_disease_ai_v3/medical_knowledge_v1_publish/MEDICAL_KNOWLEDGE_PUBLISH_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_publish/medical_knowledge_publish_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/medical_knowledge_draft_schemas.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_drafts.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_service.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_drafts.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftReviewForm.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

## Automated validation

### Backend

- Focused Medical Knowledge draft/approval/publication suite: **67 passed**.
- Full backend regression: **269 passed, 0 failed**.
- Covers approved publish, DRAFT/missing rejection, roles/auth context, audit, pointer/flags, replacement, idempotency, stale-race CAS, immutable content/approval/evidence/source links, later DRAFT behavior, API safety, and migration idempotency.

### Frontend

- Focused Medical Knowledge page: **49 passed**.
- Full frontend regression: **103 passed, 0 failed** across 4 files.
- TypeScript typecheck: **PASS**.
- Production build: **PASS**, 2301 modules transformed.

### Startup sanity

- Exact executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`.
- Prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`.
- Python: 3.11.15.
- `pip check`: **PASS**, no broken requirements.
- `import app.main`: **PASS**.
- FastAPI lifespan and v003 table verification using isolated SQLite: **PASS**.
- Bounded Uvicorn startup on `127.0.0.1:8766` with lifespan disabled: **PASS**, followed by controlled shutdown.

### Automated Publish E2E

**PUBLISH_E2E_TEST=PASS**

The isolated E2E created Revision 1 DRAFT, approved and published it; then created/edited Revision 2 without changing Revision 1 publication, approved Revision 2 without changing publication, and finally published Revision 2. It verified pointer/flag replacement, both revisions remaining APPROVED, old content/approval/history preservation, two correct audit events, duplicate protection, and no additional generator call during publication.

### Production database integrity

The valid controlled integrity window used import-only startup; lifespan/migrations and E2E used isolated SQLite. An initial attempted hash window was discarded because another development process had the file locked and was changing it concurrently. No process was stopped and no conclusion was drawn from that invalid window.

- Controlled SHA-256 before: `4A8113CA5AA49903B72096F0FDE95040A644F59E3F7AC176629A11F2AC47F0A9`
- Controlled SHA-256 after: `4A8113CA5AA49903B72096F0FDE95040A644F59E3F7AC176629A11F2AC47F0A9`
- `production_database_modified=false` for the valid controlled validation window.

## Explicit confirmations

- Published revision remains `APPROVED`: **yes**.
- Medical content modified by Publish: **no**.
- Approval metadata modified by Publish: **no**.
- LLM/Groq/OpenAI/Ollama called by Publish: **no**.
- PubMed or PMC called by Publish: **no**.
- Weather API called by Publish: **no**.
- Parent Medical Knowledge integration added: **no**; still **NOT IMPLEMENTED**.
- Weather AI, LightGBM, SHAP, ranking, and Tier 1 modified: **no**.

## Remaining limitations

- V1 has no Unpublish, Revoke, Reject, delete-publication, or dedicated rollback action.
- Publication history is stored append-only in the database but has no dedicated history API/UI yet; the UI displays audit for the current revision.
- The invariant is enforced by the application transaction and conditional SQL, not a cross-table database trigger; unsupported out-of-band SQL could violate it.
- Publisher display names are resolved from the current user record rather than stored as an immutable name snapshot.
- Parent runtime does not consume the publication state in this task.

## Manual testing

User manual testing required: **no**. Automated regression, isolated migration/lifespan, controlled startup, integrity checks, and Publish E2E are sufficient for this task.
