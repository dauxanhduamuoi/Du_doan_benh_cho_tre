# Auto Medical Knowledge Default Visibility V1 Report

## Status

**PASS** — implementation and requested focused automated validation completed.

## Scope

- Repository: `dauxanhduamuoi/Du_doan_benh_cho_tre`
- Branch audited: `feature/medical-knowledge-v1-20260820`
- Starting HEAD: `b72a9594fd265d67b988ae3b03ec316c1e2061bb`
- Existing uncommitted Multi-Tier V2 and regeneration work was preserved.
- Working tree was already dirty at task start; no reset, checkout, deletion, or unrelated rollback was performed.
- No live Groq, PubMed, PMC, production job, or production data operation was run.

## Architecture audit

The system already had two independent global controls:

1. `AutoMedicalKnowledgeSetting.enabled` controls enqueue/worker generation.
2. `AutoMedicalKnowledgeSetting.display_mode` controls whether Parent resolution may use Auto fallback.

The old `AutoMedicalKnowledgeRevision.is_visible` was a per-revision flag. A READY revision could require an Admin to turn it on before Parent resolution. There was no visibility audit record, so a historical `false` cannot distinguish an explicit revoke from a revision that was never manually allowed.

Reviewed content is resolved first by `PublishedMedicalKnowledgeReadService`. Auto is considered only for selectors not resolved by Reviewed. The current Auto pointer preserves READY Strict over READY Basic.

## Implemented policy

Parent Auto resolution now requires all of the following:

- global `display_mode` is `REVIEWED_WITH_AUTO_FALLBACK`;
- no valid Reviewed publication already resolved the canonical selector;
- the canonical topic is not explicitly hidden by staff;
- the current Auto revision passes the unchanged Parent safety and evidence eligibility checks.

`is_visible` is no longer a mutable Parent eligibility gate. It remains stored for schema/data compatibility, and the Admin response exposes it only as an effective compatibility value. New READY revisions store `true` as a legacy mirror; topic policy is authoritative.

Generation remains independent. Turning generation off prevents new work but does not suppress already stored eligible Auto content when Parent Auto display is on.

## Topic-level state and audit

Migration `v014_auto_topic_visibility.py` adds:

- `auto_medical_knowledge_topic_states.is_hidden_by_staff`;
- `auto_medical_knowledge_topic_states.hidden_at`;
- `auto_medical_knowledge_visibility_audits` with canonical topic, action, actor FK, and timestamp.

Audit actions are `HIDE_AUTO_TOPIC` and `UNHIDE_AUTO_TOPIC`. Audit history is separate from medical revision history.

The new strict endpoint is `POST /api/medical-knowledge/auto/topics/visibility`. Its DTO accepts only the canonical selector and `hidden`. Staff and Admin may call it; Parent/general roles may not. Global settings and regeneration remain Admin-only.

Generation completion only changes `current_revision_id` and never writes the topic hide fields. Consequently, hide survives concurrent generation and all later Strict or Basic revisions. Unhide only changes policy state and immediately restores access to the current eligible revision; it creates no job or revision.

## Legacy compatibility decision

No existing audit/history can reliably reconstruct whether historical `is_visible=false` meant an explicit staff revoke or simply that the old allow button was never clicked. Migration therefore does not invent hidden decisions:

- every existing topic state starts `is_hidden_by_staff=false`;
- all historical revision fields and medical prose remain unchanged;
- explicit hides begin being durable and auditable after V1 deployment.

The legacy `auto_visible_default` database/API field is retained for backward schema compatibility but is not used by the new Parent visibility policy. The authoritative global Parent gate remains `display_mode`.

## Database portability

New service and repository behavior uses SQLAlchemy ORM/Core and contains no SQLite-specific SQL. SQLite `ALTER TABLE`, `CREATE TABLE IF NOT EXISTS`, and index DDL are isolated in migration V014 and documented there for replacement by a future SQL Server migration.

The migration is additive and idempotent. Focused migration/startup tests verify preserved prose, no invented hides, an empty audit history on migration, new columns/table, and `PRAGMA foreign_key_check` with no violations.

## UI behavior

- Removed the per-revision “Cho phép hiển thị” workflow.
- Eligible, unhidden Auto shows “Đủ điều kiện hiển thị tự động”.
- Hidden topics show “Đã ẩn bởi nhân viên”.
- Actions are “Ẩn khỏi phụ huynh” and “Hiển thị lại”.
- UI does not claim an Auto revision is currently displayed, so Reviewed precedence is not misrepresented.
- Parent Auto display OFF is stated explicitly.
- Staff receives topic visibility controls without receiving Admin-only runtime, display-mode, fallback-setting, retry, or regenerate controls.
- Visibility requests serialize only the exact DTO fields; no revision object spread is sent.

## Safety invariants retained

- Reviewed precedes Auto.
- Strict precedes Basic.
- INSUFFICIENT is never Parent-visible.
- Unsafe/non-eligible revisions remain excluded.
- Source provenance, pediatric-direct support, evidence level, required prose, tier/method, and safe-template reason checks are unchanged.
- Parent DTOs retain the existing bounded citations, tier label, and unreviewed warning and do not expose diagnostics, prompts, failure details, or internal visibility state.

## Validation performed

Backend focused command selected 19 cases covering default Strict/Basic visibility, global gates, Reviewed and Strict precedence, unsafe/insufficient exclusion, hide/unhide, audit, no-generation unhide, regeneration, exact GENERATING-time hide, authorization, legacy migration, FK integrity, and startup. Result: `19 passed`.

Frontend focused command covered Auto panel, strict visibility API serialization, and Parent Medical Knowledge rendering. Result: `55 passed`.

- TypeScript: `tsc --noEmit -p tsconfig.json` passed.
- Production frontend: `vite build` passed.
- `git diff --check` passed (only existing Windows line-ending notices).

External network/provider call count: **0**. Production database writes: **0**. Historical production medical prose changed: **0**.

## Files changed for this policy

- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/repositories/auto_medical_knowledge_repository.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/published_medical_knowledge_read_service.py`
- `seasonal_disease_backend/app/routers/auto_medical_knowledge.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/migrations/v014_auto_topic_visibility.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/lib/medicalKnowledgeApi.regenerate.test.ts`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- this report and its validation JSON.

## Remaining limitations

- Pre-V014 explicit hide intent cannot be reconstructed because the old system stored no visibility audit. The deterministic compatibility policy intentionally treats those topics as unhidden.
- Authorization is role-based because the current Medical Knowledge module has no narrower visibility permission code: Staff and Admin are allowed, while global configuration and regeneration stay Admin-only.
- The retained `auto_visible_default` field is legacy compatibility surface and should be removed only in a separately versioned API/schema cleanup.

## Manual test required

After deployment, perform one authenticated browser smoke test: enable Parent Auto fallback as Admin, hide and unhide one canonical topic as Staff, confirm the status/feedback refreshes once per action, and confirm Parent switches between no Auto and the same current eligible Auto revision without a new job. No live provider generation is required for this smoke test.
