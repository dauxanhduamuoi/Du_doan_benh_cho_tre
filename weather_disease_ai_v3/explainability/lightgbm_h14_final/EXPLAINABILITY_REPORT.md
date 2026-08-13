# Explainability Report — Final LightGBM OVR H14 WITH WEATHER

## 1. Locked model and reproduction

- 221 per-disease LightGBM boosters were recreated from the locked TRAIN+VALIDATION protocol and persisted before reproduction.
- No TEST target was loaded. TEST features were used only to compare the recreated scores with the already saved final score matrix.
- **REPRODUCTION_PASS**: max abs diff=0, mean abs diff=0, RMSE=0.
- Ordered Top-5 agreement=1.000000; Top-10 agreement=1.000000.

## 2. Global SHAP method

`shap.TreeExplainer` with `model_output=raw` was evaluated on a deterministic 512-query sample from TRAIN+VALIDATION. For each disease, mean(|SHAP|) was normalized to sum to one, then macro-averaged across 221 diseases so common diseases could not dominate the summary.

SHAP explains contribution to the internal raw model score. It is not a clinical probability and does not establish causality.

## 3. Top global features

| Rank | Feature | Group | Relative SHAP contribution |
|---:|---|---|---:|
| 1 | age_group | DEMOGRAPHIC | 44.5821% |
| 2 | gender | DEMOGRAPHIC | 8.5548% |
| 3 | day_of_year_cos | SEASONAL_CALENDAR | 6.9371% |
| 4 | day_of_year_sin | SEASONAL_CALENDAR | 5.9808% |
| 5 | temperature_min_7d | WEATHER_7D | 4.0388% |
| 6 | month | SEASONAL_CALENDAR | 3.0101% |
| 7 | wind_speed_max_7d | WEATHER_7D | 2.5855% |
| 8 | temperature_max_7d | WEATHER_7D | 2.4462% |
| 9 | temperature_mean_7d | WEATHER_7D | 2.2390% |
| 10 | rain_max_daily_7d | WEATHER_7D | 2.0801% |

## 4. Seasonal, weather and demographic contribution

| Component | Relative model importance |
|---|---:|
| Seasonal/calendar | 16.0635% |
| Weather total | 30.7996% |
| Demographic | 53.1369% |

The percentages are relative SHAP contributions, not percentages of disease causation.

## 5. Weather windows

| Window | Relative model importance |
|---|---:|
| Current | 2.5628% |
| 3 days | 4.7706% |
| 7 days | 23.4663% |

## 6. Weather variable families

| Weather family | Relative model importance |
|---|---:|
| TEMPERATURE | 11.7173% |
| WIND | 8.8836% |
| HUMIDITY | 5.2163% |
| RAIN_PRECIPITATION | 4.4132% |
| WEATHER_CODE | 0.5692% |

## 7. Disease-level patterns

### Five weather-heavy diseases

| Disease ID | Disease name | Weather | Top group |
|---|---|---:|---|
| 245 | Bệnh lí thai nhi và sơ sinh do biến chứng thai nghén, chửa, đẻ - Fetus and newborn affected by maternal factors and by complications of pregnancy, labour and delivery | 91.3809% | WEATHER_3D |
| 115 | Tâm thần phân liệt, rối loạn dạng phân liệt và hoang tưởng - Schizophrenia, schiztypal and delusional disorders | 84.9386% | WEATHER_7D |
| 242 | Các biến chứng khác của chửa đẻ - Other complications pregnancy and delivery | 81.5396% | WEATHER_7D |
| 191 | Bệnh túi thừa của ruột non - Diverticular disease of intestine | 59.3976% | WEATHER_7D |
| 155 | Tai biến mạch máu não, không xác định rõ chảy máu hoặc do nhồi máu - Stroke, not specified as haemorrhage or infarction | 59.2902% | WEATHER_7D |

### Five seasonal-heavy diseases

| Disease ID | Disease name | Seasonal | Top group |
|---|---|---:|---|
| 1 | Tả - Cholera | 74.9486% | SEASONAL_CALENDAR |
| 137 | Tật khúc xạ, các rối loạn điều tiết - Disorders of refraction and accomodation | 69.4183% | SEASONAL_CALENDAR |
| 60 | U ác dạ dày - Malignant neoplasm of stomach | 58.3107% | SEASONAL_CALENDAR |
| 306 | Người có nguy cơ liên quan đến bệnh truyền nhiễm - Other persons with potential health hazards related to communicable diseases | 58.2065% | SEASONAL_CALENDAR |
| 160 | Bệnh khác của động mạch, tiểu động mạch và mao mạch - Other diseases of arteries, arterioles and capillaries | 53.4491% | SEASONAL_CALENDAR |

## 8. Local Top-5 example

| Rank | Disease ID | Disease name | Ranking score |
|---:|---|---|---:|
| 1 | 6 | Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases | 0.995599 |
| 2 | 169 | Các bệnh viêm phổi - Pneumonia | 0.988870 |
| 3 | 87 | Bệnh bạch cầu - Leukaemia | 0.983804 |
| 4 | 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 0.981652 |
| 5 | 190 | Tắc liệt ruột và tắc ruột không do thoát vị - Paralytic ileus, intestinal obstruction without hernia | 0.980619 |

Example query `Q20230831_C00` ranks disease `6` (Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases) at position 1 with ranking score 0.995599.

Top positive contributors:

- Nhóm tuổi (`age_group` = 1-5 tuổi): SHAP +3.659026.
- Nhiệt độ — 7 ngày gần đây (`temperature_min_7d` = 24.2): SHAP +0.236096.
- Thời điểm trong năm (`day_of_year_cos` = -0.5074302810827518): SHAP +0.213740.
- Lượng mưa — 7 ngày gần đây (`rain_max_daily_7d` = 38.3): SHAP +0.193887.
- Gió — 3 ngày gần đây (`wind_speed_max_3d` = 24.1): SHAP +0.123306.

Top negative contributors:

- Gió — 3 ngày gần đây (`wind_gust_max_3d` = 44.3): SHAP -0.057728.
- Nhiệt độ — 7 ngày gần đây (`temperature_max_7d` = 32.8): SHAP -0.048863.
- Gió — 7 ngày gần đây (`wind_speed_mean_7d` = 9.25119): SHAP -0.041673.
- Nhiệt độ — hiện tại (`temperature_max_current` = 30.1): SHAP -0.032567.
- Gió — 7 ngày gần đây (`wind_gust_max_7d` = 44.3): SHAP -0.030299.

These factors push the locked model score up or down for this query; they do not diagnose disease and do not imply causes.

## 9. Additivity and integrity

- SHAP additivity: **PASS**; maximum raw-score reconstruction error=3.90798504668e-14.
- Model feature names/order, disease order, category mapping, best iterations and locked hyperparameters were verified before training.
- The 221 saved boosters were reloaded from disk for reproduction and SHAP.
- final_test/ and benchmark/ checksum snapshots were unchanged.
- No model selection, hyperparameter tuning, TEST training or TEST-target analysis occurred.

## 10. Limitations

- SHAP describes this fitted model and its historical data patterns, not biological or causal mechanisms.
- Correlated weather/calendar features can share or redistribute importance.
- Macro-normalization gives every disease equal weight but does not measure clinical prevalence or severity.
- Local explanations depend on the exact engineered query and should not be interpreted as individual medical advice.
- Successful pipeline runtime: 24.881 seconds (14.727 seconds persistence training + 10.154 seconds reproduction/SHAP/reporting).
