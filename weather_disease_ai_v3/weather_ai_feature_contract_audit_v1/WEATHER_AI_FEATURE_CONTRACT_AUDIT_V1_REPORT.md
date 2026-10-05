# WEATHER AI FEATURE CONTRACT AUDIT V1

## 1. STATUS

**PASS WITH FINDINGS.** The current executable Weather AI contract was traced from local raw data through the deployed LightGBM artifacts, runtime feature construction, TreeSHAP output, and the Reviewed/Auto Medical Knowledge contracts. No product behavior was changed.

The central conclusion is:

- The canonical Medical Knowledge key `weather_condition` is backed by a real model feature, but that exact string is not a training/model column.
- Its model-side representation is `weather_code_current`, derived as the daily mode of hourly Open-Meteo/WMO `weather_code` values for anchor day D.
- Its primary category is therefore **DERIVED_MODEL_FEATURE**.
- The current dropdown item should be **RENAME**, not remove: use wording that exposes the narrower model meaning, such as **“Trạng thái thời tiết hiện tại (mã WMO)”**. The existing “Điều kiện thời tiết” search topic is semantically broader than the numeric model feature.

## 2. Branch / HEAD / initial git status

- Branch: `feature/medical-knowledge-v1-20260820`
- HEAD: `b22d0e85e001967ade9a08a9bf2ca2089578dbf9`
- Initial `git status --short`: empty (clean)
- Required checkpoint matched; audit proceeded.

## 3. Training pipeline files

| Responsibility | Current source of truth |
|---|---|
| Raw patient/catalog/weather loading | `weather_disease_ai_v3/src/data_pipeline.py`: `DataPreparationPipeline.load_raw_data`, `read_weather_hourly` |
| ICD mapping and daily disease counts | same file: `prepare_catalog`, `build_daily_cases_from_frames` |
| Hourly-to-daily weather | same file: `build_daily_weather` |
| Current/3d/7d weather engineering | same file: `build_weather_features` |
| Calendar and context construction | same file: `add_calendar_features`, `build_contexts` |
| H3/H7/H14 target construction | same file: `build_sparse_targets` |
| Chronological split and purge | same file: `split_anchor_dates_with_purge`, `build_split_query_ids` |
| Benchmark encoding/training | `weather_disease_ai_v3/benchmarks/lightgbm_ovr_h3_h7_h14/benchmark_lightgbm_ovr.py`: `encode_features`, `build_target_matrix`, `train_ovr` |
| Locked final fit | `weather_disease_ai_v3/final_test/lightgbm_ovr_h3_h7_h14/run_final_test.py`: `encode_fit_features`, `transform_features`, `prepare_fit_bundle`, `fit_experiment` |
| Current model serialization | `weather_disease_ai_v3/explainability/lightgbm_h14_final/build_explainability.py`: `main`; writes native LightGBM text via `booster_.model_to_string` |
| Current deployment artifacts | `weather_disease_ai_v3/deployment/lightgbm_h14_weather/{model_manifest.json,feature_schema.json,category_mappings.json,models/*.txt}` |
| Runtime selection | `seasonal_disease_backend/app/config.py` and `app/services/weather_ai_service.py:get_model_registry` |

There is no scaler artifact. Categorical values are integer-encoded; numerical features pass through without scaling.

## 4. Raw training dataset source

- Patient and ICD source: `weather_disease_ai_v3/data/raw/train_history.xlsx`
  - `DS-BenhNhan`: 257,771 rows.
  - `DS-MaBenh`: 12,230 rows.
- Weather source: `weather_disease_ai_v3/data/raw/weather_hcm_history.csv`
  - 37,944 hourly rows.
  - File-level metadata: latitude `10.790861`, longitude `106.6313`, elevation `6.0`, timezone `Asia/Bangkok`/GMT+7.
  - These location metadata are not tabular features.
- Dataset generator verifies the V3 raw copies against their configured originals by SHA-256 before processing.
- Stored training-ready artifacts: `data/processed/contexts.csv.gz`, `targets.csv.gz`, `daily_cases.csv.gz`, `disease_catalog.csv`, plus split query ID files.

## 5. ALL raw dataset columns

### 5.1 `DS-BenhNhan`

| Exact column | Observed dtype | Role | Actual use |
|---|---|---|---|
| `icdNV` | object | TARGET / JOIN_KEY | Admission ICD; fallback when discharge ICD is absent. |
| `icdxuatvien` | object | TARGET / JOIN_KEY | Preferred main/discharge ICD. |
| `check_in_date` | datetime64[ns] | TIME / JOIN_KEY | Encounter date; becomes daily case date. |
| `date_of_birth` | datetime64[ns] | CHILD_INPUT | Primary age derivation. |
| `month` | float64 | CHILD_INPUT | **Age in months fallback only**, not calendar month. |
| `gender` | object | CHILD_INPUT | Normalized to `Nam`, `Nữ`, or other/`Không rõ`. |

### 5.2 `DS-MaBenh`

| Exact column | Observed dtype | Role | Actual use |
|---|---|---|---|
| `MAICD` | object | IDENTIFIER / JOIN_KEY | ICD code joined to `main_icd`. |
| `TENICD` | object | IGNORED | Present in raw sheet; not selected by V3 pipeline. |
| `IDNHOMICD` | int64 | TARGET / IDENTIFIER | Canonical disease-group ID. |
| `TENNHOMICD` | object | TARGET metadata | Disease-group name. |
| `TENKHONGDAU` | object | IGNORED | Not selected. |
| `MANHOMBAOCAO` | object | TARGET metadata | Report-group code. |
| `TENTIENGANH` | object | IGNORED | Not selected. |

The normalized ICD catalog columns are exactly `icd_code`, `disease_group_id`, `disease_group_name`, `report_group_code`.

### 5.3 `weather_hcm_history.csv`

| Exact raw column | Observed dtype | Canonical name | Role |
|---|---:|---|---|
| `time` | object | `time` | TIME / JOIN_KEY |
| `temperature_2m (°C)` | float64 | `temperature_2m` | WEATHER |
| `relative_humidity_2m (%)` | int64 | `relative_humidity_2m` | WEATHER |
| `precipitation (mm)` | float64 | `precipitation` | WEATHER |
| `rain (mm)` | float64 | `rain` | WEATHER |
| `weather_code (wmo code)` | int64 | `weather_code` | WEATHER |
| `wind_speed_10m (km/h)` | float64 | `wind_speed_10m` | WEATHER |
| `wind_gusts_10m (km/h)` | float64 | `wind_gusts_10m` | WEATHER |

Observed raw WMO codes are `0, 1, 2, 3, 51, 53, 55, 61, 63, 65`.

### 5.4 Direct intermediate datasets

- Daily weather columns: `date`, `temperature_mean_daily`, `temperature_max_daily`, `temperature_min_daily`, `humidity_mean_daily`, `humidity_max_daily`, `humidity_min_daily`, `weather_code_daily`, `wind_speed_mean_daily`, `wind_speed_max_daily`, `precipitation_sum_daily`, `rain_sum_daily`, `wind_gust_max_daily`.
- Weather provenance columns: `anchor_date`, `current_start`, `current_end`, `lookback_3d_start`, `lookback_3d_end`, `lookback_7d_start`, `lookback_7d_end`, `weather_complete`.
- `daily_cases.csv.gz`: `date`, `age_group`, `gender`, `disease_group_id`, `disease_group_name`, `case_count_day`.
- `contexts.csv.gz`: `query_id`, `anchor_date`, followed by the 45 model features listed below. `query_id` is IDENTIFIER and `anchor_date` is TIME/JOIN_KEY; neither enters the model.
- `targets.csv.gz`: `query_id`, `disease_group_id`, `case_count_h3`, `has_case_h3`, `case_count_h7`, `has_case_h7`, `case_count_h14`, `has_case_h14`.
- `disease_catalog.csv`: `disease_group_id`, `disease_group_name`, `report_group_code`, `observed_case_count_for_mapping`, and for each H3/H7/H14: `train_case_count_*`, `train_positive_queries_*`, `support_*`.
- Split files contain only `query_id`.

## 6. Feature engineering transformations

1. Normalize ICD values; choose `main_icd = icdxuatvien`, falling back to `icdNV`.
2. Parse mixed dates (including Excel serials), remove rows lacking encounter date/main ICD, and join ICD to the normalized catalog.
3. Compute age from `check_in_date - date_of_birth`; fill missing age from raw `month / 12`; bucket to six age groups.
4. Normalize gender; aggregate encounters by date × age group × gender × disease group to `case_count_day`.
5. Parse hourly weather, coerce weather fields to numeric, reject duplicate timestamps, and require continuous calendar days.
6. Aggregate hourly weather to daily values. `weather_code_daily` is `Series.mode().iloc[0]`; a tie therefore selects the first/smallest mode.
7. Create current-D features, plus exact trailing D-2..D and D-6..D rolling aggregates. `rain_day_current` is `rain_sum_daily > 0`; `rain_days_*` counts rainy days.
8. Keep only anchors with complete seven-day weather and complete H14 target coverage.
9. Cross join each anchor date with 12 observed age/sex pairs; derive calendar `month`, dry/rainy `season`, and sine/cosine of day of year using 365.25.
10. Build sparse positive targets for D..D+2, D..D+6, and D..D+13. Missing query/disease rows mean zero recorded cases.
11. Chronologically split unique anchor dates 70/15/15 with two 13-day purge gaps.
12. Fit category mappings on TRAIN+VALIDATION for the final deployed fit. Encode `age_group`, `gender`, `season`; cast `month` numeric; no imputation remains after context completeness checks; no interaction feature is created.

Dataset size: 18,696 contexts over 1,558 anchor dates (`2021-01-07`..`2025-04-13`). TRAIN has 12,864 queries, VALIDATION 2,748, TEST 2,772.

## 7. Exact X_train features

The exact ordered 45-feature contract is:

1. `age_group`
2. `gender`
3. `month`
4. `season`
5. `day_of_year_sin`
6. `day_of_year_cos`
7. `weather_code_current`
8. `temperature_mean_current`
9. `temperature_max_current`
10. `temperature_min_current`
11. `humidity_mean_current`
12. `humidity_max_current`
13. `humidity_min_current`
14. `wind_speed_mean_current`
15. `wind_speed_max_current`
16. `precipitation_sum_current`
17. `rain_sum_current`
18. `wind_gust_max_current`
19. `rain_day_current`
20. `temperature_mean_3d`
21. `temperature_max_3d`
22. `temperature_min_3d`
23. `humidity_mean_3d`
24. `humidity_max_3d`
25. `humidity_min_3d`
26. `wind_speed_mean_3d`
27. `wind_speed_max_3d`
28. `precipitation_sum_3d`
29. `rain_sum_3d`
30. `rain_days_3d`
31. `rain_max_daily_3d`
32. `wind_gust_max_3d`
33. `temperature_mean_7d`
34. `temperature_max_7d`
35. `temperature_min_7d`
36. `humidity_mean_7d`
37. `humidity_max_7d`
38. `humidity_min_7d`
39. `wind_speed_mean_7d`
40. `wind_speed_max_7d`
41. `precipitation_sum_7d`
42. `rain_sum_7d`
43. `rain_days_7d`
44. `rain_max_daily_7d`
45. `wind_gust_max_7d`

Categorical mappings:

- `age_group`: `1-5 tuổi=0`, `11-15 tuổi=1`, `6-10 tuổi=2`, `Dưới 1 tuổi=3`, `Không rõ=4`, `Trên 15 tuổi=5`.
- `gender`: `Nam=0`, `Nữ=1`.
- `season`: `Mùa khô=0`, `Mùa mưa=1`.

## 8. Exact model artifact feature names

The deployment manifest and feature schema contain the same ordered list in section 7. A read-only load of all 221 native boosters using LightGBM's `Booster.feature_name()` confirmed that **221/221** models expose exactly that same list and order.

Result: one shared feature contract; no per-disease feature-set difference.

The manifest status is `DEPLOYMENT_READY_REPRODUCTION_PASS`, with 221 models and training data declared as TRAIN + VALIDATION only.

## 9. Target/label

- Deployed horizon: H14.
- For each query context and each supported disease group, the binary target is `has_case_h14 = 1` when at least one mapped encounter exists for the same age group and gender in D..D+13; otherwise 0.
- `case_count_h14` is used to construct/describe targets, but the deployed classifier label is binary.
- Candidate catalog: 311 groups; 235 observed in the full source; deployed universe: 221 TRAIN-supported groups.
- The target matrix is dense in memory but originates from a sparse positive table; missing sparse rows are zeros.

## 10. Model/output architecture

- Architecture: 221 independent LightGBM binary GBDT classifiers, one per disease group (one-vs-rest), not one multiclass model.
- Each booster returns its sigmoid output. Runtime sorts the 221 independent scores descending using stable ordering and returns the first `top_k`.
- The values do **not** form a probability distribution and do not sum to one. They are not demonstrated to be calibrated individual-diagnosis probabilities.
- Correct product term: `ranking_score` / relative candidate score for historical occurrence in a matching context, not “probability of disease.”

## 11. Parent request DTO

Current public endpoint: `POST /api/public/parent-risk`, DTO `ParentRiskRequest`.

| Request field | Parent frontend sends | Backend uses | Direct model feature | Weather fetch only | Output control |
|---|---|---|---|---|---|
| `age_group` | YES | Validates/encodes | YES: `age_group` | NO | NO |
| `gender` | YES | Validates/encodes | YES: `gender` | NO | NO |
| `top_k` | YES | Validates 1..20 | NO | NO | YES |
| `latitude` | YES, from GPS/province | Open-Meteo request | NO | YES | NO |
| `longitude` | YES, from GPS/province | Open-Meteo request | NO | YES | NO |
| `timezone` | YES (`Asia/Ho_Chi_Minh`) | Weather day boundary | NO | YES | NO |
| `weather` | DTO supports; current frontend does not send | Manual locked-vector or seven-day mode | Indirect source | Bypasses fetch | NO |

The authenticated endpoint additionally exposes optional `target_date`; the public Parent DTO does not. Province/region code is used by separate local-risk calls, not by Weather AI model inference.

## 12. Backend-derived runtime fields

| Source | Runtime field(s) | Model | Display/output | Medical Knowledge |
|---|---|---:|---:|---:|
| Selected weather anchor date | `anchor_date` | NO | YES | NO |
| Anchor date | `month` | YES | YES | Via SHAP → `SEASONALITY/time_of_year` |
| Month mapping | `season` | YES | YES | Via SHAP → seasonality |
| Anchor day | `day_of_year_sin`, `day_of_year_cos` | YES | YES | Via SHAP → seasonality |
| Hourly WMO code daily mode | `weather_code_current` | YES | YES | SHAP `weather_code` → canonical `weather_condition` |
| Hourly temperature | 9 current/3d/7d temperature aggregates | YES | YES | `WEATHER/temperature` |
| Hourly humidity | 9 current/3d/7d humidity aggregates | YES | YES | `WEATHER/humidity` |
| Hourly precipitation/rain | 11 current/3d/7d rain aggregates/indicators | YES | YES | `WEATHER/precipitation` |
| Hourly wind/gust | 9 current/3d/7d wind aggregates | YES | YES | `WEATHER/wind` |
| Open-Meteo response/request | `weather.meta.source/latitude/longitude/timezone/date/daily_series` | NO | YES | NO |

No runtime `weather_description`, `weather_main`, or `weather_type` is created.

## 13. Train/inference parity

All 45 model features have a runtime source and the feature order is enforced before prediction.

| Training feature(s) | Inference source/transformation | Status |
|---|---|---|
| `age_group` | Request; strict canonical option; same locked mapping | PASS |
| `gender` | Request; strict canonical option; same locked mapping | PASS |
| `month` | Weather anchor date month | PASS |
| `season` | Same Dec-Apr dry / May-Nov rainy mapping | PASS |
| `day_of_year_sin` | `sin(2π × day/365.25)` | PASS |
| `day_of_year_cos` | `cos(2π × day/365.25)` | PASS |
| `weather_code_current` | Daily mode of hourly `weather_code` at D | PASS |
| `temperature_mean_current` | D hourly mean | PASS |
| `temperature_max_current` | D hourly max | PASS |
| `temperature_min_current` | D hourly min | PASS |
| `humidity_mean_current` | D hourly mean | PASS |
| `humidity_max_current` | D hourly max | PASS |
| `humidity_min_current` | D hourly min | PASS |
| `wind_speed_mean_current` | D hourly mean | PASS |
| `wind_speed_max_current` | D hourly max | PASS |
| `precipitation_sum_current` | D hourly sum | PASS |
| `rain_sum_current` | D hourly sum | PASS |
| `wind_gust_max_current` | D hourly max | PASS |
| `rain_day_current` | `rain_sum_daily > 0` | PASS |
| `temperature_mean_3d` | Mean of daily means, D-2..D | PASS |
| `temperature_max_3d` | Max of daily maxima, D-2..D | PASS |
| `temperature_min_3d` | Min of daily minima, D-2..D | PASS |
| `humidity_mean_3d` | Mean of daily means, D-2..D | PASS |
| `humidity_max_3d` | Max of daily maxima, D-2..D | PASS |
| `humidity_min_3d` | Min of daily minima, D-2..D | PASS |
| `wind_speed_mean_3d` | Mean of daily means, D-2..D | PASS |
| `wind_speed_max_3d` | Max of daily maxima, D-2..D | PASS |
| `precipitation_sum_3d` | Sum of daily totals, D-2..D | PASS |
| `rain_sum_3d` | Sum of daily totals, D-2..D | PASS |
| `rain_days_3d` | Count of days with rain > 0, D-2..D | PASS |
| `rain_max_daily_3d` | Max daily rain, D-2..D | PASS |
| `wind_gust_max_3d` | Max daily gust, D-2..D | PASS |
| `temperature_mean_7d` | Mean of daily means, D-6..D | PASS |
| `temperature_max_7d` | Max of daily maxima, D-6..D | PASS |
| `temperature_min_7d` | Min of daily minima, D-6..D | PASS |
| `humidity_mean_7d` | Mean of daily means, D-6..D | PASS |
| `humidity_max_7d` | Max of daily maxima, D-6..D | PASS |
| `humidity_min_7d` | Min of daily minima, D-6..D | PASS |
| `wind_speed_mean_7d` | Mean of daily means, D-6..D | PASS |
| `wind_speed_max_7d` | Max of daily maxima, D-6..D | PASS |
| `precipitation_sum_7d` | Sum of daily totals, D-6..D | PASS |
| `rain_sum_7d` | Sum of daily totals, D-6..D | PASS |
| `rain_days_7d` | Count of days with rain > 0, D-6..D | PASS |
| `rain_max_daily_7d` | Max daily rain, D-6..D | PASS |
| `wind_gust_max_7d` | Max daily gust, D-6..D | PASS |

Important non-schema caveat: training weather is one TP.HCM coordinate, while runtime accepts GPS/province coordinates across Vietnam. Transformation parity passes, but geographic distribution parity is not established.

## 14. SHAP feature mapping

Runtime TreeSHAP calls the selected booster with the same one-row encoded DataFrame and `pred_contrib=True`. It returns 45 contributions plus a base value in raw-margin space; additivity is checked against `raw_score` at tolerance `1e-6`. SHAP can therefore output only actual model features.

| Exact feature(s) | Artifact Vietnamese label | Tier-1 category / canonical bridge |
|---|---|---|
| `age_group` | Nhóm tuổi | DEMOGRAPHIC → AGE/age_group |
| `gender` | Giới tính | DEMOGRAPHIC → SEX/gender |
| `month` | Yếu tố mùa vụ theo tháng | SEASONAL_CALENDAR → SEASONALITY/time_of_year |
| `season` | Mùa mưa / mùa khô | SEASONAL_CALENDAR → SEASONALITY/time_of_year |
| `day_of_year_sin`, `day_of_year_cos` | Thời điểm trong năm | SEASONAL_CALENDAR → SEASONALITY/time_of_year |
| `weather_code_current` | Trạng thái thời tiết — hiện tại | WEATHER / `weather_code` → `weather_condition` |
| `temperature_mean_current`, `temperature_max_current`, `temperature_min_current` | Nhiệt độ — hiện tại | WEATHER / `temperature` |
| `humidity_mean_current`, `humidity_max_current`, `humidity_min_current` | Độ ẩm — hiện tại | WEATHER / `humidity` |
| `wind_speed_mean_current`, `wind_speed_max_current`, `wind_gust_max_current` | Gió — hiện tại | WEATHER / `wind` |
| `precipitation_sum_current`, `rain_sum_current`, `rain_day_current` | Lượng mưa — hiện tại | WEATHER / `precipitation` |
| `temperature_mean_3d`, `temperature_max_3d`, `temperature_min_3d` | Nhiệt độ — 3 ngày gần đây | WEATHER / `temperature` |
| `humidity_mean_3d`, `humidity_max_3d`, `humidity_min_3d` | Độ ẩm — 3 ngày gần đây | WEATHER / `humidity` |
| `wind_speed_mean_3d`, `wind_speed_max_3d`, `wind_gust_max_3d` | Gió — 3 ngày gần đây | WEATHER / `wind` |
| `precipitation_sum_3d`, `rain_sum_3d`, `rain_days_3d`, `rain_max_daily_3d` | Lượng mưa — 3 ngày gần đây | WEATHER / `precipitation` |
| `temperature_mean_7d`, `temperature_max_7d`, `temperature_min_7d` | Nhiệt độ — 7 ngày gần đây | WEATHER / `temperature` |
| `humidity_mean_7d`, `humidity_max_7d`, `humidity_min_7d` | Độ ẩm — 7 ngày gần đây | WEATHER / `humidity` |
| `wind_speed_mean_7d`, `wind_speed_max_7d`, `wind_gust_max_7d` | Gió — 7 ngày gần đây | WEATHER / `wind` |
| `precipitation_sum_7d`, `rain_sum_7d`, `rain_days_7d`, `rain_max_daily_7d` | Lượng mưa — 7 ngày gần đây | WEATHER / `precipitation` |

Frontend groups related raw SHAP features for display. That presentation grouping does not create new SHAP features.

## 15. Reviewed factor contract

The registry is hardcoded in `app/medical_knowledge_factors.py`; AGE/SEX values are loaded dynamically from the deployed category mapping.

| Type / key | Value rule | UI label | Reviewed selectable/canonical | Guided search vocabulary | Relevance vocabulary |
|---|---|---|---:|---|---|
| `AGE/age_group` | Required; one of 6 deployed age groups | Độ tuổi | YES | age factors, age distribution, age-specific + selected value | age-specific/distribution/group/stratified/pediatric age + bucket hints |
| `SEX/gender` | Required; `Nam` or `Nữ` | Giới tính | YES | sex factors/differences, male, female + value | sex/gender differences/specific, by sex, comparison phrases |
| `SEASONALITY/time_of_year` | Must be null | Thời điểm trong năm / tính mùa vụ | YES | seasonality, seasonal variation/incidence/pattern | seasonality, pattern, variation, time of year, monthly pattern |
| `WEATHER/temperature` | Must be null | Nhiệt độ | YES | temperature, heat, cold | ambient/air/environmental temperature, hot/cold weather, heat/cold exposure |
| `WEATHER/humidity` | Must be null | Độ ẩm | YES | humidity | humidity/relative/absolute humidity; Reviewed additionally accepts `moisture` |
| `WEATHER/precipitation` | Must be null | Mưa / lượng mưa | YES | rainfall, precipitation, flood/flooding | same broad family |
| `WEATHER/wind` | Must be null | Gió | YES | wind, wind speed | wind speed/velocity, meteorological wind |
| `WEATHER/weather_condition` | Must be null | Điều kiện thời tiết | YES | weather, meteorological conditions | weather condition, meteorological condition, weather, meteorological, climate condition |

Topics are created on demand in the database from the canonical selector; registry membership is not inferred from model metadata.

## 16. Auto factor contract

Auto uses the same canonical selector validation, but its queue, discovery, evidence qualification, generation, revision, and visibility flow are separate from Reviewed.

| Concept | Auto key | Can create topic | Discovery/search vocabulary | Evidence gate recognizes | Same topic key as Reviewed |
|---|---|---:|---:|---:|---:|
| AGE | `AGE/age_group/<value>` | YES | YES | YES | YES |
| SEX | `SEX/gender/<value>` | YES | YES | YES | YES |
| SEASONALITY | `SEASONALITY/time_of_year/null` | YES | YES | YES | YES |
| TEMPERATURE | `WEATHER/temperature/null` | YES | YES | YES | YES |
| HUMIDITY | `WEATHER/humidity/null` | YES | YES | YES | YES |
| RAIN | `WEATHER/precipitation/null` | YES | YES | YES | YES |
| WIND | `WEATHER/wind/null` | YES | YES | YES | YES |
| WEATHER CONDITION | `WEATHER/weather_condition/null` | YES | YES | YES | YES |

“Can create” means a Parent/Admin selector can cause `get_or_create_topic` and queueing. Auto does not independently enumerate every disease × factor combination. For WEATHER and SEASONALITY, factor values must remain null, so Auto evidence is about the broad factor, not a specific observed WMO code/month/season value.

## 17. Weather Condition investigation

### Definitive trace

`weather_hcm_history.csv: weather_code (wmo code)`
→ canonical hourly `weather_code`
→ daily mode `weather_code_daily`
→ model feature `weather_code_current`
→ LightGBM feature #7
→ TreeSHAP factor with `weather_factor="weather_code"`
→ frontend bridge `weather_code -> weather_condition`
→ canonical Medical Knowledge topic `WEATHER/weather_condition/null`
→ Reviewed or Auto publication lookup.

Answers:

1. Present in raw training data? **YES**, as `weather_code (wmo code)` / canonical `weather_code`.
2. Present in X_train? **YES**, after daily-mode derivation as `weather_code_current`.
3. Expected by current artifacts? **YES**, feature #7 in all 221 boosters.
4. Supplied at inference? **YES**, derived from hourly Open-Meteo data or accepted in a manual locked vector.
5. Can SHAP output it? **YES**, under exact feature name `weather_code_current`.
6. Reviewed allows it? **YES**, as `WEATHER/weather_condition`.
7. Auto allows it? **YES**, same canonical key.
8. Values? Numeric WMO weather codes. Training observed 10 values: `0,1,2,3,51,53,55,61,63,65`. Runtime does not map them to descriptions or restrict future/provider values to that observed set.
9. Meaning? The most frequent hourly WMO code on the current anchor day. It is not a prose weather description and is not an aggregate of temperature/humidity/rain/wind.

Primary classification: **DERIVED_MODEL_FEATURE**.

Recommendation: **RENAME** the dropdown label to reflect the actual model concept, ideally “Trạng thái thời tiết hiện tại (mã WMO)”. Keep the canonical key only if product wants a broad evidence topic to stand in for that feature. A later design may decide whether evidence should be specific to WMO classes; this audit makes no UI change.

## 18. Cross-contract matrix

| Factor / concept | Raw training data | Actual model feature | Parent sends | Backend derives | SHAP | Reviewed | Auto |
|---|---|---|---|---|---|---|---|
| Age (`date_of_birth`, raw `month` → `age_group`) | YES | YES `age_group` | YES `age_group` | validation/encoding | YES | YES | YES |
| Sex (`gender`) | YES | YES `gender` | YES | validation/encoding | YES | YES | YES |
| Region/location (`latitude`,`longitude`) | YES as fixed file metadata, not a row column | NO | YES | weather-fetch context | NO | NO | NO |
| Time/month (`check_in_date` → `month`, sin/cos) | YES | DERIVED | NO | YES | YES | Via seasonality | Via seasonality |
| Seasonality (`season`, day cycle) | DERIVED | YES | NO | YES | YES | YES | YES |
| Temperature | YES | DERIVED aggregates | NO | YES | YES | YES | YES |
| Humidity | YES | DERIVED aggregates | NO | YES | YES | YES | YES |
| Rain/precipitation | YES | DERIVED aggregates | NO | YES | YES | YES `precipitation` | YES `precipitation` |
| Wind | YES | DERIVED aggregates | NO | YES | YES | YES | YES |
| Weather condition | YES `weather_code` | DERIVED `weather_code_current` | NO | YES | YES | YES `weather_condition` | YES `weather_condition` |
| Top K | NO | NO | YES `top_k` | NO | N/A | N/A | N/A |
| Disease group / target | YES via ICD mapping | N/A (one classifier per group) | NO | NO | Per selected disease model | Topic dimension | Topic dimension |

## 19. End-to-end sample

This sample is a real offline replay of TEST context `Q20240826_C00`. No weather network call was made.

### A. Normal Parent request shape

```json
{
  "age_group": "1-5 tuổi",
  "gender": "Nam",
  "top_k": 5,
  "latitude": 10.790861,
  "longitude": 106.6313,
  "timezone": "Asia/Ho_Chi_Minh"
}
```

For deterministic offline replay, the same runtime builder was called with the stored 39 weather features and `target_date=2024-08-26`, bypassing only the external fetch.

### B. Backend-derived context

```json
{
  "anchor_date": "2024-08-26",
  "month": 8,
  "season": "Mùa mưa",
  "day_of_year_sin": -0.8247650844733614,
  "day_of_year_cos": -0.5654755126737576,
  "weather_code_current": 51,
  "temperature_mean_current": 26.875,
  "humidity_mean_current": 86.166667,
  "rain_sum_current": 28.1,
  "wind_speed_mean_current": 6.6875
}
```

### C. Exact ordered encoded model vector

```text
[0, 0, 8, 1, -0.8247650845, -0.5654755127,
 51, 26.875, 31.9, 24.4, 86.166667, 97, 65, 6.6875, 16.1,
 28.1, 28.1, 29.9, 1,
 26.998611, 32.0, 23.8, 84.986111, 99, 63, 5.613889, 16.1,
 48.2, 48.2, 3, 28.1, 29.9,
 27.660714, 33.2, 23.8, 83.267857, 99, 59, 5.600595, 16.1,
 58.9, 58.9, 7, 28.1, 33.5]
```

The positions correspond exactly to section 7. The first four encodings are `age_group=0`, `gender=0`, `month=8`, `season=1`.

### D. Actual local model output

| Rank | Disease group | `ranking_score` |
|---:|---|---:|
| 1 | `6` — Các bệnh nhiễm khuẩn ruột khác | 0.9946499009 |
| 2 | `169` — Các bệnh viêm phổi | 0.9810266868 |
| 3 | `32` — Sốt virut khác do tiết túc truyền và sốt virus xuất huyết | 0.9800401593 |
| 4 | `87` — Bệnh bạch cầu | 0.9789871284 |
| 5 | `190` — Tắc liệt ruột và tắc ruột không do thoát vị | 0.9741111778 |

These are ranking scores, not calibrated diagnosis probabilities.

### E. Actual Tier-1 shape

For rank 4, SHAP included:

```json
{
  "feature": "weather_code_current",
  "label_vi": "Trạng thái thời tiết — hiện tại",
  "category": "WEATHER",
  "window": "CURRENT",
  "input_value": 51.0,
  "shap_value": -0.041782034436466435,
  "direction": "DOWN",
  "weather_factor": "weather_code"
}
```

This directly proves the weather-condition concept is reachable from a real current-model SHAP result.

### F. Tier-2 canonical topics derivable from positive SHAP

Examples from this real top-5 response include `6 + WEATHER/wind`, `6 + WEATHER/temperature`, `6 + AGE/age_group/1-5 tuổi`, `6 + SEASONALITY/time_of_year`, `169 + WEATHER/precipitation`, and `32 + WEATHER/humidity`. A `WEATHER/weather_condition` selector would be produced only when `weather_code_current` is among a prediction's **positive** Tier-1 factors; the sample occurrence was negative, so it was not requested for that disease.

## 20. Drift/stale/dead contracts

1. **Legacy Weather AI training path exists but is not runtime source of truth.** `seasonal_disease_backend/scripts/train_weather_ai_model.py` targets `app/ml/weather_ai_risk_model.joblib` and uses a different feature contract including disease ID/report code as inputs. A local legacy joblib and summaries exist, but current config points exclusively to V3 deployment boosters.
2. **Internal naming bridge is split.** Runtime Tier-1 emits `weather_code`; the published Medical Knowledge contract uses `weather_condition`; frontend performs the explicit bridge. This works, but backend contracts alone are not name-identical.
3. **Presentation-only `rain` alias exists.** `Frontend/src/lib/medicalKnowledgeFactors.ts` contains a `rain` label/icon alias, while canonical APIs support only `precipitation`. It is not a selectable canonical topic returned by the backend catalog.
4. **Runtime registry does not compare booster feature names to manifest.** It checks count and frame order, while the audit independently confirmed all names match. The deployment build did perform this comparison during reproduction.
5. **Generic evidence topic loses observed value.** `WEATHER/weather_condition` requires `factor_value=null`; WMO code 51 versus code 0 does not create distinct Medical Knowledge topics.
6. **Frontend condition details are empty.** The Tier-1 presentation recognizes `WEATHER_CONDITION` but intentionally returns no human-readable WMO description; users see a title without decoded condition detail.

## 21. Documentation-vs-code mismatches

- Legacy backend scripts/readmes describing a single `weather_ai_risk_model.joblib` are stale for current execution. Current runtime uses 221 native LightGBM text boosters.
- Training weather file metadata says `Asia/Bangkok`; runtime defaults to `Asia/Ho_Chi_Minh`. Both are UTC+7 for the audited dates, so values align, but the contract strings are not identical.
- Any wording that calls `ranking_score` a disease probability conflicts with runtime's explicit `relative_ranking_score_not_calibrated_probability` contract.
- “Điều kiện thời tiết” is broader than current executable model semantics (`weather_code_current`) and broader than the exact SHAP label (“Trạng thái thời tiết — hiện tại”).

## 22. Risks / recommendations

1. **RENAME** the UI option to “Trạng thái thời tiết hiện tại (mã WMO)” or similarly precise wording; do not remove it because it is backed by a real feature.
2. Decide separately whether Medical Knowledge evidence should remain broad (`weather_condition`) or be value-aware. That is a product/evidence-schema decision, not a model-contract fix.
3. Treat WMO code as a discrete condition. It is currently numeric and is not declared categorical to LightGBM; retraining to change that would be a model change requiring a new experiment, not an audit correction.
4. Add runtime verification of `booster.feature_name() == manifest.feature_order` in a future change.
5. Explicitly validate geographic generalization before presenting nationwide GPS/province predictions; the model was trained from one TP.HCM weather series.
6. Consider decoding WMO codes for display while retaining the numeric feature untouched.
7. Retire or clearly label the legacy joblib scripts/artifacts in a separate cleanup task after confirming no operational user depends on them.

## 23. Files changed by audit

Only:

- `weather_disease_ai_v3/weather_ai_feature_contract_audit_v1/WEATHER_AI_FEATURE_CONTRACT_AUDIT_V1_REPORT.md`
- `weather_disease_ai_v3/weather_ai_feature_contract_audit_v1/weather_ai_feature_contract_audit_v1_validation.json`

## 24. Commands run

- Read-only Git state commands: branch, HEAD, status, tracked-file inventory.
- Repository searches with `rg`.
- Read-only source/config/JSON/CSV/XLSX inspection.
- Read-only LightGBM loading of all 221 deployment artifacts and `Booster.feature_name()` comparison.
- One local deterministic inference and TreeSHAP replay using a stored TEST context and manual locked weather vector.
- No test suite, production build, migration, training, or model serialization was run.

## 25. Network calls = 0

No weather API, PubMed, WHO, Groq, OpenAI, or other external provider was called.

## 26. DB mutations = 0

No database query requiring production credentials, write, migration, or row mutation was performed.

## 27. NO COMMIT / NO PUSH

No commit was created and no push was performed.
