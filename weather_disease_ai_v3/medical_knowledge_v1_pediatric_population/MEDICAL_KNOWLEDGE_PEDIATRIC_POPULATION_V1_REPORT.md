# MEDICAL KNOWLEDGE V1 — PEDIATRIC POPULATION VALIDATION REPORT

## 1. STATUS

`PASS_WITH_NOTES`

Các yêu cầu pediatric population, pediatric PubMed search, immutable revision assessment, Approval revalidation và Parent fail-closed đều đã hoàn thành. Ghi chú: live PubMed smoke là tùy chọn và không chạy; historical publications chưa có population metadata chủ động không còn đủ điều kiện Tier-2.

## 2. Root cause

Assessment cũ chỉ trả lời mức liên quan giữa disease group và weather factor. Vì vậy một nghiên cứu trực tiếp về humidity–pneumonia ở người cao tuổi vẫn hợp lệ là `DIRECT`, nhưng hệ thống không có chiều dữ liệu độc lập để biết nguồn đó không phải bằng chứng nhi khoa.

## 3. Existing DIRECT semantics vs new population semantics

`DIRECT | INDIRECT | NOT_SUPPORTIVE` tiếp tục chỉ mô tả disease/weather relevance. `population_relevance` mới mô tả pediatric applicability độc lập. Một nguồn có thể hợp lệ là `DIRECT + ELDERLY_ONLY`; không có phép chuyển đổi ngầm giữa hai chiều.

## 4. Population enum implemented

Đã triển khai và validate năm giá trị bounded: `PEDIATRIC_DIRECT`, `MIXED_AGE`, `ADULT_ONLY`, `ELDERLY_ONLY`, `UNKNOWN`, kèm `population_note` ngắn và grounded trong evidence được chọn.

## 5. Prompt version

Runtime sử dụng `medical_knowledge_v3_pediatric_population`. Prompt yêu cầu đánh giá độc lập disease/weather và pediatric population cho từng source, không suy đoán khi evidence không nêu tuổi, và không cho phép `SUPPORTED` nếu thiếu cùng một nguồn `DIRECT + PEDIATRIC_DIRECT`. Local `.env` chỉ được đổi `MEDICAL_KNOWLEDGE_PROMPT_VERSION`; các entry khác được giữ nguyên và `.env` vẫn được Git ignore.

## 6. Pediatric PubMed query behavior

Keyword query tự động tạo `(disease terms) AND (weather terms) AND (pediatric population terms)`. Pediatric clause chứa `Infant`, `Child`, `Adolescent` MeSH cùng `pediatric`/`paediatric` Title/Abstract terms, xuất hiện đúng một lần. User không cần nhập lại từ khóa nhi khoa. Mocked service search xác nhận query hoàn chỉnh không bị hỏng.

## 7. Direct PMID behavior

Direct PMID lookup tiếp tục fetch đúng article theo numeric PMID, không gọi keyword search và không áp pediatric clause. Adult/elderly article vẫn có thể được staff tra cứu và đưa vào Topic Source Library.

## 8. Parent pediatric eligibility rule

Parent Tier-2 giữ nguyên toàn bộ gate hiện hữu và thêm yêu cầu có ít nhất một source đồng thời `DIRECT` và `PEDIATRIC_DIRECT`. Source `NOT_SUPPORTIVE + PEDIATRIC_DIRECT` không được tính. Policy dùng chung cũng tính eligibility/reasons cho staff UI. Không tạo workflow status mới và không đổi Publish semantics.

## 9. Adult/elderly sources

Adult/elderly sources không bị xóa hoặc cấm lưu. Chúng có thể nằm trong library/revision, được giữ làm context bổ sung và có thể tạo/duyệt/publish revision ở mức phù hợp như `LIMITED_OR_INDIRECT`. Nếu toàn bộ bộ nguồn chỉ là adult/elderly/mixed/unknown, Parent safe-read không trả Tier-2. `SUPPORTED` bị backend từ chối nếu không có pediatric-direct support.

## 10. Old revisions without population metadata

Migration thêm hai cột nullable và không rewrite bất kỳ historical row nào. Reader trả population là `UNKNOWN`; database vẫn giữ `NULL`. Old publication không thể thỏa pediatric gate và fail closed cho đến khi staff tạo, duyệt và publish revision V3 mới. Đây là tác động an toàn có chủ đích.

## 11. Staff UI warnings/badges

Source card hiển thị badge tiếng Việt cho cả năm population category và hiển thị `population_note`. Khi thiếu source `DIRECT + PEDIATRIC_DIRECT`, UI hiển thị cảnh báo và derived Parent Tier-2 indicator với lý do cụ thể. Historical source thiếu field hiển thị `Chưa xác định đối tượng` và không crash.

## 12. Files added

- `seasonal_disease_backend/app/services/medical_knowledge_population_policy.py`
- `seasonal_disease_backend/migrations/v006_medical_knowledge_pediatric_population.py`
- `weather_disease_ai_v3/medical_knowledge_v1_pediatric_population/MEDICAL_KNOWLEDGE_PEDIATRIC_POPULATION_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_pediatric_population/medical_knowledge_pediatric_population_v1_validation.json`

## 13. Files modified

- Backend: `app/config.py`, `app/main.py`, `app/medical_knowledge_draft_schemas.py`, `app/medical_knowledge_models.py`, `app/medical_knowledge_schemas.py`, `app/routers/medical_knowledge_drafts.py`, `app/services/medical_knowledge_draft_service.py`, `app/services/medical_knowledge_approval_service.py`, `app/services/published_medical_knowledge_read_service.py`, `app/services/medical_knowledge_prompt.py`, `app/services/pubmed_query_builder.py`, `app/services/pmc_content_parser.py`.
- Backend focused tests: `test_medical_knowledge_drafts.py`, `test_medical_evidence_content.py`, `test_medical_knowledge_source_library.py`, `test_published_medical_knowledge_public.py`, `test_pubmed_api_service.py`, `test_pubmed_client.py`, `test_groq_medical_knowledge_provider.py`, `test_ollama_medical_knowledge_provider.py`.
- Frontend: `src/lib/medicalKnowledgeApi.ts`, `MedicalDraftReviewForm.tsx`, `PubMedSearchForm.tsx`, `MedicalKnowledgeResearchPage.test.tsx`.
- Local ignored config: `seasonal_disease_backend/.env`, chỉ prompt version.

## 14. Focused backend tests

`270 passed, 0 failed` với đúng Python `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` (Python 3.11.15). Có hai Pydantic deprecation warnings đã tồn tại, không ảnh hưởng kết quả. Không chạy full backend suite.

Coverage gồm query clause, direct PMID, năm enum, UNKNOWN từ abstract thiếu tuổi, immutable/legacy read, `DIRECT + ELDERLY_ONLY`, adult source retention, pediatric gate, NOT_SUPPORTIVE exclusion, SUPPORTED rejection, Approval revalidation, WHOLE_GROUP rule, Parent safe-read, replacement/unpublish và no provider call on Parent read.

## 15. Focused frontend tests

`100 passed, 0 failed` trên bốn focused files. Coverage gồm pediatric helper, keyword UI, năm badge, note, warning, eligibility true/false/reasons, historical missing field, Parent empty/noneligible behavior và Tier-1/failure isolation. Không chạy full frontend suite.

## 16. Targeted E2E

`PEDIATRIC_POPULATION_E2E=PASS` bằng in-memory temporary SQLite và deterministic generator.

- Flow A lưu hai source `DIRECT + ADULT_ONLY/ELDERLY_ONLY`, tạo Draft, Approve, Publish; Parent safe-read trả no Tier-2.
- Flow B tạo revision mới với source `DIRECT + PEDIATRIC_DIRECT`, Approve, Publish; Parent safe-read trả đúng revision mới.
- Mỗi generation fixture chỉ được gọi một lần; Parent read không gọi LLM, PubMed hoặc PMC.

## 17. Typecheck/build

- TypeScript: `PASS`.
- Focused frontend validation: `PASS`.
- Production frontend build: `PASS` (`vite build`, chạy đúng một lần).

## 18. Startup

Backend compile/import `PASS`. Uvicorn bằng exact seasonal_backend Python hoàn thành application startup/lifespan/migration. Local HTTP smoke: `/` = 200, `/docs` = 200, `/openapi.json` = 200. Server validation được shutdown sạch sau smoke.

## 19. Optional PubMed live smoke

`PEDIATRIC_PUBMED_LIVE_SMOKE=NOT_RUN`. Không cần live call vì deterministic query-builder và mocked service search đã PASS. Groq/OpenAI/PMC live call đều không chạy.

## 20. Production DB integrity

Migration V006 chỉ thêm `population_relevance` và `population_note` nullable vào `medical_revision_sources`. Cả 29 historical links vẫn có hai field `NULL`; không rewrite history.

Business row counts và SHA-256 trước/sau giống hệt:

- sources `17` — `ada4e49cf3f3d1c0871eaaa022d1e8695b55abee606390e01fc30f05e55d2d59`
- contents `14` — `5cfd2425c2527c34495dd4e46fa906902788378395af811d35ec756974a2d72c`
- topics `6` — `900ae655bf375889938e3546e0bbd969c9fd49a4f367ba0a5a5342a5ef7c13d1`
- topic-source links `14` — `e44e287701b489bb8852ba27fc87d5b6c8c829f950e499a66272e084a77e24c9`
- revisions `14` — `df5780c0da14e4fbf71f18bcb2c3c59f5011238e82e96c5cf64a4dcecccd25ed`
- revision-source legacy business columns `29` — `ec1541febedec105c71b4dfc2ee716de9abe043eb7514a83c21a53ed10ca6201`
- publications `4` — `87cf6ea34ade3128a45410273c27e7a1c6357abdf67970bafe69535166224eb2`

`production_business_data_modified=false`. Weather AI, LightGBM, SHAP, ranking, Tier-1 và medical business rows không bị thay đổi.

## 21. Remaining limitations

- Exact pediatric age-band matching vẫn ngoài V1 scope.
- Khi title/abstract/PMC evidence không nêu rõ population, kết quả cố ý là `UNKNOWN`.
- LLM classification vẫn cần human clinical review; không có live provider generation trong task này.
- Historical publication thiếu population metadata cố ý mất Tier-2 cho đến revision V3 mới.

## 22. Manual test required or not

`user_manual_test_required=false`. Automated focused validation, targeted E2E, typecheck, one build và real startup/HTTP smoke đều PASS. Một manual staff visual review là tùy chọn, không phải release blocker.
