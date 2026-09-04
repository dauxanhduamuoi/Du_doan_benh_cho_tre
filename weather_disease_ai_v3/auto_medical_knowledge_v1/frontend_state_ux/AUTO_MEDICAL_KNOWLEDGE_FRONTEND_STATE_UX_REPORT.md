# Auto Medical Knowledge Frontend State UX Report

## 1. Status

**PASS**

Hai lỗi frontend đã được xử lý trong phạm vi yêu cầu. Không thay đổi backend, dữ liệu y khoa, Reviewed workflow, cấu hình hay dependency.

## 2. Nguyên nhân trạng thái “Đang chờ” bị stale

`AutoMedicalKnowledgePanel` trước đây chỉ gọi overview khi component mount, khi người dùng bấm “Làm mới”, hoặc sau phần lớn action. Panel không có cơ chế revalidation trong thời gian worker tiếp tục đổi trạng thái job ở backend, nên một job `QUEUED` có thể nằm nguyên trên UI cho tới lần fetch tiếp theo hoặc F5.

Backend đúng: `GET /api/medical-knowledge/auto` gọi `AutoMedicalKnowledgeAdminService.overview()` cho mỗi request và đọc lại settings, cooldown, jobs và current revisions từ repository. Manual refetch vì vậy nhận được trạng thái mới; không cần sửa backend.

## 3. Polling implementation

- Interval: **3.000 ms**, khai báo bằng constant `AUTO_OVERVIEW_POLL_INTERVAL_MS`.
- Polling chỉ bắt đầu khi panel đang mounted, persisted Auto setting đang ON, và có ít nhất một current attempt ở trạng thái thực tế của project: `QUEUED`, `SEARCHING` hoặc `GENERATING`.
- Polling vẫn tiếp tục nếu provider cooldown còn active nhưng current job vẫn đang chờ.
- Polling dừng khi không còn current active job, khi service OFF, hoặc khi component unmount do rời Medical Knowledge.
- `READY`, `FAILED`, `INSUFFICIENT` và `CANCELLED` đều là terminal theo cơ chế allow-list active, nên không tạo request nền vô hạn.
- Cleanup dùng `clearInterval`; effect chỉ phụ thuộc vào điều kiện active dạng boolean nên update/rerender không tạo interval trùng.
- Guard in-flight ngăn các lần background poll/focus revalidation chồng request lên nhau.
- Lỗi của một background poll bị bỏ qua có chủ đích: overview xác nhận gần nhất vẫn được giữ, không tạo status `FAILED` giả và không spam alert. Nhịp sau vẫn retry.
- Manual “Làm mới” vẫn hiển thị lỗi theo luồng tương tác hiện có.
- Một lần revalidation im lặng được thực hiện khi window nhận focus.
- Retry, Regenerate, enable/disable Auto, đổi display mode và allow/hide revision đều chờ action rồi refetch trạng thái backend xác nhận. Enable/disable không còn chỉ dựa vào optimistic local settings.

## 4. Nguyên nhân reload quay về Tổng quan

Admin shell trước đây khởi tạo `activeTab` bằng local React state cố định là `dashboard`. Section không được ghi vào URL, vì vậy reload tạo component mới và luôn mất lựa chọn Medical Knowledge.

## 5. URL navigation strategy

URL query là nguồn sự thật cho section chính, dùng scheme:

`?section=medical-knowledge`

Giải pháp dùng native History API phù hợp với single-page shell hiện tại và không thêm router/dependency mới.

- Click section gọi `history.pushState`, cập nhật URL và UI.
- Reload/direct URL parse `section` và khôi phục đúng section.
- Back/Forward được đồng bộ qua listener `popstate`.
- Thiếu `section` hoặc giá trị không hợp lệ fallback về `dashboard` (Tổng quan) đối với Admin.
- Section hợp lệ nhưng không được role hiện tại cho phép cũng fallback an toàn; `canAccessTab` hiện có vẫn là authority.
- Không dùng localStorage làm navigation source.
- Các query parameter khác được giữ nguyên khi đổi section.

## 6. Files changed

- `Frontend/src/app/App.tsx`
- `Frontend/src/app/useAdminSectionNavigation.ts`
- `Frontend/src/app/useAdminSectionNavigation.test.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- Hai artifact validation trong thư mục report này.

Backend changes: **0**.

## 7. Validation

- Focused Auto panel tests: **26 passed, 0 failed**.
- Focused URL navigation tests: **7 passed, 0 failed**.
- Smallest shared navigation permission regression: **2 passed, 0 failed**.
- Tổng focused frontend: **35 passed, 0 failed**.
- TypeScript typecheck: **PASS**.
- Frontend production build: **PASS**; chạy đúng một lần.
- Backend tests: **NOT REQUIRED** vì backend không đổi.
- Groq live calls: **0**.
- PubMed live calls: **0**.
- PMC live calls: **0**.

Các test bao phủ idle/OFF không poll, active polling, `QUEUED → READY`, `QUEUED → FAILED`, retry kích hoạt lại polling, cleanup unmount, rerender không tạo interval trùng, request nền không overlap, polling failure giữ state, direct URL, click URL update, remount/reload, popstate, default/invalid URL và permission.

## 8. Integrity and limitations

- Không sửa Auto backend logic, Reviewed lifecycle, medical content, revision hay production database.
- Không sửa lỗi numeric `3`.
- Không thực hiện external live call.
- Độ trễ hiển thị trạng thái nền tối đa thông thường là một poll interval (khoảng 3 giây), đúng với bounded polling đã chọn.
- Không còn blocker trong phạm vi task; manual test bổ sung không bắt buộc.

