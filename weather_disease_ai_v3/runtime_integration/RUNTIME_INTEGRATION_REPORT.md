# Runtime Backend Integration Report

## 1. Kết quả

**RUNTIME BACKEND INTEGRATION: PASS**

Backend hiện tại đã tích hợp model **LightGBM One-vs-Rest H14 WITH WEATHER**, local SHAP Tầng 1 và medical knowledge Tầng 2. Ranking luôn được tạo từ toàn bộ **221 disease-specific models**. Tầng 2 chỉ bổ sung explanation và không thay đổi score hoặc thứ hạng.

## 2. Kiến trúc trước integration

- Framework: FastAPI.
- Entry point: `seasonal_disease_backend/app/main.py`.
- Endpoint hiện có: `POST /api/weather-ai/predict-risk`.
- Request schema được khai báo trực tiếp trong router.
- Weather fetching, feature preparation, model loading, inference và response formatting cùng nằm trong `weather_ai_service.py` khoảng 440 dòng.
- Runtime cũ dùng artifact Joblib classifier/regressor và feature set cũ; chưa sử dụng deployment LightGBM H14 V3.
- Disease mapping nằm trong artifact cũ.
- Config chỉ chứa JWT settings.
- Backend chưa có test structure cho Weather AI.

## 3. File thêm và sửa

### Đã sửa

- `seasonal_disease_backend/app/main.py`: preload runtime theo FastAPI lifespan.
- `seasonal_disease_backend/app/config.py`: tập trung path/config V3 và environment override.
- `seasonal_disease_backend/app/routers/weather_ai.py`: controller mỏng, response model và error mapping.
- `seasonal_disease_backend/app/services/weather_ai_service.py`: application orchestration V3.
- `seasonal_disease_backend/requirements.txt`: thêm LightGBM/pytest và cập nhật các pin cần thiết cho Python 3.14.

### Đã thêm

- `app/services/weather_ai_features.py`: exact locked V3 feature preparation và Open-Meteo/manual input.
- `app/services/weather_ai_runtime.py`: registry, integrity validation, 221-model inference.
- `app/services/weather_ai_explanations.py`: local SHAP Tầng 1 và medical gating Tầng 2.
- `app/weather_ai_schemas.py`: request/response contracts.
- `tests/conftest.py`, `tests/test_weather_ai_runtime.py`, `tests/test_weather_ai_api.py`.

Không sửa frontend và không tạo backend thứ hai.

## 4. Kiến trúc sau integration

```text
FastAPI route
  -> WeatherAIRuntimeService
       -> WeatherFeatureBuilder
       -> LightGBMModelRegistry (221 models)
       -> Tier1ExplanationService (Top-K only)
       -> MedicalKnowledgeService (gate only)
  -> structured response
```

- Router chỉ validate/translate HTTP errors.
- Service điều phối pipeline, không chứa implementation LightGBM hoặc knowledge matching.
- Model inference tách khỏi SHAP.
- Tầng 1 tách khỏi medical knowledge Tầng 2.
- Không có circular dependency hoặc `sys.path` hack.
- Module lớn nhất có 354 dòng và chỉ giữ một responsibility lớn; không có file monolith 1000+ dòng.

## 5. Runtime flow

1. Validate `age_group`, `gender`, `top_k`, tọa độ hoặc manual weather.
2. Tạo đúng 45 features theo manifest: demographic/calendar + current + 3d + 7d.
3. Encode categorical bằng `category_mappings.json`, giữ nguyên feature order.
4. Chạy đủ 221 booster và stable-sort `ranking_score`.
5. Chọn Top-K từ toàn bộ 221 disease.
6. Tính local SHAP chỉ cho Top-K.
7. Tạo structured Tầng 1 với `UP`/`DOWN` từ dấu local SHAP.
8. Chỉ đưa weather factor dương sang Tier 2 gate.
9. Tier 2 kiểm tra record, evidence status, runtime flag và normalized factor match.
10. Trả ranking, Tầng 1, Tầng 2 và disclaimer riêng biệt.

## 6. Feature lifecycle

- Feature order lấy trực tiếp từ locked manifest và được kiểm tra bằng feature schema.
- Daily weather aggregation và rolling windows sử dụng đúng định nghĩa V3: exact trailing 3/7 ngày với đủ window.
- `day_of_year_sin/cos` dùng công thức khóa với 365.25.
- Season dùng quy ước TP.HCM đã khóa: tháng 12–4 là mùa khô; tháng 5–11 là mùa mưa.
- Realtime dùng 7 ngày hourly Open-Meteo rồi aggregate theo cùng công thức.
- Manual mode không còn tự nhân một ngày thành rolling history. Nó yêu cầu đủ 39 locked weather features hoặc `weather.daily` có ít nhất 7 ngày. Đây là thay đổi an toàn có chủ đích để tránh feature sai định nghĩa.

## 7. Model loading lifecycle

- Registry là process-local singleton qua `lru_cache`.
- FastAPI lifespan preload một lần; lazy access vẫn được bảo vệ bằng `RLock`.
- Mỗi worker production có một immutable registry riêng, phù hợp process model của ASGI.
- Startup kiểm tra manifest count, disease order, feature order, file size, SHA-256 và khả năng load của cả 221 model.
- Thiếu/corrupt bất kỳ model nào làm model runtime fail rõ ràng; không silently skip.
- Inference được bảo vệ bởi prediction lock để không dùng mutable LightGBM state đồng thời ngoài kiểm soát.

## 8. SHAP lifecycle — Tầng 1

- Dùng native LightGBM `pred_contrib=True`, tức local TreeSHAP cho context hiện tại.
- Không import hoặc tạo lại `shap.TreeExplainer` mỗi request.
- Chỉ tính cho Top-K, mặc định Top 5.
- Kiểm tra additivity giữa base value + feature contributions và raw model score với tolerance `1e-6`.
- `SHAP > 0` được trả là `UP`; `SHAP < 0` là `DOWN`.
- Không dùng disease-level `mean(abs(SHAP))` để suy ra chiều.

## 9. Medical knowledge lifecycle — Tầng 2

- `medical_knowledge_base.json` được đọc và index theo `disease_id` một lần mỗi process.
- Central factor normalization ánh xạ temperature, humidity, precipitation/rain, wind và weather_code.
- Tầng 2 chỉ available khi đồng thời thỏa:
  - có record;
  - local weather SHAP dương;
  - status là `SUPPORTED` hoặc `LIMITED_OR_INDIRECT`;
  - `runtime_tier2_display_allowed=true`;
  - factor khớp record;
  - record có source.
- `INSUFFICIENT`, `CONFLICTING`, disease ngoài KB hoặc factor không khớp đều giữ ranking/Tầng 1 và trả reason rõ.
- KB missing/corrupt được log và degrade thành `MEDICAL_KB_ERROR`; prediction không bị phá.

## 10. API contract

Endpoint giữ nguyên:

```text
POST /api/weather-ai/predict-risk
```

Mỗi prediction có:

```json
{
  "rank": 1,
  "disease_id": "...",
  "disease_name": "...",
  "ranking_score": 0.0,
  "tier1": {
    "available": true,
    "summary_vi": "...",
    "positive_factors": [],
    "negative_factors": []
  },
  "tier2": {
    "available": false,
    "reason": "NO_MEDICAL_KNOWLEDGE",
    "sources": []
  }
}
```

`ranking_score` chỉ dùng xếp hạng tương đối, không phải xác suất mắc bệnh. Response luôn có disclaimer: “Thông tin này nhằm hỗ trợ theo dõi và phòng ngừa, không thay thế chẩn đoán của bác sĩ.”

## 11. Error handling

- Pydantic/invalid feature input: HTTP 422.
- Model missing/corrupt/inference failure: HTTP 503.
- Lỗi explanation của một disease: disease vẫn được trả với `tier1.available=false`; lỗi được log theo disease ID.
- Medical KB error: ranking và Tầng 1 vẫn hoạt động; Tier 2 unavailable.
- Unknown runtime error: HTTP 500 và server log không ghi age/gender/weather payload.

## 12. Backward compatibility

- Giữ nguyên route `/api/weather-ai/status`, `/options`, `/predict-risk`.
- Giữ request realtime `age_group`, `gender`, `top_k`, `latitude`, `longitude`, `timezone`, `target_date`.
- Giữ `top_risks` làm alias của `predictions`.
- Giữ `input`, `disease_group_id` và `disease_group_name` làm alias cho client cũ.
- Các field cũ `probability`, `predicted_cases`, `risk_score`, `risk_level` không được giữ vì chúng thuộc model cũ và tạo semantics không đúng cho ranking V3. Frontend cần chuyển sang `ranking_score`, nhưng frontend chưa được sửa trong scope này.
- Manual weather dạng thiếu rolling history nay bị reject thay vì tự điền sai dữ liệu; migration impact đã được document tại schema/Swagger.

## 13. Tests và integration example

Kết quả: **16 passed**.

Coverage bắt buộc gồm:

- registry load đúng 221 model;
- exact feature transform khớp một TRAIN context;
- current/3d/7d weather aggregation khớp trực tiếp locked V3 pipeline trên raw weather;
- regression score/ranking khớp 221 standalone locked boosters với tolerance `1e-12`;
- Top-K lấy từ universe 221, không phải 20 candidate;
- SHAP dương/âm thành `UP`/`DOWN`;
- SUPPORTED và LIMITED gate PASS;
- INSUFFICIENT, CONFLICTING, negative SHAP, factor mismatch và runtime disabled gate FAIL an toàn;
- disease ngoài KB và KB missing không phá ranking/Tầng 1;
- API route cũ hoạt động, alias compatibility còn nguyên;
- không có response key probability/percent.

Integration sample dùng query `Q20210107_C00` thuộc TRAIN, không đọc target. Top 5 tự nhiên là disease IDs `6, 169, 41, 170, 165`; cả năm không có Tier 2 record nên vẫn được xếp hạng và trả Tầng 1 với reason `NO_MEDICAL_KNOWLEDGE`. Tier 2 available branch được xác minh riêng bằng fixture có gate hợp lệ.

## 14. Performance measurement

Đo 7 warm runs, một context thuộc TRAIN, Top 5, cùng process; không đọc target:

| Thành phần | Median | Mean | Min–Max |
|---|---:|---:|---:|
| Startup/load 221 models | 0.774 s | — | — |
| Feature preparation | 10.917 ms | 11.705 ms | 9.605–17.818 ms |
| Ranking 221 models | 224.641 ms | 236.394 ms | 217.947–291.549 ms |
| Tier 1 local SHAP Top 5 | 13.101 ms | 13.152 ms | 11.906–14.715 ms |
| Tier 2 lookup Top 5 | 0.020 ms | 0.285 ms | 0.017–1.878 ms |
| Total service runtime | 255.624 ms | 261.633 ms | 240.909–315.343 ms |

Đây là số đo thực tế trên máy phát triển hiện tại, không phải SLA. Network latency Open-Meteo không nằm trong sample manual locked-feature này.

## 15. Integrity, giới hạn và mở rộng

Checksum trước/sau khớp cho deployment model tree, manifest, SHAP tree, FINAL TEST tree, PRE-TIER-2 tree và medical knowledge base.

Known limitations:

- Ranking score chưa calibrated và không được diễn giải như xác suất.
- Tầng 2 hiện có 20 disease records; disease khác trả Tầng 1 only.
- Mỗi ASGI worker load riêng 221 model; tăng worker làm tăng RAM tương ứng.
- Open-Meteo là dependency network cho realtime mode.
- Frontend chưa chuyển sang contract mới trong scope này.

Hướng mở rộng an toàn:

- frontend render structured Tier 1/Tier 2;
- bổ sung medical record đã research/validate mà không đổi ranking;
- batch endpoint nếu có nhu cầu thực tế;
- metrics/observability theo latency và reason code, không log dữ liệu người dùng không cần thiết.

## Xác nhận

NO TRAINING. NO TUNING. NO MODEL SELECTION. NO TEST TARGET USED. NO FINAL MODEL MODIFICATION. NO SHAP SOURCE MODIFICATION. NO MEDICAL KNOWLEDGE MODIFICATION. NO FRONTEND MODIFICATION.
