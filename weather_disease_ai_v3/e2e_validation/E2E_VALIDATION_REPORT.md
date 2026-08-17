# Weather AI V3 — End-to-End Validation Report

## 1. Environment

**Kết quả: PASS**

| Thành phần | Giá trị |
|---|---|
| Conda environment | `seasonal_backend` |
| Conda prefix | `D:\Users\LENOVO\anaconda3\envs\seasonal_backend` |
| Python executable | `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` |
| Python version | 3.11.15, Anaconda 64-bit |
| Backend working directory thực tế | Bản sao tạm của `seasonal_disease_backend` |
| Frontend working directory | `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\Frontend` |
| Node | v24.15.0 |
| npm | 11.12.1 |

`conda` không có trong PATH của PowerShell tự động, nên executable chính xác `D:\Users\LENOVO\anaconda3\Scripts\conda.exe` được dùng để xác minh environment. Backend được chạy trực tiếp bằng Python executable thuộc environment này; không dùng Python global và không tạo environment mới.

Environment ban đầu thiếu hai package đã khóa trong `seasonal_disease_backend/requirements.txt`. Chỉ `lightgbm==4.7.0` và `pytest==8.4.2` được cài vào `seasonal_backend`; không chạy broad install và không upgrade package khác.

## 2. Backend/frontend startup

- Backend thật: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, không dùng reload.
- Frontend thật: `npm run dev -- --host 127.0.0.1 --port 5173`.
- Backend chỉ được coi là ready sau khi `/api/public/weather-options` trả HTTP 200 và model preload hoàn tất.
- Frontend chỉ được coi là ready sau khi `/parents` trả HTTP 200.
- Internal status xác nhận `ready=true`, `model_count=221`, `feature_count=45`, medical knowledge ready.
- PID do validation tạo đã được theo dõi và dừng riêng; port 8000/5173 đều clear sau cleanup.

## 3. Database isolation

`app/database.py` hard-code SQLite theo backend root và không có path override. Validation không sửa source chỉ để thêm test configuration. Thay vào đó:

1. Tạo một backend workspace tạm ngoài repository.
2. Copy `app/`, `tests/`, `requirements.txt` và `database.db` vào workspace đó.
3. Trỏ `WEATHER_AI_V3_ROOT` về V3 thật ở chế độ read-only.
4. Chạy Uvicorn từ backend copy, nên `seed_default_areas()` chỉ ghi vào SQLite tạm.
5. Dừng đúng PID và xóa workspace tạm sau validation.

Checksum database development trước/sau đều là:

`5998c4ea105b67fb0f098a69f07a45675aa399ff54f35f471a9245465abc2dae`

Database development không bị thay đổi.

## 4. Real Open-Meteo request

Ba context hợp lý được gửi qua đúng Vite proxy và public parent API với tọa độ TP.HCM:

- `1-5 tuổi`, Nam;
- `1-5 tuổi`, Nữ;
- `6-10 tuổi`, Nam.

Mỗi response xác nhận:

- `weather.meta.source = open_meteo`;
- timezone `Asia/Bangkok`;
- đủ 7 ngày liên tiếp từ 2026-08-08 đến 2026-08-14;
- current, rolling 3-day và rolling 7-day features đều có;
- frontend không fabricate weather history.

## 5. 45-feature validation

- Locked manifest/schema: 45 features.
- Response trả 43 calendar/weather features trong `weather.features`.
- Cộng `age_group` và `gender`: đúng 45 input features.
- Backend regression so sánh runtime transformation với locked training context và weather aggregation với data pipeline V3: PASS.
- Feature order/schema validation trong registry: PASS.

## 6. 221-model ranking validation

- `model_count = 221`.
- `ranking_universe = 221`.
- 221 booster checksums/size được registry kiểm tra khi preload.
- Regression so sánh integrated scores với 221 standalone locked boosters: PASS với tolerance `1e-12`.
- Tier 2 được chạy sau ranking và không thay đổi thứ tự score.

## 7. Top-5 validation

Ở cả ba request thật:

- prediction count = 5;
- rank = `[1, 2, 3, 4, 5]`;
- 5 disease ID duy nhất;
- score giảm dần;
- không NaN/Infinity;
- disease name không rỗng;
- không có key legacy `probability`, `predicted_cases`, `risk_score`, `risk_level`.

## 8. Tier 1 validation

- Tier 1 available: 5/5 cho cả ba context thật.
- Mọi positive factor có `shap_value > 0` và direction `UP`.
- Mọi negative factor có `shap_value < 0` và direction `DOWN`.
- `label_vi` tồn tại; frontend ưu tiên label này và không hiển thị raw SHAP mặc định.
- Additivity max absolute error lớn nhất quan sát: `6.661338147750939e-15`, PASS theo rule hiện tại.

## 9. Tier 2 real branch

Hai context đầu không có Tier 2, đây là trạng thái hợp lệ. Context tự nhiên `6-10 tuổi`, Nam xuất hiện một branch Tier 2:

- rank: 5;
- disease ID: `274`;
- evidence: `LIMITED_OR_INDIRECT`;
- matched factor: `wind`;
- explanation: present;
- limitations: present;
- một nguồn PubMed/Injury năm 2015, URL HTTPS.

Không brute-force và không dùng input phi thực tế.

## 10. Tier 2 fixture validation

Backend fixture tests xác nhận:

- `SUPPORTED` và `LIMITED_OR_INDIRECT` + positive matching weather factor + display allowed → available;
- `INSUFFICIENT` → unavailable;
- `CONFLICTING` → unavailable;
- disease ngoài KB → unavailable;
- weather SHAP âm → không kích hoạt Tier 2;
- factor mismatch → unavailable;
- display flag false → unavailable;
- KB missing/corrupt fixture → ranking và Tier 1 vẫn hoạt động, Tier 2 trả `MEDICAL_KB_ERROR`.

Frontend fixture xác nhận explanation, evidence wording thận trọng, limitations và source HTTPS được render; internal reason không hiển thị.

## 11. Public parent flow

Endpoint chain thực tế:

`/parents` → `POST /api/public/parent-risk` qua Vite proxy → FastAPI → Open-Meteo → feature builder → 221 LightGBM boosters → Top-5 → local contributions → medical gate → response → component dùng chung.

Page load, options, submit API, Top-5 contract, Tier 1 và disclaimer: PASS. Loading, result cards và no-probability semantics được kiểm tra bằng frontend tests. Auxiliary public area/knowledge endpoints không ảnh hưởng ranking contract.

## 12. Internal Weather AI flow

Đăng nhập vào database tạm bằng tài khoản development documented, sau đó gọi qua Vite proxy:

`/api/auth/login` → `/api/weather-ai/status` → `/api/weather-ai/options` → `/api/weather-ai/predict-risk`.

Kết quả: login PASS, status ready, 221 models, Top-5 rank đúng, Tier 1 5/5 và disclaimer present. `WeatherRisk` và `ParentPortal` cùng dùng `WeatherAIExplanationSections`/`WeatherAIPredictionList` đã được build và typecheck.

## 13. Error flow

API-level controlled fixtures:

| Case | Status | Kết quả |
|---|---:|---|
| Invalid input (`top_k=0`) | 422 | Không stack trace |
| Model registry unavailable | 503 | Controlled detail, không stack trace |
| Weather/server runtime error | 500 | `Weather AI runtime error.`, không lộ path/stack |
| Medical KB error | 200 ranking | Tier 1 giữ nguyên, Tier 2 unavailable |

Frontend tests xác nhận wording thân thiện cho 422/503/500 và network failure không làm component crash.

## 14. Cache validation

Cache module được load qua Vite và kiểm tra trực tiếp:

- V3 cache hydrate đúng, rank vẫn là số hữu hạn;
- key V2 cũ không được hydrate;
- V3 payload mang contract stale bị reject;
- clear xóa cả key V3 và legacy key;
- không sinh NaN/undefined từ contract cũ.

## 15. Visual QA

- `VISUAL_BROWSER_QA = NOT_AVAILABLE`.
- In-app browser không có session khả dụng; không dùng standalone Playwright và không giả vờ visual PASS.
- Không tạo screenshot.
- `STATIC_RESPONSIVE_REVIEW = PASS`: card/list mobile-first, breakpoint `sm/md/lg`, không dùng bảng rộng cho Tier 1/Tier 2, text/link wrap, UP/DOWN có icon + text và disclaimer nằm sau kết quả.

## 16. Performance

Số đo thực tế của ba request qua Vite proxy; không đặt SLA:

| Metric | Trung bình | Min–Max |
|---|---:|---:|
| Frontend proxy request total | 1,072.961 ms | 1,005.959–1,177.408 ms |
| Backend total | 1,046.332 ms | 981.180–1,154.739 ms |
| Weather + feature preparation | 875.825 ms | 814.961–982.406 ms |
| Ranking 221 models | 161.708 ms | 157.847–164.212 ms |
| Tier 1 Top-5 | 8.697 ms | 8.314–9.091 ms |
| Tier 2 Top-5 | 0.050 ms | 0.010–0.125 ms |

Internal authenticated request total qua proxy: 1,067.554 ms. Render-completion timing không đo được vì browser automation không khả dụng.

## 17. Regression tests

- Backend, đúng Conda `seasonal_backend`: **16 passed, 0 failed**.
- Frontend Vitest: **17 passed, 0 failed**.
- TypeScript typecheck: PASS.
- Vite production build: PASS, 2,292 modules transformed.

## 18. Bug found/fixed

### BUG FOUND

`GET /api/weather-ai/status` trả `manifest_path`, làm lộ đường dẫn filesystem local cho authenticated client.

### ROOT CAUSE

`LightGBMModelRegistry.status()` serialize trực tiếp `str(self.manifest_path)`.

### FIX

Thay `manifest_path` bằng boolean `manifest_verified: true`. Không thay startup, model loading, prediction, feature pipeline hoặc API prediction contract.

### REGRESSION TEST

- Assert `manifest_verified is True`.
- Assert `manifest_path` không còn trong status.
- API fixture status 200 xác nhận không có `C:\`/`D:\` trong response.
- Backend 16/16 và toàn bộ frontend regression PASS sau fix.

Số bug ứng dụng phát hiện: 1. Số bug đã sửa: 1.

## 19. Integrity

Các hash trước/sau giống hệt:

| Artifact | SHA-256 tree/file |
|---|---|
| Final deployment | `cd60c0fb1df7da3f966454543d5b60c7f1dee2ca12447b4f2467e2a96261accb` |
| Model manifest | `1b6e0b4a3c2fb7313000c730738244e6126e24c0fb3c278d08059e72d0d95416` |
| FINAL TEST | `c03d354d6fe3d5fe98eed526e48a538b61f332848629eb585a3249d9022fd6bf` |
| SHAP/explainability | `f245bf6ef8670a428cebef26aac7d0eb4c2af569e01eb93b9858b782459e1c23` |
| PRE-TIER-2 | `e9f08fe103166a0c6751227f8b455a33116ab5b0583778fd6b033b4d2e5a96f9` |
| Medical explainability | `ae8367adf537ca684ce2ac629ae0a054e3a4fd03afcb42e064b8503902d5fd4b` |
| Medical KB file | `4fc3cda83981bf7ecf0dc3bb113da3bcb786e4157cfae11202527bebba40a92c` |
| V2 workspace | `60418e399ea32e26ea1a4427fff7f0cbe60bd8c7ff761e52a1246953bfdfc5ef` |

Không train, tuning, model selection hoặc dùng TEST target. Chỉ hai application/test source liên quan status security được sửa tối thiểu.

## 20. Known limitations

- Không có browser session nên chưa có visual click-test desktop/mobile hoặc screenshot.
- Weather realtime phụ thuộc Open-Meteo và giá trị sẽ thay đổi theo thời gian.
- Performance chỉ là số đo quan sát trên ba request, không phải SLA.
- Public parent route hiện chuẩn hóa một số runtime exception thành HTTP 400; frontend hiển thị message chung an toàn. Authenticated route giữ 422/503/500 chi tiết như đã kiểm tra.

