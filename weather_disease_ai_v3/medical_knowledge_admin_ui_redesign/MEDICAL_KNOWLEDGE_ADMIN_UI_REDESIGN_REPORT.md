# MEDICAL KNOWLEDGE ADMIN UI REDESIGN V1

## 1. STATUS

**PASS_WITH_NOTES**

Admin Medical Knowledge đã được tổ chức lại thành hai workflow độc lập và dễ nhận biết: **Kiến thức đã kiểm duyệt** và **Kiến thức tự động**. Không thay đổi backend, API contract, dữ liệu nghiệp vụ hoặc điều kiện polling. Focused frontend tests, TypeScript typecheck và production build đều PASS.

Ghi chú duy nhất: phiên Browser tích hợp (`iab`) không khả dụng trong môi trường chạy, vì vậy chưa thực hiện được visual smoke trên trình duyệt thật. Nên kiểm tra nhanh desktop/tablet/mobile trước khi release.

## 2. Previous UI problems

- Reviewed và Auto nằm nối tiếp trên một trang dài nên khó xác định workflow hiện tại.
- Selector, tìm kiếm, kho nguồn, basket AI và revision thiếu phân vùng rõ.
- Auto hiển thị runtime, queue, revision và diagnostics trong một khối dày thông tin.
- Configuration chiếm vị trí nổi bật dù ít được sử dụng thường xuyên.
- History/diagnostics làm tăng chiều dài trang mặc định.

## 3. New information architecture

- Header quản trị chung với hai main tabs.
- `knowledgeView=reviewed|auto` lưu subview trong URL; giá trị thiếu/không hợp lệ mặc định về Reviewed.
- Back/Forward đồng bộ lại đúng subview qua `popstate`.
- Configuration là disclosure thu gọn, vẫn được load và giữ nguyên mọi action kiểm tra kết nối.

## 4. Reviewed layout

- Topic selector luôn hiển thị ở đầu workspace.
- Source workspace có ba tab: **Tìm tài liệu**, **Kho nguồn**, **Nguồn AI sẽ đọc**.
- Desktop dùng hai cột: source workspace bên trái, revision/review lifecycle bên phải; cột revision sticky nhẹ.
- Tablet/mobile tự xếp về một cột.
- Basket AI có số lượng, danh sách compact và action bỏ nguồn; generate draft vẫn ở revision workspace.
- Revision history mặc định thu gọn bằng accordion, nhưng dữ liệu vẫn được load theo workflow cũ.

## 5. Auto layout

- Header cảnh báo riêng, không dùng từ ngữ gây hiểu nhầm Auto là nội dung đã được phê duyệt.
- Runtime toggle và Parent display mode được gom thành hai control cards.
- Bốn summary cards: đang xử lý, hoàn thành, chưa đủ bằng chứng, lỗi.
- Frontend filters: từ khóa, status, generation mode và factor; thay đổi filter không gọi lại API.
- Queue và current revisions dùng layout hai cột trên desktop, một cột ở màn hình hẹp.
- Revision card hiển thị topic, status, visibility, generation mode, short summary và provenance compact trước; nội dung dài mở bằng accordion.
- Diagnostics, source detail và history mặc định thu gọn.

## 6. Config layout

Service Configuration được đặt trong disclosure thu gọn ngay dưới main tabs. Bên trong vẫn giữ nguyên trạng thái PubMed/LLM, provider/model indicators và hai connection-test actions. Không hiển thị secret value.

## 7. Responsive behavior

- Container tối đa `1440px` để tận dụng desktop.
- Reviewed và Auto chuyển sang hai cột ở breakpoint lớn; tự stack trên tablet/mobile.
- Main tabs, source tabs, filters và action groups cho phép wrap/co giãn.
- Text dài dùng truncate/line-clamp ở phần summary; detail mở theo nhu cầu.

## 8. URL behavior

- Main Admin section `?section=medical-knowledge` được giữ nguyên.
- Subview mới: `knowledgeView=reviewed|auto`.
- Direct link, reload và Back/Forward được cover bằng focused test.
- Invalid subview an toàn quay về Reviewed.

## 9. Polling behavior

Không thay đổi điều kiện polling: chỉ poll mỗi 3 giây khi persisted Auto setting đang bật và có current job ở `QUEUED`, `SEARCHING` hoặc `GENERATING`. Poll dừng khi terminal, dọn interval khi unmount, không overlap request, giữ state đã xác nhận khi background refresh lỗi và revalidate khi window focus.

## 10. Functionality inventory before/after

| Workflow | Action trước redesign | Sau redesign |
|---|---|---|
| Reviewed | Chọn disease group/factor/value | Giữ nguyên, selector luôn hiển thị |
| Reviewed | Guided PubMed search | Giữ nguyên trong tab Tìm tài liệu |
| Reviewed | Free PubMed query | Giữ nguyên trong tab Tìm tài liệu |
| Reviewed | Direct PMID lookup | Giữ nguyên trong tùy chọn nâng cao |
| Reviewed | Chọn kết quả/import vào topic library | Giữ nguyên |
| Reviewed | Xem/chọn tối đa 10 nguồn AI-readable | Giữ nguyên trong tab Kho nguồn |
| Reviewed | Xem/bỏ nguồn khỏi draft basket | Giữ nguyên trong tab Nguồn AI sẽ đọc và summary revision |
| Reviewed | Generate/edit/save draft | Giữ nguyên |
| Reviewed | Approve/publish/unpublish | Giữ nguyên permission, confirmation và lifecycle |
| Reviewed | Mở revision history | Giữ nguyên, mặc định thu gọn |
| Config | Xem status/test PubMed/test LLM | Giữ nguyên, panel mặc định thu gọn |
| Auto | Refresh overview | Giữ nguyên |
| Auto | Runtime ON/OFF | Giữ nguyên permission và persisted setting |
| Auto | Parent display mode | Giữ nguyên |
| Auto | Retry/regenerate | Giữ nguyên cooldown/busy guards |
| Auto | Visibility ON/OFF | Giữ nguyên, không gọi là approval |
| Auto | Queue/current revisions/history/diagnostics | Giữ nguyên, tổ chức thành dashboard/disclosures |

## 11. Files changed

- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalTopicSelector.tsx` (new)
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalDraftWorkspace.tsx`
- `Frontend/src/app/components/medical-knowledge/PubMedSearchForm.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`

## 12. Components added/refactored

- Added reusable `MedicalTopicSelector` so topic context is independent from the search form.
- Refactored `MedicalKnowledgeResearchPage` into URL-backed main tabs and a structured Reviewed workspace.
- Refactored `AutoMedicalKnowledgePanel` into controls, summaries, filters, queue and revision areas.
- Refactored `MedicalDraftWorkspace` with compact source summary and collapsed revision history.
- Added an optional `showTopicSelector` presentation prop to `PubMedSearchForm`; request state and handlers are unchanged.

## 13. Focused test result

**PASS — 191 passed, 0 failed, 5 test files.**

Covered Reviewed panel, Auto panel/polling, service configuration, general factors, navigation, new subview URL behavior and new Auto filters.

## 14. Typecheck

**PASS** — `tsc --noEmit -p tsconfig.json`.

## 15. Production build

**PASS** — Vite production build, 2308 modules transformed.

## 16. Backend changes

**0.** Không sửa backend trong task này.

## 17. External calls

- Groq: 0
- PubMed: 0
- PMC: 0

## 18. Remaining limitations

- Chưa có browser visual smoke vì in-app Browser không có phiên `iab` khả dụng.
- Disease/factor labels trong Auto tiếp tục dùng dữ liệu overview hiện có; không thêm lookup/API mới theo ràng buộc frontend-only.

## 19. Manual testing required

**YES — recommended.** Kiểm tra nhanh main/source tabs, accordion, overflow và hai cột ở khoảng 1440px, 1024px và 390px; không cần gọi PubMed/Groq/PMC để thực hiện layout smoke.
