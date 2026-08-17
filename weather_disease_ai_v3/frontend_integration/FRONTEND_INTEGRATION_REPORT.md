# Frontend Integration Report — Weather AI V3

## 1. Trạng thái

**FRONTEND INTEGRATION: PASS**

Frontend đã dùng contract ranking V3, hiển thị Tầng 1/Tầng 2 có kiểm soát và không diễn giải `ranking_score` thành xác suất, phần trăm nguy cơ hay số ca dự báo.

## 2. Frontend trước integration

- Framework: React 18 + TypeScript + Vite 6 + Tailwind CSS 4.
- Entry point: `Frontend/src/main.tsx`; điều phối trang tại `Frontend/src/app/App.tsx` và `Frontend/src/app/AppPages.tsx`.
- Trang Weather AI nội bộ: `Frontend/src/app/components/WeatherRisk.tsx`.
- Trang phụ huynh công khai: `Frontend/src/app/components/ParentPortal.tsx` (`/phu-huynh`, `/parents`).
- API client tập trung: `Frontend/src/lib/api.ts`.
- State management: React hooks cục bộ; kết quả Weather AI nội bộ có cache `localStorage`.
- Styling: component/card mobile-first bằng Tailwind; không thay framework hoặc design system.
- Contract cũ từng được dùng trực tiếp trong hai trang: `probability`, `predicted_cases`, `risk_score`, `risk_level`. Trang nội bộ còn có biểu đồ “ca/ngày” dựa trên contract cũ.
- Loading/error đã có nhưng lỗi HTTP bị mất status vì API client chỉ ném `Error` thường.

## 3. Files modified/added

### Modified

- `Frontend/package.json`
- `Frontend/package-lock.json`
- `Frontend/src/lib/api.ts`
- `Frontend/src/lib/weatherRiskCache.ts`
- `Frontend/src/app/components/WeatherRisk.tsx`
- `Frontend/src/app/components/ParentPortal.tsx`
- `Frontend/src/i18n/locales/vi.ts`
- `Frontend/src/i18n/locales/en.ts`

### Added

- `Frontend/src/app/components/weather-ai/WeatherAIResults.tsx`
- `Frontend/src/app/components/weather-ai/WeatherAIResults.test.tsx`
- `Frontend/src/test/setup.ts`
- `Frontend/vitest.config.ts`
- `weather_disease_ai_v3/frontend_integration/FRONTEND_INTEGRATION_REPORT.md`
- `weather_disease_ai_v3/frontend_integration/frontend_validation.json`

## 4. Component architecture sau integration

- `WeatherRisk` và `ParentPortal`: giữ vai trò container, form, location/Open-Meteo request, loading/error và dữ liệu phụ trợ hiện có.
- `WeatherAIPredictionList`: render danh sách ranking và disclaimer.
- `WeatherAIExplanationSections`: render hai tầng giải thích dùng chung giữa hai trang.
- `FactorList`: render yếu tố Tầng 1 theo UP/DOWN bằng cả icon, mũi tên và text.
- `WeatherAIDisclaimer`: luôn hiển thị disclaimer backend; có fallback an toàn nếu text rỗng.
- `WeatherAILoadingNotice`: feedback cho chuỗi lấy weather → ranking → explanation.
- API types và `ApiError` nằm tập trung trong `Frontend/src/lib/api.ts`.

Component dùng chung có 216 dòng; không tạo state framework hoặc design system mới. Hai page cũ vẫn lớn chủ yếu do form/location và danh mục tỉnh có sẵn, nhưng phần prediction/explanation không còn bị lặp trong page.

## 5. API contract mapping

| Backend V3 | Frontend |
|---|---|
| `rank` | Badge `#1`, `#2`… là thông tin chính |
| `disease_id`, `disease_name` | Key ổn định và tên nhóm bệnh |
| `ranking_score` | Có type nhưng chủ động không hiển thị cho phụ huynh |
| `tier1.positive_factors` | “Các yếu tố đẩy thứ hạng lên” |
| `tier1.negative_factors` | “Các yếu tố kéo thứ hạng xuống” |
| `tier2.available` | Gate bắt buộc trước khi render Tầng 2 |
| `tier2.evidence_status` | Wording tiếng Việt thận trọng |
| `tier2.limitations_vi` | Khung “Lưu ý” |
| `tier2.sources` | Link HTTPS, tab mới, `noopener noreferrer` |
| `disclaimer` | Khung lưu ý nhìn thấy được sau danh sách |

Hai page tiếp tục gửi tuổi, giới tính, tọa độ và timezone. Backend tự lấy Open-Meteo realtime; frontend không tạo weather 7 ngày giả. Type manual-weather một ngày cũ đã bị loại khỏi API client vì không còn phù hợp contract V3.

## 6. Ranking semantics

- Rank nổi bật hơn mọi numeric score.
- Copy dùng “nhóm bệnh đáng lưu ý”, “được xếp thứ…” và “xếp hạng tương đối”.
- Không hiển thị raw `ranking_score`.
- Không nhân score với 100, không có `%`, progress bar, “xác suất mắc bệnh” hoặc “ca/ngày” trong UI Weather AI V3.
- Biểu đồ dựa trên `predicted_cases` cũ đã được gỡ.

## 7. Tầng 1

- Chỉ render khi `tier1.available === true`.
- Ưu tiên trực tiếp `label_vi` từ backend; không duplicate feature-label mapping ở frontend.
- Positive/negative được tách rõ, có `↑`/`↓`, icon và text “đẩy thứ hạng lên”/“kéo thứ hạng xuống”.
- Không hiển thị `shap_value`, `base_value_raw` hoặc error code kỹ thuật.
- Không gọi SHAP là xác suất, phần trăm nguy cơ hoặc mức độ gây bệnh.

## 8. Tầng 2

- Chỉ render khi `tier2.available === true` và có `explanation_short_vi`.
- `SUPPORTED` → “Có cơ sở y khoa tương đối rõ”.
- `LIMITED_OR_INDIRECT` → “Bằng chứng còn hạn chế / gián tiếp”.
- Internal reason (`NO_MEDICAL_KNOWLEDGE`, `MEDICAL_KB_ERROR`...) không hiển thị cho phụ huynh.
- `limitations_vi` được hiển thị dưới nhãn “Lưu ý”.
- Chỉ URL HTTPS từ backend được tạo thành link; frontend không fabricate nguồn.
- Tầng 2 unavailable không tạo khung trống hoặc cảnh báo lỗi.

## 9. Migration field cũ

- Weather AI V3 `probability`: removed.
- Weather AI V3 `predicted_cases`: removed.
- Weather AI V3 `risk_score`: removed.
- Weather AI V3 `risk_level`: removed.
- Cache đổi key sang `sd_weather_ai_v3_result` và kiểm tra `rank` + `ranking_score` trước khi hydrate, tránh cache V2 sinh `undefined`/`NaN`.
- Translation “AI ước tính ... ca/ngày” cũ đã gỡ.
- Các field trùng tên trong module forecast/area analytics khác vẫn được giữ vì đó là contract nghiệp vụ khác, không phải Weather AI V3. `ParentPortal` chỉ còn đọc `area.risk_level` làm dữ liệu khu vực và gắn nhãn rõ “Dữ liệu khu vực”.

## 10. Error/loading handling

- API client giữ HTTP status bằng `ApiError`.
- 422: “Thông tin đầu vào chưa hợp lệ.”
- 503: “Hệ thống dự đoán tạm thời chưa sẵn sàng.”
- 500+: “Đã có lỗi khi xử lý. Vui lòng thử lại.”
- Network error có message kết nối riêng; không expose stack trace.
- Submit bị disable trong request và có loading notice mô tả đầy đủ các bước.
- Route public hiện có của backend chuẩn hóa phần lớn exception thành HTTP 400; frontend dùng message 400 chung, trong khi endpoint authenticated vẫn giữ mapping 422/503/500 chính xác. Backend không được sửa trong task này.

## 11. Tests và verification

### Automated

- `npm.cmd run typecheck`: PASS.
- `npm.cmd test`: **17 passed, 0 failed**.
- `npm.cmd run build`: PASS, 2,292 modules transformed.
- Test cover Top-5, rank, no percentage semantics, Tier 1 UP/DOWN, Tier 2 available/unavailable, hai evidence status, source HTTPS, disclaimer, loading, lỗi 422/503/500 và absence của bốn field legacy trong V3 record.

### Real backend through Vite proxy

- `GET /parents`: HTTP 200.
- `POST /api/public/parent-risk`: PASS với tuổi `1-5 tuổi`, giới tính `Nam`, tọa độ TP.HCM và Top-5.
- Response: 5 predictions, rank `[1,2,3,4,5]`, Tier 1 available `5/5`, Tier 2 available `0/5`, disclaimer present, không có legacy key.
- Thời gian quan sát qua proxy: khoảng 992 ms; đây chỉ là một lần smoke test.
- Fixture hợp lệ kiểm tra riêng nhánh Tầng 2 vì sample thật không có Tầng 2.

### Responsive/accessibility

- Card/list dùng layout mobile-first; grid Tier 1 chuyển cột từ `sm`, header/action chuyển từ `sm`/`md`, page shell giữ breakpoint `lg` hiện có.
- Không tạo bảng rộng; text/link được phép wrap; rank và icon có accessible label; UP/DOWN không phụ thuộc màu.
- Static responsive review cho mobile/tablet/desktop: PASS.
- In-app browser và Chrome session đều không khả dụng trong môi trường Codex, nên không có visual click-test hoặc screenshot. Không giả lập screenshot bằng tool khác.

## 12. Integrity và known limitations

- V2, V3 data, deployment models, training experiments, FINAL TEST, SHAP/explainability và medical knowledge tree hash không đổi.
- Không dùng TEST target, không train/tune model, không chạy SHAP.
- Không có source backend nào được sửa trong task frontend; danh sách diff backend trước/sau không đổi.
- Khi chạy backend thật để smoke-test, lifespan backend hiện có tự chạy `seed_default_areas()` và refresh `updated_at` trong `seasonal_disease_backend/database.db` (file bị git-ignore). Đây là side effect runtime của backend hiện hữu; không có schema/source/model/AI artifact nào bị chỉnh sửa. Lần kiểm tra frontend sau nên chạy backend với bản sao SQLite tạm nếu cần checksum byte-for-byte của database.
- Browser automation không khả dụng, vì vậy visual QA thực tế là giới hạn còn lại.
- `npm install` báo 5 cảnh báo dependency audit; không chạy broad dependency upgrade ngoài scope.

