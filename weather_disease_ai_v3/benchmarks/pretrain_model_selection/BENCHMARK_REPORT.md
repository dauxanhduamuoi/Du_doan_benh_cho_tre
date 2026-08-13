# H7 Pre-train Model Selection Benchmark

> Đây là benchmark tạm 10% TRAIN/VALIDATION, 100 iterations trên H7. Không phải full train, không dùng TEST, không SHAP và không tạo model chính thức.

## Phạm vi khóa

- CatBoost: `1.2.10`; GPU: `NVIDIA GeForce RTX 5060 Laptop GPU`.
- Benchmark TRAIN: 1,296/12,864 query; VALIDATION: 275 query.
- TRAIN bắt đầu từ sample 10% deterministic và bổ sung 10 query để mọi model-supported H7 label có ít nhất một positive; cùng subset cuối được dùng cho cả hai algorithm.
- Model-supported disease từ toàn TRAIN, positive ở ít nhất một H3/H7/H14: **221**.
- Disease unsupported vẫn nằm trong catalog gốc; benchmark-local snapshot chỉ thêm cờ `model_supported`.
- Month là calendar month dạng numeric; categorical dùng `age_group`, `gender`, `season`; Ranker thêm `disease_group_id`.
- Baseline học prior từ đúng benchmark TRAIN subset để so sánh cùng lượng query, không dùng weather/VALIDATION/TEST.
- Validation metric tính trên 227 query có ít nhất một positive H7 trong disease universe; 48 query zero-positive được loại khỏi mean metric.

## Kết quả chung

| Metric | Multi-label | Ranker | Baseline |
|---|---:|---:|---:|
| Status | success | success | success |
| GPU smoke 10 iter | passed_gpu_save_load_predict | passed_gpu_save_load_predict | N/A |
| Feature/train rows | 1,296 | 286,416 | 1,296 |
| Expanded rows | 0 | 286,416 | 0 |
| Disease labels | 221 | 221 | 221 |
| Target shape | 1296x221 | 286416x1 | train-only hierarchical frequency |
| Train time 100 iter | 649.942 s | 2.410 s | N/A |
| Prediction time | 0.007 s | 0.005 s | 0.027 s |
| Peak VRAM delta | 6678.0 MiB | 6678.0 MiB | N/A |
| Peak total GPU memory observed | 7818.0 MiB | 7298.0 MiB | N/A |
| Mean GPU utilization observed | 85.9% | 57.0% | N/A |
| Precision@5 | 0.7859 | 0.6819 | 0.7921 |
| Recall@5 | 0.1184 | 0.1007 | 0.1274 |
| NDCG@5 | 0.7942 | 0.6857 | 0.8038 |
| Precision@10 | 0.7661 | 0.7040 | 0.7480 |
| Recall@10 | 0.2284 | 0.2031 | 0.2248 |
| NDCG@10 | 0.7877 | 0.7067 | 0.7819 |
| Model size | 10.87 MiB | 0.12 MiB | N/A |

`Peak VRAM delta` là chênh lệch giữa peak `nvidia-smi memory.used` và mức ngay trước phase train; `Peak total` và GPU utilization là số quan sát toàn GPU, nên có thể gồm tải nền khác.

Ranker chạy sau Multi-label đúng thứ tự yêu cầu trong cùng Python/CUDA process, nên thời gian Ranker có thể được lợi từ CUDA/kernel cache đã warm; không diễn giải 2 thời gian như cold-start tuyệt đối.

## GPU/API verification

Smoke test bắt buộc `task_type=GPU`, save/load artifact và predict. Nếu smoke thất bại, script không chạy 100 iterations cho algorithm đó và không fallback CPU.

## Khuyến nghị

**Recommended algorithm:** CatBoost Multi-label Classification (MultiLogloss) — hướng nghiên cứu có điều kiện, chưa phê duyệt full train

**Reason:** Multi-label cao hơn Ranker 0.1085 NDCG@5, giữ đúng một row/query và tránh expand 286,416 rows. Tuy nhiên, Multi-label chậm, dùng VRAM sát trần 8GB và chưa vượt baseline ở headline @5, nên chưa đủ điều kiện để full train. Baseline NDCG@5=0.8038; Multi-label=0.7942; Ranker=0.6857.

**Decision gate:** Không model nào vượt baseline ở cả ba headline metric @5. Multi-label chỉ có tín hiệu nhỉnh hơn baseline ở Precision@10/NDCG@10, còn Ranker kém baseline rõ. Vì vậy khuyến nghị trên chỉ chọn hướng nghiên cứu tốt hơn giữa A/B, không phải phê duyệt full train.

Multi-label bám sát target vector nhiều disease và có inference một row/query; Ranker bám trực tiếp objective xếp hạng nhưng phải expand query × disease. Khả năng SHAP của hướng được chọn vẫn phải được kiểm chứng ở bước riêng sau này; benchmark này không chạy SHAP.

Trên laptop RTX 5060 8GB, peak total quan sát 7,818 MiB của Multi-label chỉ còn rất ít headroom; full TRAIN có rủi ro OOM/không ổn định. Ranker nhẹ hơn về model và nhanh hơn trong run này nhưng full candidate rows tăng xấp xỉ 10× và metric H7 hiện chưa đạt baseline.

**Ước lượng full-train 1 horizon:** khoảng 80.6–161.3 phút (linear center 107.5 phút).

**Ước lượng H3+H7+H14:** khoảng 241.9–483.8 phút (3× linear center 322.6 phút).

Các khoảng trên chỉ ngoại suy tuyến tính từ benchmark 10%; startup GPU, dữ liệu lớn hơn và I/O có thể làm thời gian thực tế phi tuyến. Đây không phải cam kết thời gian.

## Integrity và phạm vi artifact

- Processed/split source checksum không đổi sau benchmark: **PASS**.
- TEST không được đọc hoặc dùng.
- Mọi query sample, support snapshot, model tạm và log nằm trong `benchmarks/pretrain_model_selection/`.
- Không có model nào được copy sang `models/`, `data/processed/`, `reports/` hoặc `src/`.

**CHƯA FULL TRAIN MODEL. Benchmark dừng sau 100 iterations H7.**
