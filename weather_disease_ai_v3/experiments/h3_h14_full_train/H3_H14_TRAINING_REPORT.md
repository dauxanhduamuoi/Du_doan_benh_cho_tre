# H3 and H14 Full-Train Report

> Full TRAIN cho H3/H14; chọn iteration bằng VALIDATION. H7 chỉ là reference và TEST chưa được sử dụng.

## DATA

- TRAIN: 12864 queries, 2021-01-07 → 2023-12-14.
- VALIDATION: 2748 queries, 2023-12-28 → 2024-08-12.
- Cùng disease universe tính từ TRAIN cho H3/H7/H14: 221.
- Feature count WITH/NO: 45 / 6.
- LIGHT_A giữ nguyên H7: MultiLogloss, GPU, 300 max iterations, depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, seed=42, gpu_ram_part=0.85, od_wait=30.

## H3

- Target: `has_case_h3`; TRAIN/VALIDATION matrix: `12864x221` / `2748x221`.
- Positive diseases/query VALIDATION: mean=20.724, median=24.000, zero-positive=470.
- Metrics average trên 2278 query có positive, đúng logic H7.

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.7276 | 0.7167 | 0.7187 | 0.010887 | 0.008867 |
| Recall@5 | 0.1587 | 0.1564 | 0.1572 | 0.002315 | 0.001543 |
| NDCG@5 | 0.7364 | 0.7217 | 0.7245 | 0.014707 | 0.011904 |
| Precision@10 | 0.6813 | 0.6808 | 0.6696 | 0.000571 | 0.011721 |
| Recall@10 | 0.2899 | 0.2905 | 0.2856 | -0.000628 | 0.004304 |
| NDCG@10 | 0.7168 | 0.7122 | 0.7049 | 0.004618 | 0.011914 |

| Resource | WITH WEATHER | NO WEATHER |
|---|---:|---:|
| Best iteration (1-based) | 18 | 15 |
| Final/model tree count | 18 | 15 |
| Train time (s) | 22.394 | 16.327 |
| Prediction time (s) | 0.013 | 0.020 |
| Memory before (MiB) | 0.0 | 0.0 |
| Peak total VRAM (MiB) | 6086.0 | 6086.0 |
| Peak delta VRAM (MiB) | 6086.0 | 6086.0 |
| Mean GPU utilization (%) | 60.9 | 75.7 |
| Model size (bytes) | 529192 | 441520 |

**H3_WEATHER_PROMISING** — Weather NDCG gain đạt ngưỡng thực dụng và không suy giảm nghiêm trọng metric khác.

Baseline H3 dùng hierarchy TRAIN-only `age_group + gender + month → age_group + month → month → global` và `case_count_h3` làm tần suất prior; target model vẫn là binary `has_case_h3`.

## H14

- Target: `has_case_h14`; TRAIN/VALIDATION matrix: `12864x221` / `2748x221`.
- Positive diseases/query VALIDATION: mean=43.683, median=54.000, zero-positive=444.
- Metrics average trên 2304 query có positive, đúng logic H7.

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.8806 | 0.8824 | 0.8696 | -0.001736 | 0.011024 |
| Recall@5 | 0.1033 | 0.1039 | 0.1049 | -0.000540 | -0.001605 |
| NDCG@5 | 0.8833 | 0.8856 | 0.8684 | -0.002297 | 0.014947 |
| Precision@10 | 0.8638 | 0.8715 | 0.8466 | -0.007726 | 0.017188 |
| Recall@10 | 0.1924 | 0.1976 | 0.1900 | -0.005230 | 0.002386 |
| NDCG@10 | 0.8724 | 0.8784 | 0.8560 | -0.005998 | 0.016400 |

| Resource | WITH WEATHER | NO WEATHER |
|---|---:|---:|
| Best iteration (1-based) | 13 | 16 |
| Final/model tree count | 13 | 16 |
| Train time (s) | 16.412 | 17.048 |
| Prediction time (s) | 0.014 | 0.019 |
| Memory before (MiB) | 0.0 | 0.0 |
| Peak total VRAM (MiB) | 6086.0 | 6086.0 |
| Peak delta VRAM (MiB) | 6086.0 | 6086.0 |
| Mean GPU utilization (%) | 74.3 | 75.0 |
| Model size (bytes) | 386496 | 470024 |

**H14_MODEL_GOOD_BUT_WEATHER_WEAK** — Model cạnh tranh baseline nhưng weather gain chưa đạt ngưỡng thực dụng.

Baseline H14 dùng hierarchy TRAIN-only `age_group + gender + month → age_group + month → month → global` và `case_count_h14` làm tần suất prior; target model vẫn là binary `has_case_h14`.

## Diễn giải và integrity

Weather delta chỉ thể hiện tín hiệu dự báo thống kê, không chứng minh quan hệ nhân quả.

Model xếp hạng các nhóm bệnh dựa trên mẫu hình thống kê trong dữ liệu bệnh viện và thời tiết lịch sử. Không phải chẩn đoán cá nhân.

- Raw/processed/split và toàn bộ H7 checksum: **PASS**.
- TEST không được parse, predict, tính metric hay dùng chọn horizon; chỉ checksum file được đối chiếu.
- H7 không retrain; không model chính thức, SHAP, tuning, API, frontend/backend.
- Mọi artifact mới chỉ nằm trong `experiments/h3_h14_full_train/`.
