# Final Weather Ablation Report — H7

> Benchmark cuối chỉ trả lời weather contribution và khả năng chạy full-TRAIN 10 iterations trên GPU. Không dùng TEST và chưa full train.

## Phạm vi cố định

- CatBoost `1.2.10`, GPU `NVIDIA GeForce RTX 5060 Laptop GPU`.
- LIGHT_A: depth=4, border_count=32, one_hot_max_size=20, learning_rate=0.1, MultiLogloss, GPU, `gpu_ram_part=0.85`.
- gpu_ram_part được CatBoost chấp nhận khi fit: WITH=True, NO=True.
- Sample TRAIN/VALIDATION: 1296/275; disease tính từ TRAIN: 221; target `1296x221`.
- Feature count WITH/NO: 45/6; hai run dùng process CUDA riêng.

## Weather ablation

| Metric | WITH WEATHER | NO WEATHER | Delta | Baseline |
|---|---:|---:|---:|---:|
| Precision@5 | 0.8159 | 0.8220 | -0.006167 | 0.7921 |
| Recall@5 | 0.1219 | 0.1286 | -0.006766 | 0.1274 |
| NDCG@5 | 0.8280 | 0.8304 | -0.002469 | 0.8038 |
| Precision@10 | 0.7815 | 0.7762 | 0.005286 | 0.7480 |
| Recall@10 | 0.2319 | 0.2265 | 0.005407 | 0.2248 |
| NDCG@10 | 0.8103 | 0.8056 | 0.004766 | 0.7819 |
| Train time (s) | 78.933 | 9.099 | N/A | N/A |
| Peak total VRAM (MiB) | 7153.000 | 7143.000 | N/A | N/A |
| Peak delta VRAM (MiB) | 6088.000 | 6085.000 | N/A | N/A |

**Diễn giải:** Weather contribution chưa rõ: delta nhỏ và trái chiều giữa các ranking cutoff. Đây là so sánh dự báo thống kê, không phải quan hệ nhân quả và không phải chẩn đoán.

## FULL TRAIN 10-ITER SMOKE

- query count: 12864
- disease count: 221
- target shape: 12864x221
- feature count: 45
- time: 6.453 giây
- memory before: 1062.0 MiB
- peak memory: 7155.0 MiB
- peak delta: 6093.0 MiB
- memory after process: 1066.0 MiB
- OOM: False
- PASS/FAIL: success

## Estimate từ full-data smoke

- 100 iterations: ≈ 1.1 phút
- 200 iterations: ≈ 2.2 phút
- 300 iterations: ≈ 3.2 phút

Estimate ngoại suy từ đúng full-TRAIN 10 iterations, có thể phi tuyến; không phải thời gian chắc chắn.

## Decision gate

**WEATHER_SIGNAL_UNCLEAR** — Weather delta nhỏ và trái chiều: NDCG@5 không cải thiện rõ dù NDCG@10 tăng nhẹ. Full-TRAIN GPU smoke vẫn PASS và không OOM, nhưng weather gate chưa đủ rõ để quyết định full train.

## Integrity

- Raw/processed/split/sample/reference checksum không đổi: **PASS**.
- TEST không được load trong script; audit ngoài training xác nhận sample không overlap TEST.
- Mọi model/log/result mới nằm trong `benchmarks/final_weather_ablation/`.
- Không có model chính thức mới.

**CHƯA FULL TRAIN MODEL.**
