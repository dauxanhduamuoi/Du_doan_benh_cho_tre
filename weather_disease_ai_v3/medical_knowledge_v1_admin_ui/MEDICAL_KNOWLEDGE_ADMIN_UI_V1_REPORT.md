# Medical Knowledge Admin UI V1 Report

## Status

**PASS** — Workspace “Kho kiến thức y khoa” cho admin/staff đã được triển khai, kết nối PubMed search/import backend, có protected lightweight options endpoint và pass toàn bộ test/typecheck/build. Browser QA đã được thử nhưng browser surface không khả dụng; static responsive/accessibility review đã hoàn tất.

## Frontend audit

- Stack: React 18.3, TypeScript 5.8, Vite 6.4 và Tailwind CSS 4.
- Routing nội bộ không dùng React Router; authenticated application dùng `activeTab` trong `AppShell`. Parent UI được tách bằng pathname `/phu-huynh`/`/parents` trước AuthProvider.
- Auth state duy nhất: `AuthContext`, token thông qua shared `lib/api.ts`; không tạo auth/JWT state thứ hai.
- Role canonical: `admin`, `staff`; permission/tab visibility nằm trong `app/navigation.ts`.
- Admin và staff dùng chung sidebar/layout. Settings là khu vực admin-specific trong shared shell.
- API convention: generic authenticated `request<T>()`, `ApiError`, Vite proxy `/api` sang FastAPI.
- UI convention: Tailwind utility, white card/slate border, rounded-xl/2xl, blue primary, inline loading/error/status.
- Responsive convention: grid/flex breakpoint, `min-w-0`, wrapped text, cards thay vì table cho dữ liệu dài.
- Test stack: Vitest 3.2 + Testing Library + jsdom.

## Route/navigation integration

Project không có URL route cho từng dashboard page, vì vậy workspace được thêm theo convention thật dưới tab ID `medical-knowledge`, label “Kho kiến thức y khoa”, lazy-loaded trong `AppPages`.

- Admin: thấy menu và truy cập được.
- Staff: thấy menu và truy cập được, không phụ thuộc feature permission khác.
- Role khác: menu bị lọc bởi `canAccessTab`; page có guard thứ hai và trả thông báo 403-style.
- Anonymous: AuthGate tiếp tục đưa về LoginPage.
- Parent/anonymous public route: không dùng AppShell nên không thấy menu và không truy cập tab.

Không thêm React Router hoặc refactor routing toàn frontend.

## Disease-group options source

Endpoint `/api/weather-ai/options` hiện load model registry/221 LightGBM boosters nên không được reuse cho UI metadata.

Một read-only protected endpoint mới đã được thêm:

`GET /api/medical-knowledge/options`

Endpoint:

- admin/staff only;
- đọc/cache `disease_order` từ deployment `model_manifest.json`;
- đọc tên từ canonical `data/processed/disease_catalog.csv` bằng standard CSV parser;
- kiểm tra catalog bao phủ đúng 221 deployed IDs;
- giữ deployment order;
- trả `{id, name}` và canonical weather factors/nhãn Việt;
- không import model registry, không load booster, không tạo DB catalog.

`backend_options_endpoint_added = true`.

## Page/component layout

- `MedicalKnowledgeResearchPage.tsx` (208 dòng): auth guard, load options, orchestration search/import/state.
- `PubMedSearchForm.tsx` (231 dòng): disease/weather selection, disease-term editor, advanced controls.
- `PubMedResults.tsx` (82 dòng): count, select all, query details, import action.
- `PubMedResultCard.tsx` (79 dòng): paper metadata, checkbox, abstract, external link.
- `medicalKnowledgeApi.ts` (92 dòng): API types/contracts/error mapping.

Page không phải monolith; API/network không nằm trong JSX presentation và result card không duplicate orchestration.

## Search form behavior

Form có ba bước rõ:

1. Chọn disease group bằng `ID — tên canonical`.
2. Chọn weather factor từ backend vocabulary với nhãn Việt.
3. Nhập thuật ngữ y khoa tiếng Anh dạng chip.

Search button disable khi thiếu group/factor/term, year range sai hoặc request đang chạy. Loading label là “Đang tìm tài liệu…”, ngăn double submit.

Advanced options collapsed mặc định:

- `max_results`: 10, 15, 25; default 10;
- optional `year_from`/`year_to`: 1800–2100 và kiểm tra thứ tự.

Frontend gửi đúng backend contract, không gửi raw query syntax tự viết.

## Disease-term UX

- Label/helper nói rõ PubMed chủ yếu dùng thuật ngữ y khoa tiếng Anh.
- Enter hoặc nút “Thêm từ khóa” tạo chip.
- Nút xóa có accessible name.
- Trim whitespace, 2–120 chars, tối đa 8, case-insensitive dedup.
- Chặn quote/square bracket/newline làm hỏng query structure.
- Không hardcode/prefill bản dịch Việt→Anh và không gọi AI.
- Đổi disease group xóa cả chip, input draft, result, selection và feedback.
- Đổi weather factor giữ terms nhưng xóa result/selection/feedback.

## PubMed result UX

- Header “Tìm thấy X tài liệu” và selected count.
- Generated query nằm trong “Chi tiết tìm kiếm” collapsed, không lấn UI chính.
- Card hiển thị checkbox, title, year, journal, authors, PMID, DOI nếu có, abstract và canonical PubMed link.
- Missing DOI không render row rỗng.
- Missing abstract hiển thị thông báo cụ thể.
- Abstract dài preview 320 chars; toggle “Xem tóm tắt đầy đủ”/“Thu gọn”.
- Nested/long text dùng wrapping; không dùng fixed height.
- Zero result là trạng thái 200 thân thiện, không phải error.

## Selection/import UX

- Checkbox riêng và “Chọn tất cả kết quả”.
- Selected count hiển thị rõ.
- Sticky import action responsive; disabled khi zero selected hoặc đang import.
- Frontend chỉ gửi `{"pmids": [...]}`; không gửi title/abstract.
- Sau import, message giải thích `created_count` và `reused_count`; reuse không bị coi là lỗi.
- PMID trả về được mark “Đã có trong kho”; selection được clear.
- Không tự tạo topic/revision/explanation/draft và không approve/publish.

## Error/loading/empty UX

Shared API module map:

- 401: phiên đăng nhập hết hạn/không hợp lệ;
- 403: không có quyền;
- 404: group ngoài Weather AI deployment;
- 503: PubMed chưa cấu hình;
- 502: không thể kết nối PubMed;
- 422: input không hợp lệ;
- network: không thể kết nối máy chủ.

Message không expose stack trace/path/API key. Options, search và import có loading/error/status riêng; status dùng `role=alert`/`role=status` và `aria-live`.

## Responsive/accessibility review

Static desktop review: **PASS**.

- Form dùng 2-column ở desktop; paper cards scan dễ; max width 6xl.
- Metadata wrap; query/DOI dùng `break-words`/`break-all`.

Static mobile/tablet review: **PASS**.

- Sidebar nội bộ mặc định thu gọn dưới 1024px; shell padding responsive.
- Form controls/card stack; action buttons full width phù hợp.
- Không có result table hoặc horizontal overflow bắt buộc.
- Checkbox size 20px, title/abstract wrap, không fixed-height cắt nội dung.

Accessibility:

- label/htmlFor đúng cho select/input;
- checkbox/term remove/external link có accessible name;
- keyboard Enter thêm chip;
- feedback không chỉ dựa vào màu mà có text/role;
- loading buttons có text và disabled state.

`VISUAL_BROWSER_QA = NOT_AVAILABLE`: browser skill đã được khởi tạo theo workflow nhưng in-app browser surface không khả dụng. Không cài browser framework khác. `SCREENSHOTS_CREATED = 0`.

## Files added

- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedSearchForm.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedResults.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedResultCard.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
- `Frontend/src/app/navigation.test.ts`
- `weather_disease_ai_v3/medical_knowledge_v1_admin_ui/MEDICAL_KNOWLEDGE_ADMIN_UI_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_admin_ui/medical_knowledge_admin_ui_v1_validation.json`

## Files modified

- `Frontend/src/lib/api.ts`: export shared authenticated request helper.
- `Frontend/src/app/navigation.ts`: new role-protected tab and access helper.
- `Frontend/src/app/AppPages.tsx`: lazy-load workspace.
- `Frontend/src/app/App.tsx`: use tab role guard và improve internal shell mobile padding/sidebar default.
- `Frontend/src/i18n/locales/vi.ts`: Vietnamese navigation label.
- `Frontend/src/i18n/locales/en.ts`: English navigation label.
- `seasonal_disease_backend/app/pubmed_schemas.py`: options response schemas.
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`: cached manifest/catalog metadata loader.
- `seasonal_disease_backend/app/routers/medical_knowledge_pubmed.py`: protected options route.
- `seasonal_disease_backend/app/main.py`: include options router.
- `seasonal_disease_backend/tests/test_pubmed_api_service.py`: options authorization/universe/no-model-load tests.

## Tests and validation

Frontend focused UI/navigation tests: **20 passed, 0 failed**.

Covered admin/staff render, unauthorized role, disease ID/name, weather labels, disabled validation, add/remove/dedup terms, exact request, loading, zero state, provider error, metadata, missing DOI/abstract, expand/collapse, selection/count, selected-PMID-only import, created/reused feedback, stale state reset, collapsed query and no LLM action.

Frontend full suite: **50 passed, 0 failed**, bao gồm existing Parent Weather AI tests.

Backend options/PubMed file: **20 passed, 0 failed**. Options additions cover anonymous, invalid role, admin, staff, exact deployed universe/canonical factors và test model-registry function bị patch để fail nếu bị gọi.

Backend full suite: **76 passed, 0 failed**.

- `npm.cmd run typecheck`: **PASS**.
- `npm.cmd run build`: **PASS** (2298 modules transformed; Medical Knowledge lazy chunk built).
- `python -m compileall -q app migrations tests`: **PASS**.
- `git diff --check`: **PASS**.
- Import/startup route sanity từ prior PubMed validation vẫn hoạt động; full backend import/test pass.

## Integrity confirmation

- No LLM/OpenAI/Gemini/Claude/local model.
- No explanation draft.
- No approve/publish workflow.
- Parent prediction/runtime and Parent UI semantics unchanged.
- Current Tier 1/Tier 2 runtime unchanged.
- LightGBM/model artifacts/model registry unchanged.
- SHAP, feature builder, ranking and prediction contract unchanged.
- `medical_knowledge_base.json` unchanged.
- No training/tuning/model selection.
- No frontend secret/config form; NCBI email/tool/API key remain backend-only.

## Remaining limitations

1. Browser visual QA/screenshots unavailable trong phiên; static responsive review và jsdom interaction tests đã pass.
2. Native disease `<select>` chứa 221 entries; tương lai có thể nâng thành searchable accessible combobox nếu staff cần tìm nhanh hơn.
3. UI chỉ biết PMID “đã có trong kho” sau import trong phiên hiện tại; options/search response chưa expose inventory status trước import.
4. Không lưu search history/form draft qua reload.
5. Live PubMed flow không chạy vì backend chưa có `NCBI_EMAIL`; mocked API flow và backend contracts đã được test đầy đủ.
6. Workspace nội dung V1 chủ yếu tiếng Việt; navigation có cả Việt/Anh nhưng full page translation chưa thuộc scope.

## Recommended NEXT step (không triển khai)

Thiết kế task riêng cho workflow chọn imported source → tạo explanation DRAFT bằng provider/LLM được cấu hình → medical review, với audit trail và không tự publish. Trước đó có thể bổ sung inventory status/searchable disease combobox dựa trên usage feedback. Không triển khai các bước này trong task hiện tại.

