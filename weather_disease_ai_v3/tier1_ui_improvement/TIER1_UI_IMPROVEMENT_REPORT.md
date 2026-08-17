# Weather AI V3 — Tier 1 Parent-Friendly UI

Ngày kiểm tra: 2026-08-15

Trạng thái: **PASS**

Đây chỉ là thay đổi presentation phía frontend. Không thay backend contract, model, ranking, cách tính SHAP, Tier 2, medical knowledge hoặc dữ liệu.

## 1. UI trước khi sửa

Tier 1 render trực tiếp mỗi raw factor thành một card chỉ có `label_vi`. Hai cột dùng heading kỹ thuật “Các yếu tố đẩy thứ hạng lên” và “Các yếu tố kéo thứ hạng xuống”. UI không dùng `input_value`, vì vậy phụ huynh không thấy tuổi, giới tính hoặc giá trị thời tiết thực tế.

Các feature cùng ý nghĩa như `temperature_min_7d`, `temperature_mean_7d`, `temperature_max_7d` tạo nhiều card “Nhiệt độ — 7 ngày gần đây”. `day_of_year_sin` và `day_of_year_cos` cũng có thể tạo hai card “Thời điểm trong năm”.

## 2. Root problem

Frontend chưa có presentation normalization. JSX nhận raw Tier 1 factors và render một-một, dù API đã cung cấp đủ:

- `feature`;
- `label_vi`;
- `category`;
- `window`;
- `input_value`;
- `shap_value`;
- `direction`;
- `weather_factor`.

Vấn đề nằm ở presentation layer, không phải backend hay SHAP calculation.

## 3. Files modified/added

Modified:

- `Frontend/src/app/components/weather-ai/WeatherAIResults.tsx`
- `Frontend/src/app/components/weather-ai/WeatherAIResults.test.tsx`

Added:

- `Frontend/src/app/components/weather-ai/tier1Presentation.ts`
- `weather_disease_ai_v3/tier1_ui_improvement/TIER1_UI_IMPROVEMENT_REPORT.md`
- `weather_disease_ai_v3/tier1_ui_improvement/tier1_ui_validation.json`

Không sửa `api.ts`, `WeatherRisk.tsx`, `ParentPortal.tsx` hoặc bất kỳ file backend nào trong task này. Cả hai frontend flow tiếp tục dùng component giải thích chung.

## 4. Presentation grouping rules

Raw arrays được giữ nguyên và truyền qua một helper duy nhất:

`RawTier1Factor[] → buildTier1DisplayGroups() → Tier1DisplayGroup[]`

Grouping chỉ dùng `feature`, `category`, `window`, `input_value` và `direction`. Frontend không đọc raw SHAP number để tính lại ý nghĩa, không cộng, average, normalize hoặc tạo SHAP tổng.

Các concept chính:

- `age_group` → `AGE`;
- `gender` → `GENDER`;
- calendar/seasonal features → `TIME_OF_YEAR`;
- `temperature_*` → `TEMPERATURE`;
- `humidity_*` → `HUMIDITY`;
- `rain_*`/`precipitation_*` → `PRECIPITATION`;
- `wind_speed_*`/`wind_gust_*` → `WIND`;
- `weather_code_*` → `WEATHER_CONDITION`.

Weather concept giữ riêng `CURRENT`, `3D` và `7D`.

## 5. Time-of-year dedup rule

`month`, `season`, `day_of_year_sin` và `day_of_year_cos` cùng được presentation-group thành `TIME_OF_YEAR`.

- Nếu `month` và `season` có actual input: render ví dụ “Hiện tại là tháng 8, thuộc mùa mưa.”
- Nếu chỉ có month hoặc season: render phần dữ liệu thực sự có.
- Nếu chỉ có sin/cos: render label tự nhiên “Thời điểm trong năm”, không reverse-engineer tháng từ giá trị toán học.
- Sin/cos cùng direction chỉ tạo một card.

## 6. Weather grouping rule

Các raw weather factors được group theo `WEATHER FAMILY + WINDOW`. Ví dụ ba factor min/mean/max của temperature 7D chỉ tạo một card “Nhiệt độ trong 7 ngày gần đây”.

Không giới hạn lại bằng SHAP threshold mới. Số raw factors backend trả về được bảo toàn; chỉ số card presentation giảm nhờ gom trùng nghĩa.

Weather code không có mapping WMO đáng tin cậy trong frontend nên UI dùng fallback “Tình trạng thời tiết …” và không hiển thị raw code.

## 7. Mixed-direction handling

Nếu các factor trong cùng family/window cùng `UP` hoặc cùng `DOWN`, UI render một card trong nhóm tương ứng.

Nếu direction mâu thuẫn, card được chuyển sang section riêng:

**“Các yếu tố có tác động theo nhiều chiều”**

Card dùng wording trung tính và có compact detail ↑/↓ theo từng human label. UI không gộp mixed group thành một claim tăng hoặc giảm sai.

## 8. Value formatting

Chỉ format khi `input_value` tồn tại và hợp lệ. Không fabricate numeric value.

Đơn vị được audit từ raw Open-Meteo dataset hiện có:

- temperature: °C;
- relative humidity: %;
- precipitation/rain: mm;
- wind speed/gust: km/h.

Quy tắc chính:

- tuổi: “Trẻ thuộc nhóm 1–5 tuổi”;
- giới tính: “Giới tính: Nam”;
- temperature min/max: “26–33°C”;
- temperature/humidity mean: một dòng trung bình riêng;
- wind mean/max/gust: các detail đúng thuật ngữ;
- rain sum, precipitation sum, max daily rain và rain days: các detail riêng, không trộn thành một số giả;
- missing value: human title + fallback không có số.

Raw `shap_value` và raw technical feature name không xuất hiện trong parent UI.

## 9. Example before/after

Before:

- “Nhiệt độ — 7 ngày gần đây” × 3;
- không có giá trị input;
- heading “Các yếu tố đẩy thứ hạng lên”.

After:

- “Vì sao AI xếp nhóm bệnh này ở vị trí #2?”;
- “Đang làm nhóm bệnh này được xếp cao hơn” / “được xếp thấp hơn”;
- một card “Nhiệt độ trong 7 ngày gần đây”;
- “Nhiệt độ trong 7 ngày gần đây: 26–33°C”;
- “Nhiệt độ trung bình trong 7 ngày gần đây: 29°C” khi mean thực sự có;
- disclaimer Tier 1: đây là ảnh hưởng đến điểm xếp hạng, không có nghĩa trực tiếp gây bệnh.

## 10. Tests

Vitest: **30 passed, 0 failed**.

Coverage xác nhận:

1. age group hiển thị actual value;
2. day-of-year sin/cos dedup;
3. temperature min/mean/max cùng window chỉ tạo một card;
4. range min/max đúng;
5. missing input dùng fallback, không fabricate;
6. positive factor nằm trong nhóm “xếp cao hơn”;
7. negative factor nằm trong nhóm “xếp thấp hơn”;
8. mixed direction không tạo claim UP/DOWN sai;
9. raw SHAP value không render;
10. raw technical feature name không render khi có human presentation;
11. Tier 1 không có causal claim;
12. Tier 2 rendering cũ vẫn PASS;
13. disclaimer chung cũ vẫn PASS;
14. month+season tạo một mô tả thời điểm thực;
15. presentation helper không mutate raw factors.

## 11. Typecheck and build

- `npm test`: **PASS**, 30/30.
- `npm run typecheck`: **PASS**.
- `npm run build`: **PASS**, 2,293 modules transformed.
- `git diff --check`: **PASS**.

## 12. Static UI review and remaining limitations

Static responsive review: **PASS**.

- Mobile: grid mặc định một cột.
- Desktop: UP/DOWN chuyển thành hai cột từ breakpoint `sm`.
- Cards dùng `min-w-0`, text wrap tự nhiên, không fixed height và không có horizontal overflow rule nguy hiểm.
- Mixed section tách riêng, dễ phân biệt với UP/DOWN.
- Grouping giảm duplicate label và chiều cao card so với render raw factors.

`VISUAL_BROWSER_QA = NOT_AVAILABLE`: browser tích hợp không khả dụng. Không cài thêm browser automation framework và không tạo screenshot.

Remaining limitations:

- Frontend chỉ format những factor backend thực sự chọn vào Tier 1; nếu `input_value` thiếu, UI chủ động fallback không có số.
- Weather code giữ human fallback vì frontend chưa có mapping WMO được khóa.
- Presentation grouping không thay thế hoặc diễn giải lại logic SHAP.

## 13. Integrity

Tree digests trước/sau giống hệt:

- Backend: `edea4e8735e97fc502dd9d9ed37aab150ac8eae58982292b1ea3071e6d8227a6`.
- Model deployment: `17947271573c995e6bbfc9c187027ea86ef24ba51a7876f4cb1b430b4f862274`.
- SHAP/explainability: `8964b4352ab6ee61c4b9bf5d609d6e7df5f799e2224b6633ee37e7c74e517ac5`.
- Medical explainability: `08b7c1ad342f4d17a62ed40e20640071506078b2675f4bacea3950d41008222b`.

**NO BACKEND MODIFICATION.**  
**NO MODEL MODIFICATION.**  
**NO SHAP LOGIC MODIFICATION.**  
**NO TIER 2 LOGIC MODIFICATION.**  
**NO MEDICAL KNOWLEDGE MODIFICATION.**  
**NO TRAINING.**  
**NO TUNING.**  
**NO TEST TARGET USED.**

## 14. Decision

**TIER 1 UI IMPROVEMENT: PASS**
