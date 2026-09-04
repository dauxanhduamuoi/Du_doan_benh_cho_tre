# MEDICAL KNOWLEDGE V1 — FINAL AUDIT REPORT

## STATUS

`PASS_WITH_NOTES`

Medical Knowledge V1 đã vượt qua toàn bộ regression tự động và các kiểm tra an toàn cốt lõi. Local release environment nay có `SECRET_KEY` được tạo bằng nguồn ngẫu nhiên mật mã, lưu riêng trong `.env` ignored/untracked; startup validation, lifespan, migrations và HTTP smoke đều PASS. V1 release-ready với các ghi chú NICE_TO_HAVE không blocking.

## Executive summary

- Chức năng V1 từ evidence đến Parent Tier-2 nhất quán và các lỗi correctness phát hiện trong audit đã được sửa.
- Backend `313 passed`; frontend `124 passed`; typecheck, build, dependency, compile/import, clean-start migration đều PASS.
- Blocker cấu hình đã được giải quyết bằng local secret dài hơn mức tối thiểu. Giá trị secret không được in, không ghi vào `.env.example`, không commit và các biến/API key khác không bị thay đổi.

## Architecture audited

Đã audit các lớp model/schema, repository, PubMed/PMC retrieval, evidence persistence, prompt/provider, Draft, Approval, Publication/Unpublish, public safe-read, Weather AI runtime, staff/Parent frontend, auth, config, dependency và migration v001–v004.

Các câu hỏi maintainability:

| Câu hỏi | Kết luận |
| --- | --- |
| Trách nhiệm được tách hợp lý? | YES |
| DraftService quá lớn? | NO; tương đối lớn nhưng vẫn cohesive theo workflow |
| PublicationService cohesive? | YES |
| Parent read path read-only? | YES |
| Repository chứa quá nhiều business logic? | NO; chủ yếu là persistence/CAS primitives |
| Routers đủ mỏng? | YES; chủ yếu dependency và error mapping |
| Public schema tách khỏi internal schema? | YES |
| Evidence retrieval tách khỏi generation? | YES |
| Network call nằm ngoài Parent runtime path? | YES |
| Code không quá monolithic hoặc phân mảnh? | YES |

Không có broad refactor hoặc feature mới được thực hiện.

## End-to-end data flow

Luồng đã được trace và kiểm tra:

`NCBI PubMed → source → immutable evidence content → revision/source link → DRAFT → APPROVED → published pointer → public safe DTO → optional Parent Tier-2 → UNPUBLISH`

- Keyword search và direct PMID dùng official NCBI ESearch/EFetch.
- PMID→PMCID dùng ELink; PMC XML dùng `defusedxml`, license allowlist và bounded content.
- Revision giữ exact `evidence_content_id`; enrichment/reimport sau đó không thay snapshot của revision cũ.
- Parent chọn exact numeric disease ID và canonical weather factor; không fuzzy/display-name matching và không lấy “latest revision”.

## Findings summary

```text
CRITICAL: 3
IMPORTANT: 2
NICE_TO_HAVE: 5
REQUIRES_PRODUCT_DECISION: 0
FIXED: 5
REMAINING: 5
```

## Detailed findings

### FA-001 — CRITICAL — JWT configuration

- Issue: config cũ dùng public fallback signing key khi `SECRET_KEY` bị thiếu, cho phép giả mạo JWT và truy cập endpoint staff/admin.
- Evidence: cấu hình thực tế hiện tại báo key không được cấu hình; không có giá trị secret nào được in.
- Action: bỏ fallback công khai; thêm startup validation tối thiểu 32 ký tự và placeholder trống trong `.env.example`. Validation chạy trước migration/DB write.
- Status: **FIXED**. Local `.env` đã có generated secret hợp lệ, vẫn Git ignored/untracked; focused load/security/startup validation PASS mà không xuất giá trị.

### FA-002 — CRITICAL — Legacy Tier-2 failure isolation

- Issue: exception ngoài dự kiến từ legacy medical knowledge có thể làm hỏng toàn bộ Weather AI result, gồm ranking/Tier-1.
- Evidence: focused regression ban đầu tái hiện exception propagated.
- Action: cô lập optional Tier-2 tại runtime boundary, log server-side và trả `MEDICAL_KB_ERROR` unavailable state.
- Status: **FIXED**; backend và frontend failure-isolation tests PASS.

### FA-003 — CRITICAL — Stale DRAFT patch race

- Issue: PATCH có thể load DRAFT, bị request khác approve, rồi ghi nội dung qua ORM object đã stale.
- Evidence: focused concurrency regression ban đầu đã mutate revision sau concurrent approval.
- Action: thay bằng SQL status-conditioned compare-and-set `WHERE id=? AND status='DRAFT'`; zero-row update rollback và trả not-editable.
- Status: **FIXED**.

### FA-004 — IMPORTANT — Evidence/source ownership invariant

- Issue: Approval và public read chưa xác minh evidence snapshot thực sự thuộc `source_id` của link.
- Evidence: controlled mismatched link từng được approval/public read chấp nhận.
- Action: Approval từ chối mismatch; Parent safe-read fail closed; repository eager-load snapshot để kiểm tra không phát sinh network.
- Status: **FIXED**.

### FA-005 — IMPORTANT — Explicit null PATCH boundary

- Issue: schema PATCH chấp nhận explicit null cho các cột DB non-null, có thể dẫn tới 500 ở persistence boundary.
- Evidence: cả năm editable fields từng chấp nhận null.
- Action: reject explicit null tại Pydantic model validation.
- Status: **FIXED**.

### FA-006 — NICE_TO_HAVE — PMCID citation persistence

PMCID chưa được lưu trực tiếp trên source; PMID/DOI và safe PubMed URL vẫn đủ cho correctness hiện tại. Không sửa.

### FA-007 — NICE_TO_HAVE — Legacy Tier-2 technical debt

Legacy JSON Tier-2 vẫn tồn tại trong backend trong khi Parent suppress nó và dùng published V1. Không có duplicate Parent display; không xóa trong Final Audit.

### FA-008 — NICE_TO_HAVE — Publication audit legacy column names

`published_by`/`published_at` được dùng cho cả PUBLISH và UNPUBLISH events. Semantics vẫn đúng qua `action`; rename không cần thiết cho V1.

### FA-009 — NICE_TO_HAVE — PMID uniqueness enforcement

Deduplication nằm ở service/transaction behavior, chưa có DB unique constraint riêng cho PMID. Không có lỗi correctness trong deployment SQLite được chứng minh; không thêm migration trong audit.

### FA-010 — NICE_TO_HAVE — Early migration maintainability

v001 dùng check/create style gắn khá gần current models. Clean-start, upgrade/downgrade/re-upgrade và v002–v004 đều PASS; không rewrite migration đã dùng.

## Fixes performed

- Fail-closed startup cho JWT secret thiếu/yếu.
- Cô lập unexpected legacy Tier-2 exception khỏi ranking và Tier-1.
- DRAFT edit dùng status-conditioned CAS để chặn stale writer.
- Approval/public safe-read kiểm tra evidence snapshot ownership.
- PATCH từ chối explicit null cho DB non-null fields.
- Bổ sung focused regressions và mở rộng controlled cross-flow E2E có immutable evidence snapshot + DRAFT edit.

Không thay đổi product policy, prompt, provider selection, PubMed ranking hay PMC license policy.

## Source/evidence safety

PubMed/PMC retrieval dùng official NCBI endpoints, bounded input/result/content, XML hardened parser, license policy cho full text và abstract fallback. Content identity dùng SHA-256 và per-source dedup. Revision link giữ snapshot cụ thể; Approval và Parent nay từ chối link sai owner hoặc evidence rỗng.

ABSTRACT được ghi rõ là abstract; PMC excerpt được ghi rõ là bounded excerpt. Prompt không được phép kết luận paper không có thông tin chỉ vì abstract/excerpt không báo cáo thông tin đó.

## LLM boundary

Groq/OpenAI/Ollama chỉ nhận selected normalized evidence và generation context cần thiết. Không có patient data, unrelated DB data, API keys, browser, tools, web retrieval, PubMed hay PMC search trong provider runtime. OpenAI dùng structured output, `store=false`, không tools; retrieval không thuộc trách nhiệm provider.

## Draft/Approval audit

Revision numbering có retry/uniqueness handling; source/evidence links được snapshot; WHOLE_GROUP cần DIRECT primary evidence. Chỉ DRAFT được edit và CAS chặn race với approval. Approval lấy actor từ auth context, validate structured content và evidence ownership, lưu reviewer/time, không gọi network/LLM, không publish và double-approval fail safely.

## Publish/Unpublish audit

Publication source of truth là `topic.published_revision_id`. Publish/replacement đồng bộ pointer và flags bằng transaction/CAS, giữ old revision immutable và append audit event. Unpublish clear pointer, clear display flag, giữ status APPROVED và content nguyên vẹn. Republish cùng revision hoạt động; history sequence PUBLISH→UNPUBLISH→PUBLISH được giữ.

## Parent publication safety

Public read chỉ trả exact current pointer khi revision thuộc topic, APPROVED, `parent_display_allowed=true`, evidence level thuộc `SUPPORTED`/`LIMITED_OR_INDIRECT`, structured content và citations hợp lệ. Mọi inconsistency fail closed; không fallback sang DRAFT, latest revision, old/replaced hay withdrawn publication.

Public DTO không chứa abstract, PMC/full evidence body, raw metadata, source assessment reasoning, prompt/model/provider, reviewer/publisher ID, internal note, secret hoặc DRAFT history.

## Failure isolation

`FINAL_TIER2_FAILURE_ISOLATION=PASS`

Backend unexpected legacy Tier-2 exception và frontend V1 Tier-2 request failure đều được mô phỏng. Ranking, Tier-1 và Parent result vẫn usable; Tier-2 chỉ biến mất hoặc chuyển sang unavailable state.

## Authorization

Search/direct PMID/import/generate/edit/approve/publish/unpublish đều enforce staff/admin server-side. Viewer và anonymous bị chặn ở staff routes. Reviewer/publisher/unpublisher actor lấy từ authenticated context; frontend không gửi trusted actor ID.

JWT startup fail closed khi signing key thiếu/yếu. Local release environment đã có key thật ngoài source control và focused startup validation PASS.

## Privacy/data exposure

Negative serialization tests xác nhận public endpoint không leak evidence body, raw metadata, source assessment, staff metadata, provider/model, internal notes hoặc secrets. Không phát hiện committed `.env` hay credential value trong diff audit.

## Legacy Tier 2

Legacy `medical_knowledge_base.json` vẫn phục vụ internal runtime compatibility; Parent UI suppress legacy Tier-2 và chỉ render V1 published content. Exception tại legacy boundary đã được cô lập. Việc giữ/xóa legacy là technical debt/product decision cho task sau, không phải blocker V1 hiện tại.

## Migration/database integrity

Foreign keys, constraints, indexes, nullable fields và v001–v004 đã được review. Clean SQLite startup, repeat upgrades và migration idempotency tests PASS. Không reset production DB.

Controlled before/after snapshots giống nhau tuyệt đối:

| Table | Rows | SHA-256 |
| --- | ---: | --- |
| medical_evidence_sources | 4 | `436fb998840bb2187718aeb4be7b7a89b6faa3928cd69c1b2d95cc6cc59ee07f` |
| medical_evidence_contents | 1 | `3f402659c7b358684324785b457b9b180d3a64a9848afc7554e17f77d437b0c2` |
| medical_knowledge_topics | 2 | `d6242e06b7b1a30f94321f35f8d615a8c8a5b6c5206c4cd39d248d6a07f64ff2` |
| medical_knowledge_revisions | 6 | `5aff1246d59f650a2e6d43c3d4c38c15c01af43a4a9c4e04176432ebbc41ebeb` |
| medical_revision_sources | 12 | `92445a5f723893b125abe1822f63431e9935ee4074c4bb49ca065d0681ed9282` |
| medical_knowledge_publications | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

## Architecture/maintainability review

Service/repository/router boundaries hợp lý. DraftService có nhiều orchestration nhưng chưa có concrete duplication hoặc coupling đủ mức IMPORTANT để refactor. PublicationService cohesive; Parent service read-only; public schemas độc lập. Weather factor mapping là deterministic canonical mapping. Small harmless duplication và legacy naming được report thay vì cleanup rộng.

## Final E2E

`MEDICAL_KNOWLEDGE_FINAL_E2E=PASS`

Controlled test DB đã chạy: staff/admin + controlled PubMed source → immutable ABSTRACT snapshot → DRAFT → edit → APPROVE → PUBLISH → Parent read → UNPUBLISH → Parent empty → PUBLISH lại → Parent read lại. Không có external live call.

## Final security negative test

`FINAL_PUBLICATION_SECURITY_TEST=PASS`

Public endpoint không trả DRAFT, APPROVED-unpublished, old replaced revision, withdrawn revision, wrong topic, malformed/inconsistent publication hoặc unsafe evidence level.

## Full regression

- Backend full pytest: `313 passed`, `0 failed`.
- Frontend full Vitest: `124 passed`, `0 failed`.
- TypeScript typecheck: PASS.
- Production build: PASS.
- `pip check`: PASS (`No broken requirements found`).
- Compile/import sanity: PASS.
- `git diff --check`: PASS; chỉ có line-ending conversion warnings, không có whitespace error.

Full backend và frontend suites được chạy đúng một lượt sau audit/fix; trước đó chỉ chạy focused groups.

## Startup

- Isolated FastAPI lifespan với temporary SQLite và test-only 32+ character key: PASS.
- Migration clean-start và repeat upgrade: PASS.
- Cấu hình local release hiện tại: PASS với generated `SECRET_KEY` hợp lệ từ backend `.env`.

Startup implementation và current local release configuration đều sẵn sàng.

## Production DB integrity

Các count/hash controlled snapshots trước và sau giống hệt nhau. `production_business_data_modified=false`. Không tạo topic/revision test, publish hoặc unpublish trên production DB.

LightGBM artifacts, training, feature engineering, SHAP mathematics, ranking, Tier-1 selection và 14-day prediction không bị thay đổi. Chỉ optional legacy Tier-2 error boundary trong Weather AI service được chỉnh để bảo vệ Tier-1.

## Remaining limitations

1. PMCID chưa persist trực tiếp trên source.
2. Legacy Tier-2 vẫn là technical debt nhưng bị Parent suppress và đã failure-isolated.
3. Publication audit columns còn tên legacy.
4. PMID dedup chưa có DB unique constraint riêng.
5. Early migration style có thể được tài liệu hóa tốt hơn, nhưng hiện pass clean/upgrade validations.

## Release readiness checklist

| Câu hỏi | Kết quả |
| --- | --- |
| Staff/admin research evidence? | YES |
| Exact PMID lookup? | YES |
| Reproducible evidence persistence? | YES |
| Structured AI DRAFT? | YES |
| Staff edit DRAFT? | YES |
| Staff/admin approve? | YES |
| Approved content immutable? | YES |
| Publish? | YES |
| Replacement publish? | YES |
| Withdraw? | YES |
| Republish? | YES |
| Parent reads only published safe content? | YES |
| Unpublished content can leak? | NO |
| Tier-2 failure can break Tier-1? | NO |
| Parent can call LLM? | NO |
| Parent can trigger PubMed/PMC? | NO |
| History preserved? | YES |
| Permissions server-side enforced? | YES |
| Application clean-start correctly? | YES |

Final release decision: **RELEASE-READY**.

## Manual final user validation

`FINAL_USER_MANUAL_SMOKE_RECOMMENDED = YES`

Khuyến nghị đúng một manual workflow smoke: Research → Import → Generate → Edit → Approve → Publish; kiểm tra Parent Tier-1/Tier-2; Unpublish; xác nhận Tier-2 biến mất nhưng ranking/Tier-1 còn nguyên.

Không có live Groq, PubMed hoặc PMC call mới trong Final Audit; các milestone trước đã xác thực live integrations.
