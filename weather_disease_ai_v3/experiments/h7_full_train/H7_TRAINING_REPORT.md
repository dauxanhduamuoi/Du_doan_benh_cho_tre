# H7 Full-Train Stage 1 Report

> Chỉ train H7 trên TRAIN và đánh giá trên VALIDATION. TEST không được load vào pipeline.

## Dữ liệu

- TRAIN queries: 12864; date range: 2021-01-07 → 2023-12-14.
- VALIDATION queries: 2748; date range: 2023-12-28 → 2024-08-12.
- Disease supported tính lại từ TRAIN: 221.
- Target TRAIN/VALIDATION: `12864x221` / `2748x221`.
- Feature count WITH/NO: 45 / 6.
- Số disease positive/query trên VALIDATION: mean=32.575, median=40.000; zero-positive=451.
- Metric chỉ average trên 2297 query có ít nhất một positive, giống benchmark trước.

## Cấu hình cố định

- CatBoost `1.2.10`, `MultiLogloss`, GPU `NVIDIA GeForce RTX 5060 Laptop GPU`.
- LIGHT_A: depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, random_seed=42.
- iterations=300, use_best_model=true, od_type=Iter, od_wait=30, gpu_ram_part=0.85.
- CatBoost chấp nhận gpu_ram_part: WITH=True, NO=True.
- Categorical: age_group, gender, season; month là numeric.

## Kết quả VALIDATION

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.8179 | 0.8128 | 0.8154 | 0.005137 | 0.002525 |
| Recall@5 | 0.1224 | 0.1234 | 0.1252 | -0.001010 | -0.002821 |
| NDCG@5 | 0.8259 | 0.8233 | 0.8154 | 0.002596 | 0.010496 |
| Precision@10 | 0.8052 | 0.8043 | 0.7876 | 0.000914 | 0.017632 |
| Recall@10 | 0.2330 | 0.2335 | 0.2285 | -0.000467 | 0.004498 |
| NDCG@10 | 0.8247 | 0.8249 | 0.8067 | -0.000261 | 0.017916 |

Baseline dùng hierarchy `age_group + gender + month → age_group + month → month → global`, fit từ full TRAIN only và không dùng weather.

## Tài nguyên

| Resource | WITH WEATHER | NO WEATHER |
|---|---:|---:|
| Requested iterations | 300 | 300 |
| Best iteration (1-based) | 15 | 16 |
| Final/model tree count | 15 | 16 |
| Early stopped | True | True |
| Train time (s) | 37.893 | 36.811 |
| Prediction time (s) | 0.016 | 0.019 |
| Memory before (MiB) | 1027.0 | 1024.0 |
| Peak total VRAM (MiB) | 7114.0 | 7116.0 |
| Peak delta VRAM (MiB) | 6087.0 | 6092.0 |
| Mean GPU utilization (%) | 91.8 | 92.3 |
| Model size (bytes) | 443576 | 470040 |

WITH WEATHER và NO WEATHER chạy trong hai Python/CUDA process riêng. Không CPU fallback.

## Kết luận

**H7_MODEL_GOOD_BUT_WEATHER_WEAK** — Model cạnh tranh baseline nhưng weather gain chưa đạt ngưỡng thực dụng đã khóa.

Ngưỡng decision gate được khóa trước khi train: NDCG weather gain thực dụng ≥ 0.005; baseline tolerance 0.005; metric drop nghiêm trọng < -0.01.

Model xếp hạng các nhóm bệnh dựa trên mẫu hình thống kê trong dữ liệu bệnh viện và thời tiết lịch sử. Không phải chẩn đoán cá nhân và không chứng minh quan hệ nhân quả.

## Integrity

- Raw/processed/split checksum không đổi: **PASS**.
- TEST không được parse, load, train, predict hay tính metric; chỉ checksum file split được đối chiếu integrity.
- Không train H3/H14; không SHAP, tuning, API hay frontend/backend.
- Mọi artifact experiment mới chỉ nằm trong `experiments/h7_full_train/`.
