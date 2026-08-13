# CatBoost Multi-label Lightweight Benchmark — H7

> Benchmark tạm trên đúng sample cũ; không dùng TEST, không Ranker, không SHAP và không full train.

## Dữ liệu và cấu hình khóa

- CatBoost: `1.2.10`; GPU: `NVIDIA GeForce RTX 5060 Laptop GPU`.
- TRAIN/VALIDATION: **1,296 / 275 query**; disease tính lại từ TRAIN: **221**.
- WITH_WEATHER feature count: 45; NO_WEATHER: N/A; target: `1296x221`.
- `age_group`, `gender`, `season` dùng categorical native với `one_hot_max_size=20`, nên cardinality nhỏ được one-hot trực tiếp; `month` giữ numeric.
- Mỗi config chạy trong GPU process mới để giảm ảnh hưởng CUDA warm-cache giữa LIGHT_A/LIGHT_B.

## So sánh

| Metric | Old depth6 | LIGHT_A | LIGHT_B | BEST no-weather | Baseline |
|---|---:|---:|---:|---:|---:|
| Status | reference_not_rerun | success | success | N/A | reference_not_rerun |
| Train time 100 iter (s) | 649.942 | 108.382 | 188.102 | N/A | N/A |
| Prediction time (s) | 0.0069 | 0.0059 | 0.0046 | N/A | N/A |
| Peak total GPU memory (MiB) | 7818.0 | 7751.0 | 7861.0 | N/A | N/A |
| Precision@5 | 0.7859 | 0.8159 | 0.8194 | N/A | 0.7921 |
| Recall@5 | 0.1184 | 0.1219 | 0.1257 | N/A | 0.1274 |
| NDCG@5 | 0.7942 | 0.8280 | 0.8232 | N/A | 0.8038 |
| Precision@10 | 0.7661 | 0.7815 | 0.7762 | N/A | 0.7480 |
| Recall@10 | 0.2284 | 0.2319 | 0.2295 | N/A | 0.2248 |
| NDCG@10 | 0.7877 | 0.8103 | 0.8021 | N/A | 0.7819 |
| Model size | 10.87 MiB | 2.73 MiB | 5.45 MiB | N/A | N/A |

Old depth6 và Baseline chỉ là reference đọc từ benchmark trước, không chạy lại.

## Lựa chọn lightweight

- **BEST_LIGHT_CONFIG:** `LIGHT_A`.
- Speedup vs old: **6.00x**.
- VRAM saved vs old: **67.0 MiB** (dương là tiết kiệm).
- Lý do: chọn theo GPU/OOM, VRAM, thời gian, NDCG@5/NDCG@10 rồi Precision/Recall; LIGHT_A được ưu tiên nếu NDCG@5 nằm trong 0.005 của LIGHT_B và nhẹ hơn.

## Weather ablation

Không có ablation hợp lệ vì không chọn được BEST_LIGHT_CONFIG hoặc cấu hình tốt nhất vẫn vượt resource-warning gate 7,500 MiB; pipeline dừng theo yêu cầu an toàn.

## Đề xuất và estimate

- Đề xuất full train ngay: **KHÔNG**.
- Gate gồm GPU ổn định, peak total <7,500 MiB, speedup ≥1.5x, NDCG@5 không thấp hơn baseline quá 0.02 và weather cải thiện NDCG@5 hoặc NDCG@10.
- Full H3 estimate: 13.4–26.9 phút (center 17.9).
- Full H7 estimate: 13.4–26.9 phút (center 17.9).
- Full H14 estimate: 13.4–26.9 phút (center 17.9).
- Tổng H3+H7+H14 estimate: 40.3–80.7 phút (center 53.8).

Estimate ngoại suy từ khoảng 10% TRAIN, có thể phi tuyến và không phải cam kết thời gian/VRAM.

## Integrity

- Raw/processed/split/old sample checksum không đổi: **PASS**.
- TEST không được load trong script; audit cuối kiểm sample overlap TEST = 0.
- Tất cả model/log/result mới nằm trong `benchmarks/multilabel_lightweight/`.
- Không có model chính thức mới.

**CHƯA FULL TRAIN MODEL.**
