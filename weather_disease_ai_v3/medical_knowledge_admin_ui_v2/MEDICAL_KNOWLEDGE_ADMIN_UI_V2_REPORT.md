# MEDICAL KNOWLEDGE ADMIN UI V2 REPORT

## STATUS

**PASS về implementation và automated validation; MANUAL VISUAL REVIEW đang chờ.**

Giao diện Auto Medical Knowledge đã được chuyển sang information architecture “disease first”, toàn bộ test tập trung, typecheck, backend suite và production build đều pass. Manual visual review bằng trình duyệt tích hợp chưa thể thực hiện vì phiên Codex này không có browser surface `iab`; không sử dụng browser ngoài để thay thế vì workflow hiện hành không cho phép fallback đó.

## Branch và baseline

- Repository: `dauxanhduamuoi/Du_doan_benh_cho_tre`
- Branch: `feature/medical-knowledge-v1-20260820`
- Starting commit / HEAD khi thực hiện: `b72a9594fd265d67b988ae3b03ec316c1e2061bb`
- Ngày validation: 2026-09-10

## Git status

Worktree đang dirty và có các thay đổi từ các task Auto Medical Knowledge trước đó. Các file chính của UI V2 là:

- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- `Frontend/src/lib/autoMedicalKnowledgePresentation.ts`
- `Frontend/src/lib/medicalKnowledgeFactors.ts`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `weather_disease_ai_v3/medical_knowledge_admin_ui_v2/`

Các thay đổi sẵn có của Multi-Tier V2, regenerate và topic visibility được giữ nguyên; không reset hoặc ghi đè worktree. `git diff --check` pass, chỉ có cảnh báo line-ending LF/CRLF của Git trên Windows.

## UX problems found

- Disease ID và canonical factor key chiếm vị trí heading, khiến nhân viên phải nhớ mã nội bộ.
- Cùng một bệnh bị lặp qua nhiều topic card, làm trang dài và khó scan.
- Trạng thái xử lý, nội dung hiện có, tier, method, visibility và diagnostics cạnh tranh thị giác.
- Source/search/validation detail xuất hiện gần lớp nội dung chính, tạo cảm giác debug dashboard.
- Search không ưu tiên tên bệnh hoặc label yếu tố thân thiện.
- Wording visibility cũ có thể ngụ ý nội dung chắc chắn đang xuất hiện dù Reviewed vẫn có precedence.

## Information architecture chosen

Giữ hai vùng vì chúng trả lời hai câu hỏi nghiệp vụ khác nhau:

1. **Xử lý và trạng thái**: topic nào đang chờ, đang chạy, hoàn thành, thiếu bằng chứng hoặc lỗi.
2. **Nội dung hiện tại**: hệ thống đang có nội dung Auto nào, tier/method nào, đủ điều kiện dùng cho Parent hay bị ẩn.

Trong mỗi vùng, topic được nhóm thành disease accordion. Disease đầu tiên mở mặc định; disease đóng vẫn hiển thị tên, mã phụ, số topic và summary trạng thái. Topic row hiển thị factor, status và action cần thiết. Search, source, history và technical diagnostics nằm trong disclosure thứ cấp.

## Disease-first design

- Tên nhóm bệnh là heading nổi bật nhất.
- Disease ID chỉ xuất hiện dưới dạng metadata `Mã nhóm #...`.
- Không có mapping ID → tên bệnh trong React.
- Nhiều factor cùng bệnh nằm trong một disease section, giảm lặp và chiều dài trang.
- Tên bệnh dài dùng `min-w-0`/truncate ở summary và nội dung co giãn theo viewport.

## Disease name data source

DTO job và revision được bổ sung `disease_group_name`. Backend resolve tên từ source of truth triển khai hiện có qua `load_deployed_disease_contexts(WEATHER_AI_V3_MODEL_MANIFEST, WEATHER_AI_V3_DISEASE_CATALOG)`.

Catalog được nạp một lần trong mỗi `overview()` rồi dùng lại cho toàn bộ job/revision. Test monkeypatch xác nhận loader chỉ được gọi một lần, do đó không tạo N+1 API/database request.

## Factor presentation architecture

`medicalKnowledgeFactors.ts` cung cấp typed, reusable `getFactorPresentation()` với:

- title;
- short label;
- category label;
- icon name;
- accessibility label;
- search terms gồm cả friendly label và canonical key.

Mapping hỗ trợ Weather, Age, Sex, Seasonality; temperature, humidity, precipitation/rain, wind và weather condition. Canonical keys backend được giữ nguyên nhưng không còn là main heading. Icon dùng lại `lucide-react`, không thêm UI framework/package mới.

`autoMedicalKnowledgePresentation.ts` tập trung mapping status → Vietnamese label/description/semantic tone, tier/method presentation và normalized search (bao gồm Unicode accents và dash variants).

## Visual hierarchy và status system

Thứ tự hiển thị:

1. Disease name;
2. Factor thân thiện;
3. Status;
4. Tier/method và visibility;
5. Evidence/source count và short explanation;
6. Actions;
7. Source/search/history/technical detail khi mở.

Status chỉ dùng năm tone hạn chế: success, warning, danger, processing và neutral. Raw enum không xuất hiện trong primary UI. FAILED có thông báo con người đọc được và nút Thử lại; technical code nằm trong disclosure. INSUFFICIENT được rút gọn, không hiển thị tier/method/visibility không áp dụng.

Strict, Basic AI và Basic Safe Template được phân biệt rõ nhưng đều giữ wording “Tự động”. Downgrade callout nhỏ, reason kỹ thuật không tràn ra card chính.

## Visibility presentation

- Topic bị hide: `Đã ẩn bởi nhân viên`.
- Parent Auto global OFF: `Auto đang tắt trên giao diện phụ huynh`.
- READY eligible khi fallback bật: `Đủ điều kiện hiển thị tự động`.
- Không dùng wording `Đang hiển thị` vì Reviewed vẫn có precedence.
- Hide/unhide refresh đúng canonical topic và không regenerate.

## Filter và search

Filter bar gồm search, status, Auto tier, factor group và visibility. Search match:

- disease name;
- disease ID;
- Vietnamese factor label;
- canonical factor type/key;
- factor value;
- chuỗi không dấu và dash Unicode tương đương.

Filter chạy local, giữ nguyên sau mutation/refresh và không phát sinh API theo từng card. Empty state có giải thích và nút `Xóa bộ lọc`.

## Responsive design và accessibility

- Desktop dùng hai cột processing/content; dưới breakpoint `xl` tự stack một cột.
- Runtime/settings, counters và filter dùng responsive grid, không có fixed card width.
- Buttons wrap, text container dùng `min-w-0`, source/query dùng break/truncate phù hợp.
- Button có accessible name; runtime dùng semantic `role="switch"` và `aria-checked`.
- Status luôn có text, không phụ thuộc màu.
- Accordion dùng native `details/summary`, hỗ trợ keyboard semantics.
- Input/select có label/`aria-label`; icon trang trí được ẩn khỏi accessibility tree khi phù hợp.
- Contrast dùng palette slate/blue/emerald/amber/red ở mức restrained.

Responsive DOM sanity, long disease name và long generated text đã có automated tests. Pixel-level responsive/contrast review vẫn thuộc manual visual checklist bên dưới.

## Component structure

Component chính giữ orchestration/polling/filter state. Các presentation boundary có ý nghĩa gồm:

- `DiseaseSection`;
- `FactorHeading` / `FactorIcon`;
- `StatusBadge`;
- `DiscoveryDetails`;
- `ValidationDetails`;
- `Disclosure`;
- `EmptyState`;
- centralized factor/status presentation utilities.

Không rewrite screen Reviewed hoặc thêm framework UI mới.

## Backend changes và database portability

Backend chỉ bổ sung display field `disease_group_name` vào admin overview job/revision DTO và resolve từ deployed catalog. Không thay model, migration hoặc business SQL cho UI V2. Không thêm SQLite-specific logic, PRAGMA, rowid hoặc query phụ thuộc SQLite; khả năng chuyển SQL Server không bị giảm.

## Functionality preserved

- Polling 3 giây chỉ chạy khi service ON và có current active job; không tạo interval trùng.
- Background poll failure giữ state xác nhận gần nhất.
- Regenerate/retry theo đúng canonical selector và khóa khi topic đang active/cooldown.
- Hide/unhide topic và refresh state giữ nguyên.
- Current/history và opt-in legacy history giữ nguyên.
- Runtime setting, Parent display mode và Basic fallback setting giữ nguyên.
- Không thay Reviewed precedence, publication, evidence qualification, Strict/Basic/Safe Template, Parent resolver, authorization hoặc visibility semantics.

## Validation results

- Frontend disease-first component suite: **51 passed, 0 failed**.
- Frontend regenerate/visibility API suite: **2 passed, 0 failed**.
- Backend Auto Medical Knowledge suite: **186 passed, 0 failed**.
- TypeScript: `tsc --noEmit -p tsconfig.json` — **PASS**.
- Production frontend build: `vite build` — **PASS** (2309 modules transformed).
- `git diff --check` — **PASS**.
- Backend warnings: deprecation warnings hiện hữu từ Starlette, `datetime.utcnow`, sqlite adapter và Pydantic config; không có test failure.

## External calls và production data integrity

- Live Groq calls: 0.
- Live PubMed calls: 0.
- Live PMC calls: 0.
- Production job retries: 0.
- Production data changed: no.
- Backend tests dùng SQLite in-memory, fake discovery và fake generator.

## Remaining limitations

- Manual pixel-level visual inspection chưa hoàn thành vì in-app browser surface không khả dụng trong phiên này.
- Disease accordion dùng native `details`; automated DOM tests xác nhận semantics, nhưng cần kiểm tra animation/spacing thực tế trên browser.
- Warnings deprecation backend là nợ kỹ thuật có sẵn, ngoài scope UI V2.

## Manual visual test required

Khi browser/local authenticated fixture sẵn sàng, cần kiểm tra thủ công:

- desktop wide, medium viewport và narrow/mobile;
- READY Strict;
- READY Basic AI;
- READY Basic Safe Template;
- INSUFFICIENT;
- FAILED;
- QUEUED/SEARCHING/GENERATING;
- hidden topic;
- Parent Auto global OFF;
- nhiều factor trong cùng disease;
- nhiều disease và disease name dài;
- search theo tên/ID/friendly factor/raw key/value;
- status/tier/factor/visibility filters và reset;
- mở source/search/history/technical disclosures;
- hide/unhide và regenerate;
- keyboard focus order, native details toggle, contrast và overflow.

Không cần live Groq/PubMed/PMC cho lượt review này; dùng local fixture hoặc local development data là đủ.
