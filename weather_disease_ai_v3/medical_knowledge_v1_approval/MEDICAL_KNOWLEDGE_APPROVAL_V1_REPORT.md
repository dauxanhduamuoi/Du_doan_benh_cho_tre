# MEDICAL KNOWLEDGE V1 — REVIEW + APPROVAL REPORT

Date: 2026-08-23  
Branch: `feature/medical-knowledge-v1-20260820`  
Status: **PASS**

## Outcome

Medical Knowledge V1 now supports the business transition:

`DRAFT → APPROVED`

An authenticated medical staff or admin can review/edit a DRAFT, confirm approval, and freeze that revision as an immutable historical record. Approval is not Publish: the Parent visibility flag remains false and the topic's published pointer is not changed.

`APPROVAL_E2E_TEST=PASS`

## Source audit

- Revision status is stored as a bounded string with a database check constraint. The existing code already defines `DRAFT`, `APPROVED`, and legacy `REJECTED`; this task did not add a rejection workflow or change the existing status set.
- `MedicalKnowledgeRevision` already had `reviewed_by`, `reviewed_at`, and `review_note`, with `reviewed_by` referencing `users.id`.
- The existing schema already allowed `APPROVED`, so no database schema migration was required.
- DRAFT updates run through `MedicalKnowledgeDraftService.update_draft()` and already reject any status other than `DRAFT`.
- User identity is resolved from JWT `sub` by `get_current_user`; actual authorized roles are `staff` and `admin`. The non-medical test role is `viewer`.
- Revision history is ordered by revision number descending and already preserves all old revisions.
- New generated revisions always use the next revision number and are not blocked by an earlier APPROVED revision.

## Architecture choice

Approval is implemented as a separate `MedicalKnowledgeApprovalService`, keeping provider generation and approval responsibilities separate:

`FastAPI router → Approval Service → MedicalKnowledgeRepository → database`

The router only passes the authenticated user's server-side ID and maps domain errors. It contains no transition, validation, or persistence logic. The Approval Service has no LLM, PubMed, or PMC dependency.

## Approval data model and transition

The existing one-to-one metadata on `medical_knowledge_revisions` is used:

- `status = APPROVED`
- `reviewed_by = authenticated current_user.id`
- `reviewed_at = server UTC time`
- `updated_at = approval time`

This is simpler than adding a separate approval table because V1 permits only one active approval per revision and the required audit columns already existed. The API/readback also returns a reviewer display label resolved as `full_name`, falling back to `username`; it does not expose email or secret data.

## Validation and immutability

Before transition, the service validates:

- revision and topic exist;
- status is exactly `DRAFT`;
- authenticated reviewer exists, is active, and has role `staff` or `admin`;
- Parent display is false;
- at least one source link exists;
- linked source/evidence text is usable;
- stored source assessments have a valid relevance prefix and consistent source role;
- evidence level/scope and all Vietnamese structured fields pass the existing proposal schema;
- `WHOLE_GROUP` still has a DIRECT/PRIMARY source.

`INSUFFICIENT` is explicitly approvable; approval confirms the medical assessment, not that evidence is strong.

After approval, the existing PATCH endpoint returns HTTP 409 because only DRAFT revisions are editable. Source links, evidence snapshots, and source records remain unchanged.

## Double-approval and race protection

The repository performs one conditional atomic update:

`WHERE revision_id = ? AND status = 'DRAFT'`

Only a single caller can change the row to APPROVED. A second or racing call affects zero rows and returns safe HTTP 409. Direct revision metadata inherently permits only one reviewer/timestamp pair, so no duplicate approval record can be created.

## Authorization and API

Endpoint:

`POST /api/medical-knowledge/revisions/{revision_id}/approve`

- Request body: none.
- Reviewer ID is never accepted from the frontend.
- `staff`: allowed.
- `admin`: allowed.
- anonymous: HTTP 401.
- `viewer`/non-medical role: HTTP 403.
- missing revision: HTTP 404.
- already approved/non-DRAFT: HTTP 409.
- invalid structured revision: HTTP 422.

The response is a bounded approval summary containing revision ID, APPROVED status, reviewer ID/display name, approval time, Parent visibility false, and the unchanged published pointer.

## Frontend UX

- DRAFT keeps “Lưu bản nháp” and adds “Duyệt bản này” for authorized roles.
- Approval requires a confirmation dialog explaining that the revision will be locked and is not published to parents.
- Loading prevents duplicate approval actions.
- After success, the UI reloads the revision/history and shows `APPROVED — Đã duyệt`.
- Reviewer display name and approval time are shown.
- APPROVED fields are read-only; Save and Approve actions disappear.
- The helper explicitly says the revision is locked and has not been published to parents.
- Revision history remains browsable; other DRAFT revisions remain editable.
- No Publish button or Parent Medical Knowledge UI was added.

## Migration

No new migration was added. The existing V1 schema already contains all required approval columns and the APPROVED status constraint. Existing idempotent migrations and full FastAPI lifespan were validated against isolated in-memory SQLite without destructive operations.

## Automated tests

- Focused backend Medical Knowledge workflow: **56 passed**.
- Focused frontend research/review page: **41 passed**.
- Full backend: **258 passed, 0 failed**.
- Full frontend: **95 passed, 0 failed** across 4 files.
- TypeScript typecheck: **PASS**.
- Production build: **PASS**; 2,301 modules transformed.
- `git diff --check`: **PASS**; output contained only Windows LF→CRLF notices.

Backend tests cover DRAFT approval, auth-derived reviewer identity, timestamp, staff/admin permission, anonymous/viewer rejection, missing/non-DRAFT/invalid revisions, INSUFFICIENT approval, WHOLE_GROUP invariant, immutable readback, source/evidence/link preservation, atomic double approval, published pointer preservation, and creating a later DRAFT.

Frontend tests cover Save/Approve visibility, confirmation/cancel, explicit Parent warning, loading, successful APPROVED UI, reviewer/time, read-only fields, hidden post-approval actions, safe authorization error, revision browsing, and absence of Publish.

All existing PubMed keyword/direct PMID, import/dedup, PMC enrichment, provider generation, DRAFT edit, Weather AI, and Parent API tests passed in the full suites.

## Automated approval E2E

The standalone smoke used real FastAPI routes, JWT authentication for a `staff` user, the real Draft/Approval services, and isolated in-memory SQLite:

1. Created test user, topic, source, immutable evidence snapshot, DRAFT, and source link.
2. Edited the DRAFT through PATCH.
3. Approved it through POST with no request body.
4. Read back APPROVED with reviewer/time.
5. Confirmed a later PATCH returns 409.
6. Confirmed source, evidence snapshot, and link values were unchanged.
7. Confirmed `parent_display_allowed=false` and `published_revision_id` remained null.
8. Used a generator that fails if called; observed zero generation calls.

Result: `APPROVAL_E2E_TEST=PASS`.

## Environment and startup sanity

- Executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`
- Prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`
- Python: `3.11.15`
- Changed-path dependencies and `pip check`: **PASS**.
- `import app.main`: **PASS**.
- Existing migrations plus FastAPI lifespan on isolated SQLite: **PASS**.
- Bounded Uvicorn startup on `127.0.0.1:8765` with production lifespan disabled: **PASS**, then terminated. Full lifespan was tested separately on the isolated database.

## Production database integrity

- Controlled validation SHA-256 before: `A7944C2987AAA7A76CDF072B1F5E3799C9112F103D7D4F883350A25D5FAFAC5A`
- Controlled validation SHA-256 after: `A7944C2987AAA7A76CDF072B1F5E3799C9112F103D7D4F883350A25D5FAFAC5A`
- `production_database_modified=false`

All approval E2E and migration/lifespan checks used isolated in-memory SQLite. No approval record was created in production.

## Explicit invariants

- Publish added: **No**.
- Parent Medical Knowledge integration added: **No**.
- `parent_display_allowed` changed by approval: **No; remains false**.
- `published_revision_id` changed by approval: **No**.
- LLM call on approval: **No**.
- PubMed/PMC call on approval: **No**.
- Prompt/provider/evidence grading/PMC policy changed: **No**.
- Weather AI, LightGBM, SHAP, ranking, Tier 1, prediction, and Parent UI changed: **No**.

## Files added

- `seasonal_disease_backend/app/services/medical_knowledge_approval_service.py`
- `weather_disease_ai_v3/medical_knowledge_v1_approval/MEDICAL_KNOWLEDGE_APPROVAL_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_approval/medical_knowledge_approval_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/medical_knowledge_draft_schemas.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_service.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_drafts.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_drafts.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftReviewForm.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

## Remaining limitations

- V1 supports one irreversible approval per revision; it does not implement revoke, rejection, approval notes, or a general workflow engine.
- To revise approved content, users generate a new DRAFT; there is no clone-approved-revision action in this task.
- Reviewer display name is resolved from the current user record; no separate immutable display-name snapshot was added because the existing direct audit columns were reused.
- The pre-existing `REJECTED` status remains in the model for compatibility, but this task adds no rejection action.

User manual testing required: **No**.

