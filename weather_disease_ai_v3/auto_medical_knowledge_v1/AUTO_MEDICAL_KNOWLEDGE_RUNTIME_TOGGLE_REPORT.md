# AUTO MEDICAL KNOWLEDGE V1 — RUNTIME TOGGLE REPORT

## 1. STATUS

`PASS`

Admin có thể bật/tắt Auto Medical Knowledge ngay trên UI. Trạng thái được lưu trong SQLite, có hiệu lực với Parent và worker mà không sửa `.env`, không restart backend và không restart frontend.

## 2. Cơ chế cũ

Trước thay đổi này, `AUTO_MEDICAL_KNOWLEDGE_ENABLED` từ environment được đọc khi import backend:

- Parent queue service nhận một boolean cố định.
- Worker chỉ được tạo lúc backend startup nếu boolean là `true`.
- Thay đổi trạng thái yêu cầu sửa `.env` và restart backend.

## 3. Runtime source of truth mới

Singleton `auto_medical_knowledge_settings` hiện có cột persisted:

```text
enabled BOOLEAN NOT NULL DEFAULT 0
```

Đây là source of truth duy nhất cho ON/OFF vận hành. Environment flag cũ đã được loại khỏi config và `.env.example`; local `.env` không bị sửa.

Ba control độc lập:

1. `enabled`: có enqueue/process Auto hay không.
2. `display_mode`: Parent có cho phép Auto fallback hay không.
3. `revision.is_visible`: revision Auto cụ thể có được hiển thị hay không.

## 4. `.env` và restart

- `.env` edit required: `NO`.
- Backend restart required: `NO`.
- Frontend restart required: `NO`.
- Browser refresh đọc lại đúng trạng thái persisted.
- Sau backend restart, worker được tạo lại và đọc setting DB; default/migration vẫn OFF.

## 5. Admin UI

Panel Auto Medical Knowledge có switch Admin-only:

- OFF: `Bật Auto`.
- ON: `Tắt Auto`.
- Mutation đang chạy: `Đang bật…` hoặc `Đang tắt…`; control bị disable để chống click lặp.
- Chỉ cập nhật UI sau khi backend xác nhận; lỗi giữ nguyên trạng thái đã xác nhận trước đó.
- Lỗi toggle: `Không thể thay đổi trạng thái Auto Medical Knowledge.`
- Không đọc được setting: fail closed và không render switch.
- Nút `Làm mới` vẫn tải lại trạng thái persisted.

Helper text giải thích rõ dữ liệu/queue cũ không bị xóa và job đang chạy có thể hoàn thành an toàn.

## 6. Staff UI

Staff vẫn xem được:

- `Dịch vụ: Đang bật/Đang tắt`;
- helper text;
- queue, revisions, sources và display mode hiện tại.

Staff không thấy switch và không thể PATCH setting.

## 7. Parent khi OFF

- Reviewed lookup hoạt động bình thường.
- Tier 1/ranking/SHAP hoạt động bình thường.
- Không tạo topic demand/job Auto mới.
- Không gọi PubMed/PMC/LLM.
- Existing Auto content vẫn có thể hiển thị nếu display mode và per-revision visibility cho phép, vì display policy tách biệt với generation ON/OFF.
- Nếu không đọc được runtime setting, Parent fail closed: giữ Reviewed result, bỏ Auto và không phát sinh exception.

## 8. Worker khi OFF

- Worker task luôn tồn tại trong lifespan để có thể resume mà không restart.
- Mỗi vòng lặp đọc singleton setting trước khi tạo provider.
- OFF trả về idle ngay, không khởi tạo LLM/PubMed provider và chờ poll interval hiện có; không busy-loop.
- Câu lệnh claim kiểm tra `enabled=true` lần nữa trong SQL để đóng race với thao tác Admin OFF.
- Conditional job insert cũng kiểm tra `enabled=true` ngay trong SQL.

## 9. Job đang chạy

Khi job đã được claim thành `SEARCHING`/`GENERATING`, Admin OFF không cancel job. Job đó hoàn thành và persist revision/provenance bình thường. Worker không claim job tiếp theo.

## 10. Queue pause/resume

- Job `QUEUED` giữ nguyên khi OFF.
- Không chuyển thành FAILED/CANCELLED và không bị xóa.
- Khi Admin ON, polling worker tự resume và claim job, không restart.

## 11. Authorization

- Admin PATCH runtime setting: allowed.
- Staff PATCH: HTTP 403.
- Public/Parent PATCH không token: HTTP 401.
- Staff/Admin GET overview giữ conventions cũ.

Không có config-audit subsystem phù hợp sẵn trong project, nên event `AUTO_SERVICE_ENABLED/DISABLED` không được tạo riêng: `NOT_IMPLEMENTED` theo yêu cầu tránh overengineering.

## 12. API

Tái sử dụng endpoint hiện có, không tạo API trùng:

```http
GET /api/medical-knowledge/auto
PATCH /api/medical-knowledge/auto/settings
```

PATCH hỗ trợ độc lập:

```json
{
  "enabled": true
}
```

Response trả lại `enabled`, `display_mode`, `auto_visible_default` đã persist.

## 13. Migration và data integrity

Migration mới: `v009_auto_medical_knowledge_runtime_toggle.py`.

- Additive và idempotent.
- Cột `enabled` chỉ được thêm nếu chưa tồn tại.
- Existing installation mặc định OFF.
- Không rewrite Reviewed business rows.
- Không xóa/sửa Auto jobs, revisions, sources, evidence snapshots, discovery audit hoặc topic state.
- Chạy V009 hai lần trên bản sao DB: PASS.
- Production lifespan migration: PASS.
- Hash tất cả bảng Reviewed và Auto business trước/sau: không đổi.
- SQLite foreign key check: PASS.
- Production runtime sau migration: OFF.
- Production Auto job count sau startup: 0.

## 14. Files changed cho runtime toggle

Backend:

- `app/medical_knowledge_models.py`
- `app/auto_medical_knowledge_schemas.py`
- `app/repositories/auto_medical_knowledge_repository.py`
- `app/services/auto_medical_knowledge_service.py`
- `app/services/auto_medical_knowledge_worker.py`
- `app/services/published_medical_knowledge_read_service.py`
- `app/routers/auto_medical_knowledge.py`
- `app/routers/public.py`
- `app/main.py`
- `app/config.py`
- `.env.example`
- `migrations/v009_auto_medical_knowledge_runtime_toggle.py`
- `tests/test_auto_medical_knowledge.py`

Frontend:

- `src/lib/medicalKnowledgeApi.ts`
- `src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`

## 15. Focused tests

- Backend: `71 passed`, `0 failed`.
- Frontend: `120 passed`, `0 failed`.
- Python compileall: PASS.
- TypeScript typecheck: PASS.
- Frontend production build: PASS, chạy đúng một lần; 2,305 modules transformed.
- Backend startup/lifespan: PASS.
- HTTP root smoke: PASS.

Backend coverage bao gồm default OFF, OFF→ON→OFF, reload persistence, singleton, Admin/Staff/Public authorization, Parent enqueue gates, worker idle, pause/resume, in-flight completion, Reviewed/Tier 1, display/visibility separation và settings-read failure.

Frontend coverage bao gồm Admin switch, Staff read-only, ON/OFF state, helper text, backend mutation, confirmed-state update, failed mutation, loading/double-click prevention, refresh persistence, display dropdown và không hiển thị secret/config values.

## 16. Targeted E2E

- `AUTO_RUNTIME_ENABLE_E2E=PASS`
- `AUTO_RUNTIME_PAUSE_RESUME_E2E=PASS`
- `REVIEWED_WHILE_AUTO_DISABLED_E2E=PASS`

Các E2E dùng SQLite/provider doubles deterministic; không dùng external network.

## 17. External calls

- Groq/OpenAI/Ollama: `NOT_RUN`.
- PubMed: `NOT_RUN`.
- PMC: `NOT_RUN`.
- Trusted web: `NOT_RUN`.

Không secret nào được in hoặc sửa.

## 18. Remaining limitations

- Runtime transition được worker nhận ở poll tiếp theo, tối đa theo `AUTO_MEDICAL_KNOWLEDGE_POLL_SECONDS`; không có push/wakeup bus riêng.
- Worker vẫn là in-process consumer của durable SQLite queue, không phải distributed multi-host scheduler.
- Config audit event không được triển khai vì project chưa có admin/config audit mechanism phù hợp.

## 19. Manual test

`user_manual_test_required=false`

Khuyến nghị một browser smoke ngắn: Admin OFF→ON→refresh→OFF và quan sát queue trên staging. Đây không phải blocker của task.
