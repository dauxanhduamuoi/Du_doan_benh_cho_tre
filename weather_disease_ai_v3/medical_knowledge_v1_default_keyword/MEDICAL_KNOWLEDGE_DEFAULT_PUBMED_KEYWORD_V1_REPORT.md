# MEDICAL KNOWLEDGE V1 — DEFAULT PUBMED KEYWORD REPORT

## STATUS

`PASS_WITH_NOTES`

## English disease name source

Medical Knowledge options hiện trả `id` và nhãn nhóm bệnh kết hợp trong field `name`, ví dụ:

`Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis`

Options hiện chưa có field English riêng ở cấp disease group. Cột `DiseaseCode.english_name` trong DB là tên của từng ICD con và không tương đương tên tiếng Anh của toàn nhóm; ví dụ group 170 có nhiều subtype khác nhau nên không được dùng thay thế.

Helper `getDefaultPubMedDiseaseKeyword` ưu tiên `english_name` structured nếu option có field này trong tương lai. Với contract hiện tại, helper fallback parse phần sau delimiter ` - ` đầu tiên. Việc dùng delimiter đầu tiên giữ nguyên đúng các English name tự chứa thêm ` - `.

Audit deployed catalog:

- 221 disease groups;
- 220 group labels có English suffix parse được;
- English keyword dài nhất 110 ký tự, nằm trong giới hạn 2–120 hiện tại;
- không có parsed keyword chứa ký tự PubMed bị cấm `"`, `[` hoặc `]`;
- group ID 313 không có English delimiter an toàn, nên UI không tự suy đoán từ khóa sai cho group này.

## Auto-fill behavior

- Chọn disease group sẽ clear keyword của disease trước và chèn đúng một English default keyword của disease mới.
- Group 170 tự điền `Acute bronchitis and acute bronchiolitis` và nút `Tìm tài liệu PubMed` dùng được ngay khi weather factor đã chọn.
- Chỉ đổi weather factor không thay đổi disease keywords và không thêm weather term vào chip list. Backend query builder vốn xử lý weather vocabulary riêng, nên không bị duplicate.
- Search PubMed, direct PMID lookup, mở advanced options và import source không reset default hoặc custom keywords.
- User vẫn có thể xóa default, thêm synonym và dùng tối đa 8 keywords.
- Action `Khôi phục từ khóa mặc định` xuất hiện khi keyword list đã bị chỉnh; click sẽ khôi phục đúng một default keyword và không duplicate.
- Direct PMID behavior, source library, Draft, Approval, Publish, Unpublish và Parent Tier-2 không thay đổi.

## Files modified

- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedSearchForm.tsx`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

Không có backend production file, migration hoặc database schema nào được sửa trong task này.

## Validation

- Focused baseline: 69/69 PASS.
- Focused final frontend tests: 79/79 PASS.
- TypeScript typecheck: PASS.
- Vite production build: PASS; 2303 modules transformed.
- Backend tests: không chạy vì backend/query builder không thay đổi.
- Live PubMed/PMC/Groq calls: không có.

Task này không thực hiện bất kỳ lệnh ghi Medical Knowledge DB nào. Active Uvicorn/user runtime vẫn chạy và DB thật đã có thêm business rows so với snapshot của task trước trong lúc làm việc; đây là hoạt động ngoài validation frontend này. Snapshot đọc-only sau implementation được giữ để kiểm tra artifact cuối.

Manual test không bắt buộc. Có thể thực hiện một visual smoke ngắn với group 170 để xác nhận bố cục chip dài trên kích thước màn hình thực tế.

