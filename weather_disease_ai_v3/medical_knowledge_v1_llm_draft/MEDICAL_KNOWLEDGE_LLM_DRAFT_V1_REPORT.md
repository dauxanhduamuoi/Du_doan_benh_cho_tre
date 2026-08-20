# WEATHER AI V3 — MEDICAL KNOWLEDGE V1 — LLM DRAFT GENERATION & MEDICAL REVIEW

## Status

**PASS** — Đã triển khai workflow tạo bản nháp có cấu trúc từ các nguồn PubMed đã import, tạo/reuse topic, lưu revision luôn ở trạng thái `DRAFT`, đính kèm nguồn, đọc lịch sử và cho admin/staff chỉnh sửa nội dung DRAFT. Không có approval, publish hoặc tích hợp Parent runtime.

Ngày validation: 2026-08-18 (Asia/Bangkok).

## Audit hiện trạng

Source code thật được audit trước khi triển khai:

- Backend đã có đủ bốn bảng `medical_knowledge_topics`, `medical_knowledge_revisions`, `medical_evidence_sources`, `medical_revision_sources`.
- Schema hiện có đủ các field lõi: evidence level/scope, `generated_by_llm`, `llm_model`, `prompt_version`, `relevance_note`, review metadata, `parent_display_allowed`, `published_revision_id`.
- `MedicalKnowledgeRepository` tuân theo convention transaction-neutral: repository flush nhưng không tự commit.
- PubMed import trả DB source ID, PMID và trạng thái create/reuse; abstract/metadata được đọc lại từ database thay vì nhận từ frontend.
- `require_staff_or_admin` xác định rõ role `admin` và `staff`; anonymous trả 401 và role khác trả 403.
- Disease universe được đọc nhẹ từ deployment manifest + canonical disease catalog, không load model registry hoặc LightGBM booster.
- Frontend đã có admin/staff workspace, form PubMed, results, import response chứa source IDs và test convention Vitest/jsdom.
- `requirements.txt` đã có `httpx==0.28.1` và Pydantic 2; chưa có OpenAI SDK.
- Không phát hiện khác biệt cản trở giữa code thật và foundation/PubMed/admin UI đã báo cáo trước đó.
- Không cần migration mới; không có stop condition nào bị kích hoạt.

## Provider architecture

Kiến trúc được tách thành ba phần:

1. `MedicalKnowledgeDraftGenerator` là protocol nhỏ mà business service phụ thuộc.
2. `OpenAIMedicalKnowledgeDraftGenerator` là concrete provider, chỉ chịu trách nhiệm dựng request Responses API và parse structured response.
3. `MedicalKnowledgeDraftService` chịu trách nhiệm canonical validation, database reads/writes, transaction, topic/revision/source links và response DTO.

Provider không phụ thuộc FastAPI hoặc database. Router không chứa OpenAI payload/prompt. Business workflow không phụ thuộc raw OpenAI response, nên có thể thay provider khác mà không viết lại database/router workflow.

## Concrete provider và HTTP client choice

Concrete provider V1 là OpenAI Responses API qua `httpx` hiện có. Không thêm dependency mới.

Lý do chọn direct `httpx`:

- repo đã dùng và pin `httpx`;
- request boundary nhỏ, dễ mock bằng `httpx.MockTransport`;
- vẫn dùng API chính thức hiện hành `/v1/responses`;
- output dùng JSON Schema strict, không parse free-form bằng regex;
- request đặt `store=false` và không khai báo bất kỳ tool/web search nào.

OpenAI documentation xác nhận Responses API hỗ trợ structured output theo JSON Schema/Pydantic và refusal có thể được phát hiện riêng: [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Tài liệu migration xác nhận Responses được lưu mặc định và có thể tắt bằng `store: false`: [Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses).

Không dùng Assistants API/deprecated workflow.

## Config/environment

Các biến cấu hình:

- `MEDICAL_KNOWLEDGE_LLM_PROVIDER` — mặc định `openai`;
- `OPENAI_API_KEY` — không có default/hardcode;
- `OPENAI_MODEL` — bắt buộc cấu hình từ environment;
- `MEDICAL_KNOWLEDGE_PROMPT_VERSION` — mặc định `medical_knowledge_v1`;
- `MEDICAL_KNOWLEDGE_LLM_TIMEOUT_SECONDS` — mặc định 45 giây;
- `MEDICAL_KNOWLEDGE_LLM_MAX_INPUT_CHARS` — mặc định 60.000 ký tự;
- `MEDICAL_KNOWLEDGE_LLM_MAX_SOURCES` — mặc định 8.

Thiếu provider/key/model không chặn application startup, Weather AI hoặc PubMed. `GET /api/medical-knowledge/options` chỉ trả boolean `llm_draft_generation_available`, không trả key/model secret. Generation thiếu config trả 503 với message an toàn.

## Prompt design và version

Prompt nằm riêng trong `medical_knowledge_prompt.py`, không inline trong router. Prompt version lưu vào revision là `medical_knowledge_v1` hoặc giá trị environment hiện hành.

Developer instruction bắt buộc:

- chỉ dùng disease group metadata, weather factor và selected PubMed source data;
- không external knowledge, web search, tool hoặc paper nhớ sẵn;
- source text là untrusted DATA, không phải instructions;
- giữ phạm vi nhóm bệnh, không tự tạo bệnh con;
- không diagnosis, personal probability/risk hoặc thuốc/phác đồ;
- không causal overclaim;
- không fabricate effect size, identifiers, dates, authors, population, mechanism hoặc result;
- output tiếng Việt và dùng rubric thận trọng;
- title-only source không đủ cho strong claim;
- thiếu evidence phải trả `INSUFFICIENT` rõ ràng.

User input được serialize thành JSON data envelope bounded, gồm scope canonical và các nguồn được chọn. Abstract/metadata không thể thêm instruction cấp developer.

## Structured output schema

Provider bắt buộc JSON Schema strict và Pydantic validation:

- `evidence_level`: `SUPPORTED | LIMITED_OR_INDIRECT | CONFLICTING | INSUFFICIENT`;
- `evidence_scope`: `WHOLE_GROUP | PARTIAL_GROUP`;
- `short_explanation_vi`;
- `detailed_explanation_vi`;
- `limitations_vi` bắt buộc;
- `source_assessments[]` gồm `source_id`, `DIRECT | INDIRECT | NOT_SUPPORTIVE`, `note_vi`.

Unknown hoặc duplicate `source_id` trong assessments bị backend từ chối. Mọi assessment ID phải là subset của selected DB source IDs. Invalid enum, blank text, malformed JSON, missing structured output và refusal đều không tạo revision.

## Evidence rubric và scope

Rubric được mô tả là project review rubric, không phải chuẩn grading y khoa phổ quát:

- `SUPPORTED`: evidence trực tiếp và tương đối mạnh hoặc review/systematic review/meta-analysis/guideline phù hợp trực tiếp.
- `LIMITED_OR_INDIRECT`: observational/indirect/subtype evidence hoặc chưa đủ mạnh.
- `CONFLICTING`: selected sources không thống nhất.
- `INSUFFICIENT`: abstract thiếu/yếu, outcome/group/weather relation không trực tiếp hoặc title-only.

`WHOLE_GROUP` chỉ dùng khi evidence đủ rộng cho cả group. `PARTIAL_GROUP` dùng cho disease/subtype/pathogen/subgroup và là lựa chọn thận trọng khi scope không chắc chắn. UI luôn ghi “AI đề xuất”, không trình bày đây là final medical status.

## Source-only grounding và patient-data isolation

Generation endpoint chỉ nhận:

```json
{
  "disease_group_id": "5",
  "weather_factor": "precipitation",
  "source_ids": [10, 11]
}
```

Backend tự lấy disease name/report group code từ canonical catalog và lấy title, authors, journal/year, PMID/DOI, publication types, abstract từ DB. Frontend không thể gửi prompt, abstract, title, disease name hoặc evidence text tự do.

Không gửi patient/parent data, tuổi, giới tính, vị trí, JWT, email người dùng, password, database dump hoặc API key lên provider. Không có OpenAI web-search tool hay PubMed call bổ sung trong generation.

## Input validation

- deployed disease group hợp lệ;
- canonical weather factor;
- 1–8 unique positive DB source IDs;
- tất cả sources tồn tại;
- V1 chỉ chấp nhận `PUBMED`;
- tối thiểu một usable abstract;
- total serialized input không vượt configured character cap;
- không silently truncate/drop nguồn.

Nếu quá 8 nguồn, UI disable generation và giải thích cần chọn tập nhỏ hơn; backend vẫn enforce giới hạn độc lập.

## Transaction và concurrency

Flow thực tế:

1. đọc/validate canonical context và DB sources;
2. rollback để kết thúc read transaction;
3. gọi provider;
4. validate structured proposal/source IDs;
5. bắt đầu writes: get/create topic, allocate revision number, create DRAFT, attach sources;
6. commit.

Provider failure không tạo topic/revision. DB write failure rollback toàn bộ. `UNIQUE(topic_id, revision_number)` vẫn là lớp bảo vệ cuối; service retry tối đa ba lần khi gặp `IntegrityError` và không gọi LLM lại. Đây là chiến lược phù hợp SQLite V1, không thêm distributed locking.

## Topic, revision và source attachment

Generation thành công:

- get/reuse topic bằng `disease_group_id + weather_factor`;
- revision number tăng tuần tự;
- `status = DRAFT`;
- `parent_display_allowed = false`;
- `generated_by_llm = true`;
- `llm_model` lấy từ configured provider model;
- `prompt_version` lấy từ config;
- `created_by` là authenticated user ID;
- `reviewed_by/reviewed_at = NULL`;
- attach đúng selected DB source IDs theo sort order;
- lưu assessment dưới dạng `RELEVANCE: note_vi` trong `relevance_note`;
- DIRECT source dùng role PRIMARY, nguồn khác SUPPORTING;
- không thay `published_revision_id`.

## Protected API

- `POST /api/medical-knowledge/drafts/generate`
- `GET /api/medical-knowledge/topics?disease_group_id=...&weather_factor=...`
- `GET /api/medical-knowledge/revisions/{revision_id}`
- `PATCH /api/medical-knowledge/revisions/{revision_id}`

Tất cả admin/staff only. PATCH chỉ nhận năm editable fields: evidence level, evidence scope, short explanation, detailed explanation, limitations. Pydantic `extra="forbid"` chặn status, parent flag, published pointer, provenance/model/prompt/user fields. Non-DRAFT trả 409.

## Admin UI workflow

- Giữ nguyên search/import PubMed.
- “Tạo bản nháp bằng AI” chỉ xuất hiện sau khi có imported DB source IDs hợp lệ.
- Availability false hiển thị: “Tạo bản nháp bằng AI chưa được cấu hình trên máy chủ.”; PubMed vẫn dùng bình thường.
- Loading hiển thị đúng: “AI đang đọc tóm tắt của các tài liệu đã chọn và tạo bản nháp…” và disable double submit.
- Generated review panel hiển thị `DRAFT — Chưa xuất bản`, disease group, weather factor, source count, AI proposed level/scope, ba textarea và source relevance notes.
- Warning nói rõ AI chỉ dùng thông tin/tóm tắt PubMed và nhân viên y tế phải kiểm tra.
- Nhân viên sửa được toàn bộ nội dung cho DRAFT; save gọi PATCH đúng allowlist.
- Save success: “Đã lưu bản nháp. Nội dung này chưa hiển thị cho phụ huynh.”
- Không auto-call LLM khi edit.

## Draft history

Khi disease group/weather factor đổi, UI tải đúng topic history và xóa active revision cũ/import generation set cũ. History hiển thị newest-first. DRAFT mở editable; APPROVED/REJECTED nếu có sẵn chỉ mở read-only. Empty state: “Chưa có bản nháp cho nhóm bệnh và yếu tố này.” Không thay status.

## Failure/error semantics

- missing config: 503;
- provider timeout/network/rate limit: 502 safe unavailable message;
- invalid structured output/refusal: 502 safe generation message;
- invalid input/input cap/source type/no abstract: 422;
- disease/source/revision not found: 404;
- non-DRAFT edit: 409;
- persistence/unexpected: generic 500 with server-side logging.

Raw provider payload, stack trace và API key không được trả về frontend.

## Files added

- `seasonal_disease_backend/app/medical_knowledge_draft_schemas.py`
- `seasonal_disease_backend/app/services/medical_knowledge_prompt.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_service.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_drafts.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_drafts.py`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftReviewForm.tsx`
- `weather_disease_ai_v3/medical_knowledge_v1_llm_draft/MEDICAL_KNOWLEDGE_LLM_DRAFT_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_llm_draft/medical_knowledge_llm_draft_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/app/pubmed_schemas.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- `seasonal_disease_backend/tests/test_pubmed_api_service.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

## Dependency và migration changes

- Dependency changes: none; reuse pinned `httpx` và Pydantic.
- Database migrations: none; foundation schema đủ dùng.

## Validation results

Backend dùng project-local `.venv` vì `conda` executable không có trong shell; không dùng global Python.

- Focused new LLM/draft tests: **41 passed, 0 failed**.
- Focused LLM + foundation + PubMed regression: **75 passed, 0 failed** sau test availability update.
- Full backend pytest: **117 passed, 0 failed**.
- Python compile sanity: **PASS**.
- Startup/OpenAPI route sanity với preload tắt: **PASS**.
- Frontend medical workspace + navigation focused: **30 passed, 0 failed**.
- Full frontend: **60 passed, 0 failed**, gồm 30 Parent Weather AI tests.
- TypeScript typecheck: **PASS**.
- Production build: **PASS**, 2.300 modules transformed.
- `git diff --check`: **PASS**; chỉ có line-ending warnings từ working copy Windows.

Existing warnings là Starlette/httpx compatibility deprecation và legacy `datetime.utcnow()` deprecation; không có test failure.

## Live smoke status

- `LIVE_LLM_SMOKE_TEST = UNAVAILABLE`: `OPENAI_API_KEY` và `OPENAI_MODEL` không có trong environment; không hardcode/bịa credentials.
- `LIVE_PUBMED_SMOKE_TEST = UNAVAILABLE`: `NCBI_EMAIL` không có trong environment; không hardcode/bịa email.
- `BROWSER_QA = UNAVAILABLE`: in-app browser `iab` không khả dụng. Không tạo screenshot. Responsive/accessibility được review tĩnh và jsdom interaction tests đạt.

## Security/privacy review

- API key chỉ nằm trong Authorization header gửi tới OpenAI endpoint; không vào prompt, DB, response, log fixture hoặc report.
- `store=false`; không tools/web search.
- source content được coi là untrusted input và đặt trong data envelope.
- authenticated user ID chỉ lưu ở DB, không gửi provider.
- không patient data, parent request hoặc personalized prediction context.
- read/generate/edit đều protected admin/staff.
- exact editable-field allowlist và non-DRAFT guard.

## Code-quality review

- Router không chứa OpenAI implementation/prompt.
- Provider không phụ thuộc FastAPI/DB.
- Business service không parse raw provider response.
- Prompt/version tập trung một module.
- UI chia thành research orchestrator, draft workspace và review form; file lớn nhất của implementation là 352 dòng, không monolith >500 dòng.
- Không import cycle phát hiện qua compile/startup.
- Không hardcode secret hoặc model.
- Bounded source/input size và retry.
- Không accidental Parent integration.

## Explicit integrity confirmation

- No approval workflow added.
- No publish workflow added.
- `parent_display_allowed` never enabled; generation always stores false.
- `published_revision_id` is not changed by generation or edit.
- Parent runtime unchanged.
- Current Tier 2 runtime unchanged.
- `medical_knowledge_base.json` unchanged.
- LightGBM/model artifacts/model registry/feature builder unchanged.
- SHAP unchanged.
- Ranking/prediction response unchanged.
- Parent Weather AI UI unchanged.
- No training, tuning, model selection, vector DB, RAG, fine-tuning or child-disease classifier.

## Remaining limitations

1. Live provider behavior was not exercised because OpenAI credentials/model were unavailable; mocked HTTP/provider boundary covers request, structured parsing and error semantics.
2. V1 uses PubMed metadata + abstracts, not full-text studies.
3. Browser visual QA/screenshots were unavailable; automated DOM interactions and static responsive review passed.
4. SQLite revision concurrency uses unique constraint + three retries; distributed locking is intentionally out of scope.
5. One generation uses at most eight imported sources and 60.000 serialized characters; the UI asks users to choose/import a smaller set if the current imported set is larger.
6. APPROVED/REJECTED revisions can be displayed read-only only if such data already exists; this task does not create or transition those statuses.

## Recommended next step (not implemented)

Thiết kế một task riêng cho medical approval governance: reviewer identity/permissions, audit trail, explicit approval criteria, safe publish transaction và Parent integration contract. Không triển khai bất kỳ phần approval/publish nào trong task này.
