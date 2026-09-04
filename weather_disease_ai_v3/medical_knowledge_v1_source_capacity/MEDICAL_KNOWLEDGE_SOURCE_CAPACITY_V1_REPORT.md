# MEDICAL KNOWLEDGE V1 — SOURCE CAPACITY

## STATUS

**PASS** — một Draft hiện hỗ trợ tối đa 10 nguồn AI-readable, trong khi nguồn không có evidence content vẫn được lưu để tham khảo nhưng không thể đi vào Draft basket.

## Old max source count

Giới hạn cũ là 8 tại config mặc định, schema, Draft service và UI. Draft service còn khóa cứng bằng `min(max_sources, 8)`.

## New max source count

Giới hạn mới là **10**. Giá trị mặc định, `.env.example`, local ignored `.env`, structured provider output, Draft/public response contract, backend service và frontend đều đã được đồng bộ. Local `.env` chỉ đổi `MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES` từ 8 thành 10; file vẫn được Git ignore và không có secret nào được đọc/in/thay đổi.

## Existing total evidence/input bound

- Tối đa **6.000 ký tự mỗi nguồn**.
- Tối đa **60.000 ký tự cho toàn bộ generation input**.
- Snapshot mới được bound khi resolve; snapshot cũ quá dài tiếp tục được bound phòng thủ trước khi gửi provider.
- Tăng số lượng nguồn không bỏ qua giới hạn tổng. Request vượt trần tổng vẫn bị từ chối trước provider.

## Unusable-source behavior

Backend Topic Source Library chỉ báo `content_kind` khi preferred evidence thực sự có text không rỗng. Source không đọc được hiển thị `AI chưa có nội dung để đọc` và `Nguồn vẫn được lưu trong kho để tham khảo.` Checkbox bị disable. Reimport/enrichment tạo được evidence mới sẽ làm source có thể chọn lại mà không tạo bản ghi nguồn trùng.

## Source-selection UX

UI hiển thị bộ đếm `X / 10 nguồn đã chọn`. Khi đạt 10, các source usable chưa chọn bị disable cho tới khi staff bỏ một lựa chọn. Draft basket lọc lại theo trạng thái AI-readable, hiển thị đúng số tài liệu và button động `Tạo bản nháp bằng AI từ X nguồn`.

Khi refresh thư viện, ID không còn tồn tại hoặc không còn usable bị loại khỏi selection. UI báo không chặn luồng: `N nguồn đã được bỏ khỏi bản nháp vì AI không còn nội dung khả dụng để đọc.`

## Select-all behavior

`Chọn tất cả nguồn AI đọc được`:

- 10 usable: chọn đủ 10.
- 8 usable + 2 unusable: chỉ chọn 8.
- Trên 10 usable: chọn 10 nguồn đầu tiên theo stable Topic Library ordering, hiển thị rõ tổng số và giới hạn; staff có thể bỏ/chọn lại để quyết định bộ 10 mong muốn.
- Không bao giờ chọn source không có evidence content.

## Backend validation

Backend tiếp tục fail closed và kiểm tra độc lập:

- phải có ít nhất một source;
- source ID dương và không trùng;
- tối đa 10 source;
- source tồn tại, là PubMed và thuộc đúng generic topic;
- mỗi source có preferred evidence text usable;
- evidence snapshot thuộc đúng source;
- per-source và total-input bound;
- provider phải đánh giá đúng mọi source đã chọn;
- revision provenance giữ nguyên đúng tập source request.

11 source trả `DRAFT_TOO_MANY_SOURCES` với thông báo `Một bản nháp hiện hỗ trợ tối đa 10 nguồn.` Source unusable trả `DRAFT_SOURCE_NO_USABLE_EVIDENCE`; backend không tự bỏ ID rồi generate từ phần còn lại.

## Files changed

Backend:

- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/app/medical_knowledge_draft_schemas.py`
- `seasonal_disease_backend/app/published_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/services/medical_evidence_content_service.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_service.py`
- `seasonal_disease_backend/tests/test_medical_evidence_content.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_drafts.py`

Frontend:

- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalTopicSourceLibrary.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeGeneralFactors.test.tsx`

Local configuration:

- `seasonal_disease_backend/.env` — ignored, chỉ đổi non-secret max-source value thành 10.

## Focused backend tests

**PASS — 256 passed, 0 failed.** Hai cảnh báo deprecation Pydantic có sẵn, không liên quan tới task. Coverage gồm 1/8/9/10 nguồn được chấp nhận, 11 nguồn bị từ chối với code riêng, duplicate, unusable/mixed request, topic/evidence ownership, per-source/total bounds, exact provenance, factor/pediatric policy, source library, PubMed service và public safe-read regression.

## Focused frontend tests

**PASS — 136 passed, 0 failed trong 5 file.** Coverage gồm usable/unusable UI, label, disabled control, basket filtering, đủ 10 nguồn, source thứ 11, select-all, stale recovery, re-enrichment, import không auto-select, error mapping, generic factors và published-read regression.

## E2E

`TEN_SOURCE_DRAFT_E2E=PASS`.

Isolated deterministic DB/provider đã xác minh:

1. Tạo topic và gắn 10 source usable.
2. Generator nhận đúng 10 normalized source.
3. Draft được persist với đúng 10 revision-source link và sort order 0–9.
4. Revision vẫn APPROVE được theo policy hiện tại.
5. Request 11 source bị từ chối trước provider, không persist revision.
6. Mixed usable/unusable request bị từ chối fail closed, không persist revision.

## Typecheck/build/startup

- TypeScript typecheck: **PASS**.
- Production Vite build, chạy đúng một lần: **PASS**, 2.304 modules, 4,02 giây.
- Backend import/lifespan/migrations: **PASS** bằng `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`, Python 3.11.15.
- HTTP root smoke: **200 PASS**.

## External live calls

- Groq/OpenAI/Ollama: **không gọi**.
- PubMed: **không gọi**.
- PMC: **không gọi**.

## Production DB integrity

**PASS** — snapshot count/hash nội dung của topics, revisions, topic-source links, revision-source links, publications, evidence sources và evidence contents giống hoàn toàn trước/sau startup validation. `PRAGMA foreign_key_check` sạch. Task không có migration và không sửa production business data.

## Remaining limitations

- Readability ở UI dựa trên trạng thái evidence do backend trả về; nếu evidence thay đổi trong race sau refresh, backend vẫn từ chối fail closed và UI xóa selection lỗi.
- Khi có hơn 10 source usable, Select All chọn 10 nguồn đầu theo stable library ordering; staff phải bỏ/chọn lại nếu muốn một bộ 10 khác. Không có relevance ranking hoặc AI auto-selection.
- Một source AI-readable vẫn có thể được AI đánh giá `INDIRECT` hoặc `NOT_SUPPORTIVE`; readability không đồng nghĩa với giá trị y khoa.

## Manual test required or not

`user_manual_test_required = false`. Focused regression, deterministic E2E, typecheck, production build, startup/HTTP và DB integrity đều PASS. Manual visual walkthrough là tùy chọn, không phải release blocker.
