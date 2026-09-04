# MEDICAL KNOWLEDGE V1 — SAFE UNPUBLISH / WITHDRAW FROM PARENT

## STATUS

**PASS**

`UNPUBLISH_E2E_TEST=PASS`

`PARENT_WITHDRAWAL_E2E_TEST=PASS`

Nhánh nguồn đã xác nhận: `feature/medical-knowledge-v1-20260820`.

## Source audit

- `MedicalKnowledgePublication` trước thay đổi lưu `topic_id`, `revision_id`, `published_by`, `published_at`; mỗi dòng chỉ được hiểu ngầm là một lần Publish.
- Publish hiện cập nhật `topic.published_revision_id`, bật cờ `parent_display_allowed` của revision đích và tắt cờ của các revision còn lại trong cùng transaction.
- Bảo vệ race hiện hữu gồm topic row lock khi DB hỗ trợ, compare-and-swap trên published pointer và tối đa ba lần thử lại.
- Parent safe-read join qua chính `published_revision_id` và còn yêu cầu `APPROVED` + `parent_display_allowed=true`; khi pointer là `null`, truy vấn fail-closed và trả về không có item.
- Approval service, Parent matching, Weather AI, LightGBM, SHAP, ranking và Tier 1 không bị thay đổi trong task này.

## Business semantics and architecture

API mới:

`POST /api/medical-knowledge/revisions/{revision_id}/unpublish`

Luồng thực thi:

`Router -> MedicalKnowledgePublicationService -> MedicalKnowledgeRepository -> one DB transaction`

Unpublish chỉ rút revision hiện hành khỏi Parent. Nó không Reject, không revoke approval, không xóa và không sửa nội dung. Chỉ revision `APPROVED` đang được `topic.published_revision_id` trỏ tới mới hợp lệ; DRAFT, APPROVED chưa publish, revision cũ đã bị thay thế và trạng thái khác topic đều bị từ chối an toàn.

Response không chứa email hay secret. Actor được lấy từ backend auth context, không nhận user ID từ frontend.

## Audit model and migration

`medical_knowledge_publications` được mở rộng thành publication-event history bằng cột bắt buộc `action`:

- `PUBLISH`
- `UNPUBLISH`

Các cột `published_by` và `published_at` hiện hữu được tái sử dụng là actor/time của event; `action` xác định ngữ nghĩa. Mọi row cũ nhận default `PUBLISH`, không mất history.

Migration `v004_medical_knowledge_unpublish.py` là idempotent, không reset DB và không xóa dữ liệu. Kiểm thử isolated đã chạy `upgrade` hai lần, xác nhận row cũ là `PUBLISH`, sau đó `downgrade` và xác nhận row cũ vẫn còn: **PASS**.

## Permissions

- Staff: allowed.
- Admin: allowed.
- Viewer: HTTP 403.
- Anonymous: HTTP 401.
- Staff/admin identity và display name trong response/audit được xác minh lấy từ access token và DB auth context.

## Atomicity, rollback, race and idempotency

Trong cùng transaction, service xác minh revision/topic/status/current pointer, CAS pointer từ exact revision sang `null`, tắt `parent_display_allowed`, append `UNPUBLISH`, rồi commit. Lỗi khi ghi audit đã được mô phỏng; pointer, flag và audit đều rollback về trạng thái Publish ban đầu.

CAS và các interleaving Publish/Unpublish đã chứng minh không thể kết thúc với pointer/flag lệch nhau hoặc hai visibility flag cùng true. Request Unpublish lặp lại chọn behavior **HTTP 409** và không tạo event `UNPUBLISH` thứ hai.

Sau withdrawal, cùng revision vẫn `APPROVED` nên Publish workflow hiện hữu có thể publish lại. Audit sequence đã xác minh: `PUBLISH -> UNPUBLISH -> PUBLISH`.

## Approval, medical content and side effects

- `status`, `reviewed_by`, `reviewed_at`: unchanged.
- Short/detailed explanation, limitations, evidence level/scope, source assessments: unchanged.
- Evidence snapshots, PubMed source links, prompt version và model ID: unchanged.
- LLM called: **NO**.
- PubMed called: **NO**.
- PMC called: **NO**.
- Weather API called: **NO**.

Kiểm thử chặn mọi external HTTP request trong Unpublish và vẫn hoàn tất thành công.

## Parent behavior

Sau Unpublish, public Medical Knowledge safe-read không còn trả Tier 2 cho topic/factor đó. Parent presentation loại bỏ Tier 2 nhưng ranking, Tier 1, symptoms, prevention và warnings vẫn giữ nguyên. Sau Publish lại, Tier 2 xuất hiện lại. Publication của topic khác không bị ảnh hưởng.

## Frontend

Chỉ staff/admin xem revision `APPROVED` hiện hành mới thấy nút **Ngừng xuất bản**. Dialog xác nhận nói rõ Parent sẽ không còn thấy giải thích, trong khi revision vẫn Đã duyệt và không bị xóa. UI có Cancel, loading state và safe error mapping.

Sau success, badge `ĐANG XUẤT BẢN` biến mất; `APPROVED — Đã duyệt`, nội dung read-only và nút Publish xuất hiện lại.

## Automated E2E

SQLite isolated/test DB đã chạy:

1. Revision 1 DRAFT -> APPROVED -> PUBLISH; Parent safe-read trả Revision 1.
2. UNPUBLISH Revision 1; pointer `null`, flag `false`, status vẫn `APPROVED`, Parent trả no item.
3. PUBLISH Revision 1 lại; Parent trả item lại.
4. Revision 2 DRAFT -> APPROVED -> PUBLISH.
5. Unpublish Revision 1 bị từ chối, không đổi state.
6. Unpublish Revision 2 thành công; publication được clear.
7. Topic khác vẫn trả publication bình thường.

Kết quả E2E cuối cùng: `1 passed in 0.66s`.

## Validation results

- Backend focused Draft/Publish/Parent/Unpublish: **99 passed**.
- Backend Unpublish focused: **10 passed**.
- Backend full suite: **301 passed, 0 failed** in 11.25s.
- Frontend focused Medical Knowledge + Parent: **63 passed**.
- Frontend full suite: **124 passed, 0 failed**.
- TypeScript typecheck: **PASS**.
- Vite production build: **PASS**, 2302 modules transformed.
- `git diff --check`: **PASS**; chỉ có cảnh báo line-ending LF/CRLF hiện hữu.

## Startup

- Executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`.
- Prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`.
- Python: 3.11.15.
- `pip check`: **PASS**, no broken requirements.
- Changed modules compile/import and `import app.main`: **PASS**.
- Full FastAPI lifespan + migrations trên temporary SQLite: **PASS**, root HTTP 200 và cột `action` tồn tại.
- Bounded Uvicorn trên `127.0.0.1:8767`, lifespan tắt vì lifespan đã kiểm tra riêng trên DB tạm: **PASS**, HTTP 200; process được dừng có kiểm soát sau đó.

## Production database integrity

Không Unpublish hay tạo publication test trong production. E2E/migration/lifespan đều dùng DB tạm. Trong cửa sổ integrity bao quanh E2E cuối, count và SHA-256 nội dung của tất cả bảng Medical Knowledge giống hệt trước/sau:

| Table | Rows | SHA-256 |
|---|---:|---|
| `medical_evidence_contents` | 1 | `839a3a1c6dbbc46366989a9888f4291d92d1f59bac98d3fe997fcdb2440ecb29` |
| `medical_evidence_sources` | 4 | `37abeb385313a46963f40f007ff32733657a7893a8104cadbd20121362d421a4` |
| `medical_knowledge_publications` | 0 | `ca6d38512d732f5f13a9d21399ac4a915f82487aac6f4fda27f4df1f61dbf645` |
| `medical_knowledge_revisions` | 6 | `c4ebc7253566cb2b6ee1b7d4be731ed684fc28f5635de93badc953c44468b90d` |
| `medical_knowledge_topics` | 2 | `9db72d23cf7b45322ef2fe310702b803e84e5728ff943b4072d6f7219c218eac` |
| `medical_revision_sources` | 12 | `5d77c623dec309750a97b6c9af26b34ee42c638cc4c2d0b5b05dd42d8a4d717c` |

`production_database_modified=false` có nghĩa validation không thay đổi business rows. Cột schema `action` là migration v004 chủ đích của feature; development Uvicorn `--reload` do người dùng đang chạy có thể tự áp dụng migration này khi source reload. Không dừng hay can thiệp process do người dùng sở hữu.

## Files added

- `seasonal_disease_backend/migrations/v004_medical_knowledge_unpublish.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_unpublish.py`
- `weather_disease_ai_v3/medical_knowledge_v1_unpublish/MEDICAL_KNOWLEDGE_UNPUBLISH_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_unpublish/medical_knowledge_unpublish_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/app/medical_knowledge_draft_schemas.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_drafts.py`
- `seasonal_disease_backend/app/services/medical_knowledge_publication_service.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftReviewForm.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
- `Frontend/src/app/components/ParentPortal.test.tsx`

## Limitations

- Audit giữ tên cột legacy `published_by`/`published_at` cho cả hai action; consumer phải đọc kèm `action`. Cách này tránh migration đổi tên/destructive và bảo toàn history.
- SQLite không cung cấp row-level `FOR UPDATE` như các DB server; consistency trong runtime hiện tại được bảo vệ bằng atomic transaction, exact-pointer CAS và retry. Các stale/interleaving case đã được test tự động.

## Manual test

**USER MANUAL TEST REQUIRED = NO**

Automated backend/frontend regression, auth, rollback, migration, E2E, Parent withdrawal/return, startup/build và production table integrity đã đủ cho phạm vi task.
