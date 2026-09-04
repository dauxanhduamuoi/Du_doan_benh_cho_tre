# Auto Medical Knowledge Numeric Claim Contract V2

## 1. Status

**PASS**

Numeric Claim Contract V2 đã được triển khai cho các Auto generation attempt mới. Reviewed schema/workflow, Parent response contract và dữ liệu lịch sử không bị thay đổi. Không có Groq, PubMed hoặc PMC live call.

## 2. Kiến trúc numeric trước đây

Auto validator trước đây quét numeric token trong generated prose rồi tìm một biểu diễn tương đương trong toàn bộ selected evidence hoặc canonical context. Cơ chế này fail-closed nhưng token không mang ngữ nghĩa: cùng một biểu diễn có thể là count, decimal, tuổi, phần trăm, khoảng thời gian, measurement hoặc metadata. Vì vậy grouped count `5.087 ↔ 5087`, year range `2004–2009` và các giá trị phổ biến như `3` liên tục cần thêm quy tắc regex theo edge case.

Token scanning vẫn được giữ để phát hiện numeric occurrence chưa khai báo và để tái sử dụng normalizer an toàn, nhưng không còn là evidence contract chính của Auto V2.

## 3. Numeric Claim Contract V2

Exact Auto output schema gồm các field hiện có và một field bắt buộc mới:

```json
{
  "evidence_level": "SUPPORTED | LIMITED_OR_INDIRECT | CONFLICTING | INSUFFICIENT",
  "evidence_scope": "WHOLE_GROUP | PARTIAL_GROUP",
  "short_explanation_vi": "string | null",
  "detailed_explanation_vi": "string | null",
  "limitations_vi": "string | null",
  "source_assessments": ["existing Auto source assessment objects"],
  "numeric_claims": [
    {
      "value_text": "string, 1..100 chars",
      "claim_kind": "bounded enum",
      "unit": "string | null, max 100 chars",
      "source_id": "positive selected source ID",
      "supporting_text": "exact short excerpt, 1..1000 chars"
    }
  ]
}
```

`numeric_claims` có tối đa 10 phần tử. `INSUFFICIENT` và `CONFLICTING` chỉ hợp lệ với `numeric_claims=[]`.

Claim kinds:

- `COUNT`
- `PERCENTAGE`
- `RATE`
- `RATIO_OR_EFFECT`
- `MEASUREMENT`
- `AGE`
- `DURATION`
- `TEMPORAL_PERIOD`
- `OTHER_NUMERIC`

`OTHER_NUMERIC` không được tự động chấp nhận khi không thể phân loại deterministic; validator fail-closed với kind-invalid.

## 4. Prompt V2

Prompt/pipeline version mới:

- `medical_knowledge_auto_v2_numeric_claims`
- `auto_medical_knowledge_v2_numeric_claims`

Prompt ưu tiên giải thích định tính, cấm thêm số chỉ để tạo vẻ khoa học, yêu cầu mỗi số y khoa Parent-facing có đúng một declaration, exact selected source và exact supporting excerpt. Khi không có support, model phải bỏ numeric detail hoặc dùng structured insufficient path. Worker không cho cấu hình version V1 cũ gắn nhãn sai lên attempt V2.

## 5. Deterministic validation

Validator chỉ quét ba Parent-facing prose fields:

- `short_explanation_vi`
- `detailed_explanation_vi`
- `limitations_vi`

Canonical topic value được so khớp trước. Vì vậy việc nhắc lại age bucket như `1-5 tuổi` không cần numeric claim. PMID, publication year, selected source ID, DOI và disease group ID vẫn dùng metadata exemption an toàn hiện có.

Mỗi numeric occurrence còn lại phải khớp đúng một declaration. Không có declaration trả về `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`; declaration không được dùng trả về `AUTO_OUTPUT_NUMERIC_CLAIM_UNUSED`; duplicate hoặc nhiều declaration cùng khớp một occurrence bị reject.

`source_id` phải có trong exact selected source set của attempt. Source tồn tại global nhưng không được chọn vẫn trả về `AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID`.

`supporting_text` được kiểm tra là substring của immutable evidence snapshot sau đúng các normalization vô hại:

- Unicode NFKC;
- whitespace/line-break collapse;
- typographic dash normalization.

Không lowercase, không fuzzy match và không chấp nhận paraphrase. Quote không tìm thấy trả về `AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH`.

Claim kind được kiểm tra deterministic với representation, unit, generated context và evidence excerpt. AGE không thể support PERCENTAGE; measurement/rate/count/year không cross-match. Backend không sửa, thay số hoặc xóa câu prose.

## 6. Numeric normalization được tái sử dụng

Normalizer hiện có tiếp tục cung cấp fail-closed equivalence theo kind:

- `COUNT`: grouped integer `5.087`, `5 087` và `5087` chỉ tương đương trong count context ở cả prose và evidence.
- `TEMPORAL_PERIOD`: `2004–2009` tương đương exact study period như `between January 2004 and December 2009`; unrelated years không support range.
- decimal comma/dot, signed values và bounded ranges tiếp tục dùng canonical keys hiện có.
- phần trăm, tuổi, duration, measurement, rate và ratio cần context/unit tương thích.

Regression `3` được giải quyết bằng declaration COUNT + exact group-count excerpt, không có special-case cho giá trị `3`.

## 7. Persistence và migration

Migration additive, idempotent `v011_auto_numeric_claim_contract.py` tạo `auto_medical_knowledge_numeric_claims`.

Mỗi verified row lưu:

- revision ID và bounded claim order;
- kind, value text và optional unit;
- selected source ID;
- immutable evidence content ID;
- verified support start/end offsets;
- SHA-256 của exact source excerpt tại offsets.

`supporting_text` do model trả về không được persist. Không lưu raw model response, full prompt hay full evidence body trong diagnostics. Không backfill/rewrite historical revisions, không đổi current pointer hoặc visibility.

V1 revision không có claim row vẫn đọc được, vẫn Parent-eligible theo logic cũ và giữ nguyên current pointer. Retry/regenerate mới sử dụng V2; attempt history cũ không bị mutate.

## 8. Parent và Admin

Parent API không được mở rộng và không nhận numeric claim object, excerpt, offsets, hash hay validator diagnostics.

Admin Auto panel chỉ bổ sung safe localized messages cho:

- `AUTO_OUTPUT_NUMERIC_CLAIM_UNDECLARED`
- `AUTO_OUTPUT_NUMERIC_CLAIM_SOURCE_INVALID`
- `AUTO_OUTPUT_NUMERIC_CLAIM_EVIDENCE_MISMATCH`
- `AUTO_OUTPUT_NUMERIC_CLAIM_KIND_INVALID`
- duplicate/unused declarations.

Raw LLM output không được hiển thị.

## 9. Files changed

- `seasonal_disease_backend/app/auto_medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/repositories/auto_medical_knowledge_repository.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_prompt.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_service.py`
- `seasonal_disease_backend/app/services/auto_medical_knowledge_worker.py`
- `seasonal_disease_backend/app/services/auto_medical_numeric_validation.py`
- `seasonal_disease_backend/migrations/v011_auto_numeric_claim_contract.py`
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- `seasonal_disease_backend/tests/test_groq_medical_knowledge_provider.py`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.tsx`
- `Frontend/src/app/components/medical-knowledge/AutoMedicalKnowledgePanel.test.tsx`
- Hai validation artifacts trong thư mục này.

## 10. Focused validation

- Focused backend Auto/schema/Groq + small Reviewed regression: **141 passed, 0 failed**.
- Focused Auto panel diagnostics: **30 passed, 0 failed**.
- Frontend TypeScript typecheck: **PASS**.
- Python compile/import: **PASS**.
- Temp SQLite migration/startup/lifespan: **PASS**.
- HTTP root smoke trên temp runtime: **PASS**.
- SQLite foreign key check: **PASS**.
- Production `database.db` hash trước/sau startup smoke: **unchanged**.

Deterministic E2E results:

- `AUTO_NUMERIC_CONTRACT_QUALITATIVE_E2E=PASS`
- `AUTO_NUMERIC_CONTRACT_SUPPORTED_E2E=PASS`
- `AUTO_NUMERIC_CONTRACT_UNDECLARED_E2E=PASS`
- `AUTO_NUMERIC_CONTRACT_HALLUCINATION_E2E=PASS`
- `AUTO_NUMERIC_CONTRACT_YEAR_RANGE_E2E=PASS`
- `AUTO_NUMERIC_CONTRACT_LEGACY_E2E=PASS`

Causal, unsupported-mechanism, pediatric, personalized/certainty, exact source-set provenance và trusted-source guards đều tiếp tục PASS. Ba focused Reviewed tests xác nhận generation, approval/audit và pediatric gating không đổi.

## 11. Integrity, external calls và limitations

- Reviewed business data modified: **NO**.
- Auto visibility/current pointers/historical revisions modified: **NO**.
- Production job `169 · wind` retried: **NO**.
- Groq/PubMed/PMC live calls: **0/0/0**.
- Không có second-LLM validation hoặc semantic resampling.

Remaining limitations: exact quote policy cố ý reject paraphrase/case changes ngoài whitelist normalization; `OTHER_NUMERIC` cố ý fail-closed. Đây là safety boundaries, không phải release blocker. Manual test không bắt buộc.

