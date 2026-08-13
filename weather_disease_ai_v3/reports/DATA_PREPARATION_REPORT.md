# Data Preparation Report — Weather Disease AI V3

Giai đoạn này chỉ chuẩn bị dữ liệu và khung baseline/metrics. **Chưa huấn luyện bất kỳ model nào.**

> `case_count_day` và `case_count_h*` chỉ là số lượt được ghi nhận trong dữ liệu bệnh viện; không phải xác suất mắc bệnh trong cộng đồng và không phải chẩn đoán cá nhân.

## Nguồn thực tế

- Bệnh viện gốc: `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\seasonal_disease_backend\Tool\weather\train_history.xlsx`
- Weather gốc: `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\seasonal_disease_backend\Tool\weather\open-meteo-10.79N106.63E6m.csv`
- Bản raw V3 dùng để xử lý: `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\weather_disease_ai_v3\data\raw\train_history.xlsx` và `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\weather_disease_ai_v3\data\raw\weather_hcm_history.csv`.
- SHA-256 bệnh viện/weather: `ae148fdadbcc901a3ade4bff9281bc856f34fc24906fa0c561a2cb09a3f28c78` / `d40d4931966e89778a959598ec5b4ecb701f8f67b0ae3356d89c6c164797ae82`.

## Phạm vi nguồn

- Ngày bệnh: 2021-01-01 → 2025-04-26.
- Ngày weather: 2021-01-01 → 2025-04-30 (1,581 ngày liên tục).
- Age groups (6): 1-5 tuổi, 11-15 tuổi, 6-10 tuổi, Dưới 1 tuổi, Không rõ, Trên 15 tuổi.
- Gender: Nam, Nữ.
- Catalog candidate: 311; đã xuất hiện trong toàn nguồn bệnh nhân: 235; chưa từng xuất hiện: 76.
- Cột raw `month` được hiểu là tuổi theo tháng, chỉ dùng fallback khi thiếu ngày sinh; calendar month được tạo lại từ `anchor_date`.

## Context và target sparse

- Anchor: 2021-01-07 → 2025-04-13 (1,558 ngày).
- Tổ hợp age_group + gender: 12.
- Query contexts: 18,696.
- Sparse target rows (positive union H14): 673,691.

| Horizon | Total candidate pairs | Positive pairs | Positive rate |
|---|---:|---:|---:|
| H3 | 5,814,456 | 306,800 | 5.276504% |
| H7 | 5,814,456 | 492,033 | 8.462236% |
| H14 | 5,814,456 | 673,691 | 11.586484% |

- Nếu expand đầy đủ: 5,814,456 rows cho toàn anchor hợp lệ; 4,000,704 rows cho TRAIN.
- Ước lượng payload dense tối thiểu ở 40 bytes/pair: 221.8 MiB (chưa gồm overhead chuỗi/CSV).
- File sparse không được dùng làm mẫu số positive rate; mẫu số luôn là query × 311 candidate.

## Support theo TRAIN

Support dùng tổng `case_count_h*` trên các TRAIN query. Do target window overlap giữa các anchor liên tiếp, cùng một lượt bệnh viện có thể đóng góp cho nhiều query; validation/test không tham gia quyết định tier.

| Horizon | High | Medium | Low | Insufficient | Unsupported |
|---|---:|---:|---:|---:|---:|
| H3 | 65 | 43 | 70 | 43 | 90 |
| H7 | 85 | 57 | 56 | 23 | 90 |
| H14 | 104 | 55 | 44 | 18 | 90 |

## Temporal split và purge

- train: 2021-01-07 → 2023-12-14; 1,072 anchor; 12,864 query.
- validation: 2023-12-28 → 2024-08-12; 229 anchor; 2,748 query.
- test: 2024-08-26 → 2025-04-13; 231 anchor; 2,772 query.
- purge_train_validation: 2023-12-15 → 2023-12-27 (13 ngày bị loại).
- purge_validation_test: 2024-08-13 → 2024-08-25 (13 ngày bị loại).

Purge gap = 13 ngày anchor giữa các split. Vì H14 dùng D..D+13, target window cuối split trước kết thúc trước anchor đầu split sau.

## Leakage và invariant

- PASS — `no_duplicate_query_id`
- PASS — `no_duplicate_target_key`
- PASS — `weather_current_is_d_only`
- PASS — `weather_3d_is_d_minus_2_to_d`
- PASS — `weather_7d_is_d_minus_6_to_d`
- PASS — `no_future_weather`
- PASS — `h3_is_d_to_d_plus_2`
- PASS — `h7_is_d_to_d_plus_6`
- PASS — `h14_is_d_to_d_plus_13`
- PASS — `h3_le_h7_le_h14`
- PASS — `has_case_matches_case_count`
- PASS — `target_windows_within_source`
- PASS — `no_anchor_overlap`
- PASS — `no_target_window_overlap_between_splits`
- PASS — `disease_catalog_mapping_valid`
- PASS — `context_has_no_disease_target`
- PASS — `anchor_date_excluded_from_model_features`
- PASS — `year_excluded_from_model_features`
- PASS — `support_built_from_train_only`
- PASS — `baseline_contract_train_only`
- PASS — `same_weather_features_for_h3_h7_h14`

## Ba ví dụ ngày thật

### Ví dụ 1: Q20210107_C00

- Anchor D: **2021-01-07**; age_group: **1-5 tuổi**; gender: **Nam**.
- Weather current: 2021-01-07.
- Weather 3d: 2021-01-05 -> 2021-01-07.
- Weather 7d: 2021-01-01 -> 2021-01-07.
- H3: 2021-01-07 -> 2021-01-09.
- H7: 2021-01-07 -> 2021-01-13.
- H14: 2021-01-07 -> 2021-01-20.
- Weather thực tế: `temperature_mean_current`=28.671, `humidity_mean_current`=61.250, `precipitation_sum_3d`=4.000, `wind_speed_mean_7d`=7.670.
- Positive H3: 169 — Các bệnh viêm phổi - Pneumonia (5); 170 — Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis (2); 182 — Bệnh khác của khoang miệng, tuyến nước bọt và hàm - Other diseases of the oral cavity, salivary glands and jaws (1); 185 — Bệnh khác của thực quản, dạ dày và tá tràng - Other diseases of oesophagus, stomach, duodenum (1); 204 — Bệnh của hệ thống tổ chức liên kết - Systematic connective tissue disorders (1); 41 — Bệnh virut khác - Other viral diseases (1).
- Positive H7: 169 — Các bệnh viêm phổi - Pneumonia (12); 170 — Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis (5); 165 — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis (4); 197 — Bệnh khác của bộ máy tiêu hoá - Other diseases of the digestive system (4); 41 — Bệnh virut khác - Other viral diseases (3); 176 — Hen - Asthma (2); 32 — Sốt virut khác do tiết túc truyền và sốt virus xuất huyết - Other arthropod (2); 182 — Bệnh khác của khoang miệng, tuyến nước bọt và hàm - Other diseases of the oral cavity, salivary glands and jaws (1); … tổng 11 nhóm.
- Positive H14: 169 — Các bệnh viêm phổi - Pneumonia (19); 170 — Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis (8); 41 — Bệnh virut khác - Other viral diseases (5); 165 — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis (4); 197 — Bệnh khác của bộ máy tiêu hoá - Other diseases of the digestive system (4); 176 — Hen - Asthma (3); 32 — Sốt virut khác do tiết túc truyền và sốt virus xuất huyết - Other arthropod (3); 6 — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases (3); … tổng 14 nhóm.

### Ví dụ 2: Q20230412_C04

- Anchor D: **2023-04-12**; age_group: **6-10 tuổi**; gender: **Nam**.
- Weather current: 2023-04-12.
- Weather 3d: 2023-04-10 -> 2023-04-12.
- Weather 7d: 2023-04-06 -> 2023-04-12.
- H3: 2023-04-12 -> 2023-04-14.
- H7: 2023-04-12 -> 2023-04-18.
- H14: 2023-04-12 -> 2023-04-25.
- Weather thực tế: `temperature_mean_current`=29.496, `humidity_mean_current`=74.625, `precipitation_sum_3d`=9.500, `wind_speed_mean_7d`=10.289.
- Positive H3: 169 — Các bệnh viêm phổi - Pneumonia (8); 165 — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis (4); 173 — Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids (4); 6 — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases (4); 253 — Tổn thương khác có nguồn gốc trong thời kỳ chu sinh - Other conditions originating in the perinatal period (3); 99 — Tổn thương chảy máu, bệnh khác của máu và cơ quan tạo máu - Haemorrhagic conditions and other diseases of blood, blood (3); 176 — Hen - Asthma (2); 184 — Viêm dạ dày và tá tràng - Gastritis and duodenitis (2); … tổng 37 nhóm.
- Positive H7: 169 — Các bệnh viêm phổi - Pneumonia (15); 87 — Bệnh bạch cầu - Leukaemia (13); 173 — Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids (10); 165 — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis (9); 186 — Bệnh của ruột thừa - Diseases of appendix (9); 259 — Dị tật bẩm sinh khác của bộ máy sinh dục tiết niệu - Other malformations of the genitourinary system (8); 176 — Hen - Asthma (5); 282 — Hậu quả do dị vật vào hốc tự nhiên - Effects of foreign body entert hrough natural orifice (5); … tổng 54 nhóm.
- Positive H14: 169 — Các bệnh viêm phổi - Pneumonia (31); 165 — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis (23); 87 — Bệnh bạch cầu - Leukaemia (22); 173 — Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids (18); 259 — Dị tật bẩm sinh khác của bộ máy sinh dục tiết niệu - Other malformations of the genitourinary system (17); 186 — Bệnh của ruột thừa - Diseases of appendix (14); 176 — Hen - Asthma (10); 274 — Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones (10); … tổng 71 nhóm.

### Ví dụ 3: Q20250413_C11

- Anchor D: **2025-04-13**; age_group: **Trên 15 tuổi**; gender: **Nữ**.
- Weather current: 2025-04-13.
- Weather 3d: 2025-04-11 -> 2025-04-13.
- Weather 7d: 2025-04-07 -> 2025-04-13.
- H3: 2025-04-13 -> 2025-04-15.
- H7: 2025-04-13 -> 2025-04-19.
- H14: 2025-04-13 -> 2025-04-26.
- Weather thực tế: `temperature_mean_current`=30.133, `humidity_mean_current`=70.500, `precipitation_sum_3d`=3.100, `wind_speed_mean_7d`=8.588.
- Positive H3: 186 — Bệnh của ruột thừa - Diseases of appendix (1); 214 — Suy thận - Renal failure (1); 270 — Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified (1); 6 — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases (1); 96 — U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour (1).
- Positive H7: 186 — Bệnh của ruột thừa - Diseases of appendix (1); 192 — Bệnh khác của ruột non và màng bụng - Other diseases of intestine peritoneum (1); 214 — Suy thận - Renal failure (1); 270 — Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified (1); 6 — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases (1); 96 — U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour (1).
- Positive H14: 270 — Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified (3); 6 — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases (2); 186 — Bệnh của ruột thừa - Diseases of appendix (1); 192 — Bệnh khác của ruột non và màng bụng - Other diseases of intestine peritoneum (1); 200 — Viêm khớp dạng thấp và viêm khớp khác - Rheumatoid arthritis, other inflamatory polyarthropaties (1); 214 — Suy thận - Renal failure (1); 96 — U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour (1).

## Artifact

- `data/processed/daily_cases.csv.gz`
- `data/processed/contexts.csv.gz`
- `data/processed/targets.csv.gz`
- `data/processed/disease_catalog.csv`
- `data/processed/dataset_metadata.json`
- `data/splits/train_query_ids.csv`
- `data/splits/validation_query_ids.csv`
- `data/splits/test_query_ids.csv`
- `data/splits/split_metadata.json`

Không có CatBoost/LightGBM/XGBoost/neural network/SHAP nào được chạy trong giai đoạn này.
