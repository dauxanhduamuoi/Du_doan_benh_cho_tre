# MEDICAL KNOWLEDGE V1 — SOURCE LIBRARY VALIDATION REPORT

## STATUS

`PASS_WITH_NOTES`

Tất cả tiêu chí bắt buộc về kho nguồn theo chủ đề, lựa chọn nguồn rõ ràng cho Draft, validation phía backend, persistence qua restart, E2E cô lập, frontend, typecheck, build và startup đều PASS. Hai ghi chú không chặn release là: repository có thêm một file `database.db` 0 byte không được backend sử dụng; migration không tự backfill nguồn của các revision lịch sử nhằm không thay đổi dữ liệu nghiệp vụ hiện có.

## Root causes

Giao diện cũ dùng cùng một tập ID cho hai ý nghĩa khác nhau: nguồn vừa import và nguồn AI sẽ đọc. Nó không có màn hình đọc kho nguồn bền vững, nên sau import checkbox biến mất và staff không thể thấy chính xác title/PMID/evidence snapshot trước generation.

Backend cũ chỉ deduplicate PubMed source toàn cục. Không có association `(topic_id, source_id)`, vì vậy request Draft không thể chứng minh source thuộc đúng cặp disease group + weather factor. Đây cũng là boundary defect tái hiện được ở case Cúm: một source Viêm phổi toàn cục được gửi với selector Cúm. Production DB không có topic/revision Cúm tương ứng, xác nhận lỗi xảy ra trước persistence. Backend mới chặn deterministic trước LLM bằng `DRAFT_TOPIC_MISMATCH` nếu topic chưa tồn tại, hoặc `DRAFT_SOURCE_NOT_IN_TOPIC` nếu topic tồn tại nhưng source không thuộc kho đó.

Thông báo cũ còn gom nhiều lỗi 422 thành `Nguồn hoặc phạm vi tạo bản nháp chưa hợp lệ.`, che khuất các nguyên nhân như source sai topic, thiếu evidence, WHOLE_GROUP không có DIRECT và proposal AI sai cấu trúc.

## Persistence and database path

- Backend dùng đường dẫn tuyệt đối, ổn định: `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\seasonal_disease_backend\database.db`.
- Đường dẫn được resolve từ vị trí `app/database.py`, không phụ thuộc current working directory.
- Có hai file tên `database.db`:
  - file cấu hình thật ở `seasonal_disease_backend/database.db`;
  - file 0 byte ở repository root, không được backend sử dụng và không bị xóa/merge.
- Test SQLite file tạm đã tạo association, dispose engine, mở lại cùng path và đọc lại source thành công: `SOURCE_LIBRARY_RESTART_PERSISTENCE_TEST=PASS`.
- Source/evidence toàn cục trước task vốn đã persistent. Vấn đề chính là không có persistent topic membership và UI không có cách đọc lại library.

## Architecture and migration

Ba quan hệ nay tách biệt:

1. `MedicalEvidenceSource`: PubMed source toàn cục, tiếp tục reuse/deduplicate theo PMID.
2. `MedicalKnowledgeTopicSource`: source đã được staff thu thập cho đúng disease group + weather factor; khóa chính/unique `(topic_id, source_id)`, có `added_by`, `added_at` và index theo topic/source.
3. `MedicalRevisionSource`: immutable link tới đúng source và evidence snapshot thực sự được dùng cho một revision.

Migration `v005_medical_knowledge_topic_sources.py` là idempotent, non-destructive; clean upgrade, repeated upgrade, downgrade và upgrade trên schema v004 có revision/source lịch sử đều PASS. Migration không backfill revision lịch sử và không sửa revision/evidence hiện có. Tiến trình Uvicorn reload đang chạy của user đã áp dụng schema v005; bảng production mới có 0 dòng.

## API and import semantics

- `GET /api/medical-knowledge/topic-sources?disease_group_id=...&weather_factor=...` trả DTO staff-safe gồm source ID, PMID, title, journal/year, DOI, PMCID, evidence kind và added time; không trả evidence body.
- Search và direct PMID lookup trả riêng trạng thái `stored_globally` và `in_topic_library`.
- Import luôn nhận exact disease/weather selector, reuse global source/evidence nếu có và chỉ tạo association còn thiếu.
- Response phân biệt `source_reused`, `topic_link_created` và `already_in_topic_library`.
- Import lặp lại cùng source/topic không tạo association trùng; một global source có thể thuộc nhiều topic.

## UI and Draft selection

- Checkbox trong kết quả tìm kiếm chỉ dùng để thêm vào kho chủ đề.
- Source đã thuộc topic hiện badge `Đã có trong kho chủ đề`, checkbox import bị disable và không được tính vào bulk CTA.
- Source chỉ tồn tại global hiện `Đã lưu trong hệ thống` và vẫn có thể link vào topic hiện tại.
- Sau import, chỉ import selection được clear; library được refresh và source mới không tự động được chọn cho AI.
- Khu vực `Kho nguồn của chủ đề` tải độc lập từ persistent backend storage.
- Khu vực `Nguồn sẽ dùng cho bản nháp` hiển thị exact title, PMID, PMCID, evidence kind và nút bỏ từng nguồn.
- CTA hiển thị số nguồn động; không có nguồn thì disable.
- Keyword search/direct PMID mới không thay đổi Draft selection.
- Đổi disease group hoặc weather factor clear selection ngay; stale async response của topic cũ cũng bị bỏ qua.
- Draft request chỉ gửi exact `source_ids` đang được chọn trong topic library, tối đa 8 ID duy nhất.

## Backend validation and errors

Backend kiểm tra trước LLM: topic tồn tại và đúng selector, source tồn tại, source thuộc topic library, chỉ PubMed, evidence snapshot usable và thuộc đúng source, source IDs unique/bounded, input bounded. Không silently drop source và không fallback sang toàn bộ library, search selection hoặc revision trước.

Các mã lỗi cụ thể đã được đưa qua FastAPI và TypeScript client:

- `DRAFT_NO_SOURCES_SELECTED`
- `DRAFT_SOURCE_NOT_IN_TOPIC`
- `DRAFT_SOURCE_NOT_FOUND`
- `DRAFT_SOURCE_NO_USABLE_EVIDENCE`
- `DRAFT_SOURCE_EVIDENCE_MISMATCH`
- `DRAFT_SCOPE_WHOLE_GROUP_REQUIRES_DIRECT`
- `DRAFT_PROPOSAL_INVALID`
- `DRAFT_TOPIC_MISMATCH`

WHOLE_GROUP vẫn bắt buộc có ít nhất một assessment DIRECT. Source được staff chọn nhưng AI đánh giá `NOT_SUPPORTIVE` vẫn được giữ trong revision, không bị tự động loại.

## Targeted E2E

`SOURCE_LIBRARY_DRAFT_SELECTION_E2E=PASS`

Trên SQLite file tạm: tạo Pneumonia + humidity, thêm fixture A+B, dispose/reopen DB, xác nhận A+B còn trong library, chọn riêng A và tạo revision chỉ có A. Sau đó chuyển sang Influenza, xác nhận library/selection ban đầu rỗng, thêm/chọn C, tạo revision chỉ có C và không có source A/B.

Không gọi live Groq, PubMed hoặc PMC.

## Validation results

- Focused backend: `155 passed, 0 failed`; có 2 warning Pydantic deprecation từ class-based config hiện hữu, không ảnh hưởng test.
- Focused frontend: `70 passed, 0 failed` trong 2 test files.
- Restart persistence: `PASS`.
- Targeted E2E: `PASS`.
- Migration/startup/lifespan trên SQLite file tạm: `PASS`.
- HTTP root smoke qua `TestClient`: `PASS` (200).
- Python: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`, prefix đúng `seasonal_backend`, Python `3.11.15`.
- Frontend typecheck: `PASS`.
- Production build: `PASS` (Vite, 2303 modules transformed).
- Không chạy full 313 backend tests, full 124 frontend tests hoặc Weather AI E2E.

## Production DB integrity

Validation chỉ ghi vào SQLite file tạm. Logical count + SHA-256 của toàn bộ rows trong 7 bảng production Medical Knowledge giống hệt trước/sau:

| Table | Rows | SHA-256 |
|---|---:|---|
| `medical_evidence_sources` | 9 | `b440a666090072de51ec1eba7052a56067fc0cfe8bec8a6c85fb16df5371e95e` |
| `medical_evidence_contents` | 5 | `8fc1cb20b04b4215ca06f22e509595f14134c3a47fb7086ff2991e9ee44fefbc` |
| `medical_knowledge_topics` | 2 | `41f76607e814d8fd2d4eceb6d4df4339dada92112a0f39e8c954de1dc100c594` |
| `medical_knowledge_topic_sources` | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `medical_knowledge_revisions` | 11 | `c30e81dbdb12292154fb350374940b274f93300ce4b375fc5fb2c7d496ab7a9c` |
| `medical_revision_sources` | 20 | `769185da0c6877596e0864b89c2dc6e727560040b89bc6070e2184aaa7ef9d51` |
| `medical_knowledge_publications` | 3 | `61b31ba10f1fafc9c683ace91e9efc08a42cb9bdd32519cb4aae421d335cf3e9` |

Production business data modified by validation: `NO`. `.env` remained ignored/uncommitted; no secret was printed. LightGBM, SHAP, ranking, Tier 1, Weather AI, Parent Tier-2 policy, approval, publish and unpublish semantics were not changed by this task.

## Task files

Added:

- `seasonal_disease_backend/app/services/medical_knowledge_topic_source_service.py`
- `seasonal_disease_backend/migrations/v005_medical_knowledge_topic_sources.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_source_library.py`
- `Frontend/src/app/components/medical-knowledge/MedicalTopicSourceLibrary.tsx`
- `Frontend/src/lib/api.medicalKnowledgeErrors.test.ts`

Modified for this task:

- Backend models, schemas, repository, startup migration registration, PubMed router/service, Draft router/service/generator mappings and focused Medical Knowledge tests.
- Frontend API error parsing/contracts, research page, PubMed form/results/cards, Draft workspace and focused research tests.

## Remaining notes

- Historical revision sources are deliberately not backfilled into the new topic library. Staff can re-add/reuse those global sources for a topic without duplicating source/evidence rows.
- Automated acceptance does not require a manual test. A short browser visual smoke is still recommended before final UI release because spacing and responsive layout are best judged visually.

