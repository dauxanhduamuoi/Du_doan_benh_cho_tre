# AUTO MEDICAL KNOWLEDGE V1 — VALIDATION REPORT

## STATUS

`PASS_WITH_NOTES`

Auto Medical Knowledge V1 đã được triển khai như một subsystem độc lập, mặc định tắt và không làm thay đổi hành vi Parent hiện tại. Các ghi chú còn lại là giới hạn có chủ đích của V1: chưa có WHO/CDC provider thật, không chạy live external smoke, và chưa chạy toàn bộ regression ngoài phạm vi Medical Knowledge.

## Kiến trúc và dữ liệu

- Nhánh Reviewed được giữ nguyên lifecycle `DRAFT → APPROVED → PUBLISH/UNPUBLISH`, `published_revision_id`, `parent_display_allowed`, publication audit, Topic Source Library và explicit source selection.
- Auto tái sử dụng đúng canonical topic `(disease_group_id, factor_type, factor_key, factor_value)`, nhưng có bảng revision, source link, discovery audit, state và job riêng. Auto không có `APPROVED`, reviewer hay approved timestamp.
- Migration V008 hoàn toàn additive và idempotent. Sáu bảng Auto được thêm mà không rewrite hàng dữ liệu Reviewed.
- Auto revision là snapshot bất biến; regenerate tạo revision mới và state trỏ đến revision hiện tại. Nguồn/evidence snapshot dùng lại hạ tầng toàn cục, nhưng Auto không tự thêm nguồn vào Topic Source Library của Reviewed.

## Durable queue và Parent trigger

- Queue dùng SQLite làm nguồn sự thật, không dùng danh sách in-memory.
- Public Parent lookup chỉ thực hiện DB lookup/enqueue và trả về ngay; PubMed/PMC/LLM chỉ chạy trong background worker.
- Chỉ selector canonical thuộc 221 disease groups đang deploy mới được enqueue. Selector do Parent tạo vẫn xuất phát từ positive/upward Tier-1 contribution hiện có.
- Unique partial index bảo đảm tối đa một job active (`QUEUED/SEARCHING/GENERATING`) trên mỗi topic; transaction/CAS bảo vệ race.
- Demand signal chỉ lưu count và timestamp ở cấp topic, không lưu user/patient identity. Queue ưu tiên request count cao hơn, sau đó job cũ hơn.
- Job có retry count, retry delay, next retry, error code và concurrency limit cấu hình được.
- Job `SEARCHING/GENERATING` bị gián đoạn được chuyển sang trạng thái retryable lúc backend restart trước khi worker bắt đầu.
- Khi feature flag tắt, không tạo topic state/job và không khởi động worker.

## Trusted evidence discovery

Provider thực sự đã triển khai:

- `PUBMED`: tìm kiếm/metadata/abstract qua NCBI PubMed E-utilities.
- `PMC`: resolve PMCID và dùng nội dung PMC có provenance/license phù hợp; nếu không dùng được thì fallback về abstract PubMed.

Provider future-only, chưa được tuyên bố là đã triển khai:

- WHO, CDC.
- Official public-health agencies.
- Pediatric/professional medical organizations.
- Academic/trusted web providers ngoài PubMed/PMC.

Discovery dùng provider abstraction, tối đa ba query tập trung và tối đa 25 kết quả/query theo cấu hình, sau đó lọc/rank deterministic theo disease, pediatric, factor, evidence availability và trust class. Tối đa 10 nguồn được chọn. PMID được deduplicate. Provider gán trust class; persistence từ chối selected source ngoài `PUBMED/PMC`. Exact evidence content hash, retrieval metadata, selected source links và discovery decision/reason được lưu.

## Generation và evidence safety

- Auto dùng provider abstraction Groq/OpenAI/Ollama hiện có, nhưng dùng prompt/input builder riêng `medical_knowledge_auto_v1`.
- Input chỉ có disease group, factor canonical, pediatric group-level context và exact selected evidence; không có dữ liệu cá nhân.
- Không dùng LLM web tools. OpenAI Responses giữ `store=false`; các provider khác không có persistence/tool call trong request.
- Structured output phải assess đúng toàn bộ exact selected source IDs.
- Prompt cấm causal overclaim, cơ chế không có trong nguồn, fabricated study facts và personalized diagnosis.
- Validator fail-closed bổ sung từ chối ngôn ngữ causal/certain/personalized, cơ chế nhạy cảm không xuất hiện trong evidence, và số liệu không có trong evidence/context.
- `PEDIATRIC_DIRECT` vẫn là điều kiện bắt buộc để Auto claim đủ điều kiện Parent. Adult-only không thể tự tạo claim pediatric.
- `INSUFFICIENT` là kết quả hoàn tất hợp lệ: không lưu explanation giả, không hiển thị và không enqueue lại trước stale window trừ admin retry/regenerate.
- `CONFLICTING` không đủ điều kiện Parent và mặc định ẩn.

## Display policy và precedence

- Mặc định migration: `REVIEWED_ONLY`.
- Mặc định Auto feature: OFF.
- Mặc định Auto revision mới: `is_visible=false`.
- Mode tùy chọn: `REVIEWED_WITH_AUTO_FALLBACK`.
- Reviewed published hợp lệ luôn được resolve trước và luôn thắng Auto.
- Nếu Reviewed bị unpublish, Auto chỉ trở lại khi mode fallback đang bật và Auto revision còn `READY`, eligible, có pediatric-direct evidence và `is_visible=true`.
- Auto visibility chỉ là quyền hiển thị, không phải medical approval.
- Parent response có `knowledge_type=REVIEWED|AUTO`; Auto luôn có cảnh báo nguyên văn: “Giải thích tự động bởi AI — chưa được nhân viên y tế kiểm duyệt.”
- Parent frontend không suy luận type từ text; sanitizer yêu cầu field type/warning hợp lệ và fail closed.

## Staff/Admin UI

Khu vực Auto được đặt riêng khỏi Reviewed Draft Workspace và hiển thị:

- feature/display mode;
- queue status;
- disease/factor;
- generation/evidence status;
- explanation và references;
- visibility;
- last error;
- retry failed job;
- regenerate;
- `Cho phép hiển thị` / `Ẩn khỏi phụ huynh`.

UI nói rõ việc cho phép hiển thị không phải là phê duyệt y khoa. Staff có view read-only; admin có mutation actions.

## E2E bắt buộc

- `AUTO_DEMAND_GENERATION_E2E=PASS`
- `REVIEWED_OVERRIDES_AUTO_E2E=PASS`
- `AUTO_INSUFFICIENT_E2E=PASS`
- `AUTO_FAILURE_ISOLATION_E2E=PASS`
- `AUTO_JOB_DEDUP_E2E=PASS`

Các E2E dùng provider doubles deterministic, không gọi Internet hay LLM thật. Failure tests bao gồm discovery error, generation error, unsafe/malformed claim, unsupported trust class, adult-only evidence và restart recovery.

## Validation

- Backend focused regression: `399 passed`, `0 failed`, 2 warnings không chặn.
- Frontend focused tests: `170 passed`, `0 failed`.
- TypeScript typecheck: PASS.
- Frontend production build: PASS; chạy đúng một lần, 2,305 modules transformed.
- Python compileall: PASS.
- Backend import/startup/lifespan: PASS bằng `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`.
- HTTP root smoke: PASS.
- Migration chạy hai lần trên bản sao DB: PASS/idempotent.
- Production migration/startup: PASS với Auto feature OFF.
- SQLite foreign key check: PASS.
- Production Auto jobs/revisions sau startup: `0/0`.
- Focused Reviewed flow regression bao phủ search/import/explicit selection/Draft/Approve/Publish/Parent/Unpublish.

## Production integrity

- Nội dung các bảng Reviewed trước/sau migration/startup: hash bằng nhau.
- Không rewrite Reviewed revision, publication history, Topic Source Library hay evidence links.
- Production business Medical Knowledge data: không thay đổi.
- Production DB chỉ nhận schema Auto additive và singleton setting conservative.
- Forecast AI, LightGBM, Weather AI model, SHAP math và disease ranking semantics: không sửa.

## External calls trong validation

- Live LLM: `NOT_RUN`.
- Live PubMed: `NOT_RUN`.
- Live PMC: `NOT_RUN`.
- Trusted web: `NOT_RUN`.

Không secret nào được in. Đây là policy tùy chọn của task và không phải failure.

## Giới hạn còn lại

- V1 chỉ có source discovery thật cho PubMed/PMC; các trusted web families khác cần provider/API xác minh riêng.
- Worker là process-local consumer của durable SQLite queue, phù hợp deployment hiện tại nhưng không phải distributed scheduler nhiều host.
- Bulk generation/cancel queue là optional và chưa triển khai; V1 tập trung demand-driven generation và admin retry/regenerate.
- Semantic support tuyệt đối không thể được chứng minh chỉ bằng rule-based validation; V1 giảm rủi ro bằng closed evidence input, exact source mapping, pediatric gates, deterministic overclaim checks, default hidden và explicit admin visibility.
- Nên chạy một whole-project regression cuối và manual browser smoke trước release-closing milestone; không bắt buộc để hoàn tất task này.

## Manual test

`user_manual_test_required=false`

Khuyến nghị một manual smoke với feature được bật trên môi trường staging có cấu hình provider hợp lệ để quan sát worker và UI end-to-end; không cần dùng production data.
