# Weather AI V3 — Release Readiness Cleanup

Ngày kiểm tra: 2026-08-14

Trạng thái: **PASS**

Phạm vi của bước này chỉ gồm hai consistency issue đã phát hiện sau E2E: quy ước timezone TP.HCM và HTTP status của public parent API. Không train, tuning, chọn model, đọc TEST target hoặc thay đổi artifact khoa học.

## 1. Environment

- Backend được kiểm thử bằng đúng Python của Conda environment `seasonal_backend`: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`.
- Python: 3.11.15, 64-bit.
- Không dùng Python global và không cài thêm dependency trong bước cleanup này.

## 2. Timezone audit

### Trạng thái trước cleanup

- Cả `WeatherRisk` và `ParentPortal` lấy timezone từ `Intl.DateTimeFormat().resolvedOptions().timeZone`, fallback `Asia/Bangkok`.
- Public request schema và internal request schema đều kế thừa backend default `Asia/Bangkok`.
- Public và internal API truyền nguyên timezone request cho feature builder.
- Open-Meteo được gọi với timezone **explicit**, không dùng `timezone=auto`.
- Hourly timestamp từ Open-Meteo được parse và group theo calendar date trả về trong timezone đã yêu cầu. Ngày cuối hợp lệ trở thành `anchor_date` khi không có `target_date` explicit.
- `month`, `season`, `day_of_year_sin` và `day_of_year_cos` đều được tính từ `anchor_date` này.
- E2E trước cleanup vì vậy ghi nhận `Asia/Bangkok` dù ứng dụng phục vụ TP.HCM và config V3 khóa `Asia/Ho_Chi_Minh`.

### Kiểm tra provider

Audit thật với cùng tọa độ TP.HCM cho thấy:

- Request explicit `Asia/Ho_Chi_Minh` → Open-Meteo trả `Asia/Ho_Chi_Minh`, UTC offset +07:00.
- Request explicit `Asia/Bangkok` → Open-Meteo trả `Asia/Bangkok`, UTC offset +07:00.
- Request `auto` tại tọa độ này → Open-Meteo trả `Asia/Ho_Chi_Minh`, UTC offset +07:00.

Không cần tạo thêm `provider_timezone`: provider trả đúng label explicit mới. Trường `weather.meta.timezone` tiếp tục giữ contract hiện tại và phản ánh application timezone đã gửi.

### Root cause

Application convention chưa được khóa thống nhất: backend default là Bangkok và frontend phụ thuộc timezone label mà browser/OS trả về. Hai timezone hiện cùng UTC+7 nên numerical features không sai trong fixture E2E, nhưng label và convention không phù hợp với TP.HCM.

### Fix

- Backend `DEFAULT_TIMEZONE` đổi thành `Asia/Ho_Chi_Minh`.
- Hai frontend flow gửi explicit `Asia/Ho_Chi_Minh`.
- Public và internal schemas tự kế thừa default mới.
- API vẫn nhận timezone explicit từ external client để không phá compatibility; official application flows và default đều dùng convention TP.HCM.
- Không sửa công thức weather aggregation hoặc calendar features.

## 3. Timezone and ranking regression

| Check | Result |
|---|---|
| Application timezone is `Asia/Ho_Chi_Minh` | PASS |
| Public/internal schema default | PASS |
| Open-Meteo query contains explicit application timezone | PASS |
| Local `anchor_date` and calendar date | PASS |
| Locked feature vector has 45 features | PASS |
| HCM vs Bangkok fixture feature values identical | PASS |
| All 221 ranking scores unchanged within `atol=1e-12` | PASS |
| Top-5 order unchanged | PASS |
| Locked V3 weather aggregation regression | PASS |

Kết quả trên dùng TRAIN fixture đã khóa. Không đọc TEST target. Do hai timezone cùng UTC+7, thay đổi convention không làm đổi feature numeric trong fixture; khác biệt chỉ có thể xuất hiện nếu timezone có UTC offset khác hoặc ở local-date boundary thực sự.

## 4. Public API HTTP status audit

Endpoint: `POST /api/public/parent-risk`

### Root cause

Public wrapper trước cleanup có `except Exception` và luôn chuyển exception còn lại thành HTTP 400. Vì vậy `ValueError`, `ModelRuntimeError` và unexpected runtime error mất status có ý nghĩa. Internal Weather AI route đã có mapping 422/503/500 đúng hơn.

### Fix

- Missing realtime coordinates và invalid runtime input → **422**.
- `ModelRuntimeError` → **503**, với message public tổng quát, không lộ filesystem path.
- Unexpected runtime/backend error → **500**, log server-side và trả `Weather AI runtime error.`.
- Prediction thành công → **200**.
- Medical KB unavailable nhưng ranking/Tier 1 vẫn chạy → **200**, Tier 2 trả trạng thái unavailable như trước.
- Không thay successful response contract: `predictions`, `top_risks`, Tier 1, Tier 2 và `disclaimer` giữ nguyên.

| Public behavior | Expected | Result |
|---|---:|---|
| Invalid input/missing coordinates | 422 | PASS |
| Model/runtime service unavailable | 503 | PASS |
| Unexpected runtime error | 500 | PASS |
| Successful prediction | 200 | PASS |
| Missing medical KB graceful fallback | 200 | PASS |
| Error response does not expose injected local path | — | PASS |

## 5. Regression tests

| Gate | Result |
|---|---|
| Backend full `pytest` in `seasonal_backend` | **24 passed, 0 failed** |
| Frontend Vitest | **17 passed, 0 failed** |
| TypeScript typecheck | **PASS** |
| Vite production build | **PASS**, 2,292 modules transformed |

Các regression tối thiểu A–H đều đạt:

- A. TP.HCM application timezone convention: PASS.
- B. Locked feature pipeline không sai sau timezone cleanup: PASS.
- C. Public invalid input → 422: PASS.
- D. Public model unavailable → 503: PASS.
- E. Public unexpected runtime error → 500: PASS.
- F. Medical KB unavailable vẫn giữ ranking/Tier 1, Tier 2 unavailable: PASS.
- G. Successful prediction contract không đổi: PASS.
- H. Ranking regression: PASS.

## 6. Files modified in this cleanup

Application source:

- `seasonal_disease_backend/app/services/weather_ai_features.py`
- `seasonal_disease_backend/app/routers/public.py`
- `Frontend/src/app/components/WeatherRisk.tsx`
- `Frontend/src/app/components/ParentPortal.tsx`

Regression tests:

- `seasonal_disease_backend/tests/test_weather_ai_runtime.py`
- `seasonal_disease_backend/tests/test_weather_ai_release_readiness.py`

Validation outputs:

- `weather_disease_ai_v3/release_readiness/RELEASE_READINESS_REPORT.md`
- `weather_disease_ai_v3/release_readiness/release_readiness_validation.json`

Repository đã có các thay đổi Weather AI V3 chưa commit từ các giai đoạn tích hợp trước. Cleanup này không đảo ngược hoặc ghi đè các thay đổi đó.

## 7. Integrity

Các SHA-256 file/tree digest trước và sau cleanup giống hệt:

| Artifact | Digest trước/sau |
|---|---|
| Deployment 221 models | `17947271573c995e6bbfc9c187027ea86ef24ba51a7876f4cb1b430b4f862274` |
| Model manifest | `1b6e0b4a3c2fb7313000c730738244e6126e24c0fb3c278d08059e72d0d95416` |
| FINAL TEST artifacts | `316bcf4bb5c2581bd60cd43fd274bbf43b620a88b2d08766c58d403c798df32f` |
| SHAP/explainability tree | `49e0efa5e5adb6bd81432f95c47b945631358cc537a2d036e8b02cc0053a449b` |
| PRE-TIER-2 artifacts | `1b0bc5949530c780469d876c9791c18f6c3d61cb0f370e04beb2f8a4fd523636` |
| Medical explainability tree | `08b7c1ad342f4d17a62ed40e20640071506078b2675f4bacea3950d41008222b` |
| Medical knowledge base | `4fc3cda83981bf7ecf0dc3bb113da3bcb786e4157cfae11202527bebba40a92c` |

- Model file count: **221**, không đổi.
- Development database SHA-256: `5998c4ea105b67fb0f098a69f07a45675aa399ff54f35f471a9245465abc2dae`, không đổi so với E2E baseline.
- `git diff --check`: PASS.

**NO TRAINING.**  
**NO TUNING.**  
**NO MODEL SELECTION.**  
**NO TEST TARGET USED.**  
**NO MODEL MODIFICATION.**  
**NO SHAP MODIFICATION.**  
**NO MEDICAL KNOWLEDGE MODIFICATION.**

## 8. Remaining limitations

- `VISUAL_BROWSER_QA = NOT_AVAILABLE`; theo phạm vi task không cài browser automation framework mới.
- Realtime weather vẫn phụ thuộc availability và response của Open-Meteo.
- External API client vẫn có thể gửi timezone explicit khác để giữ backward compatibility; default và hai official frontend flows đã khóa `Asia/Ho_Chi_Minh`.
- Không chạy lại scientific FINAL TEST vì cleanup không thay model, feature definition hoặc artifact khoa học.

## 9. Release-readiness decision

**RELEASE READINESS CLEANUP: PASS**

Hai technical consistency issue đã được xử lý với thay đổi nhỏ, regression đầy đủ đạt và các artifact khoa học giữ nguyên.
