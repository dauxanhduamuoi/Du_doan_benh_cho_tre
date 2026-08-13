# Pre-train model selection benchmark

Đây chỉ là benchmark tạm trước khi train.
Xóa toàn bộ thư mục này không ảnh hưởng raw data,
processed data hoặc model chính thức.

Benchmark chỉ dùng H7 và subset deterministic nằm riêng bên trong TRAIN/VALIDATION hiện có. TEST không được đọc hoặc sử dụng. Hai hướng được kiểm tra bằng GPU với cùng query, disease universe, feature thời tiết và 100 iterations:

- CatBoost multi-label classification với `MultiLogloss`;
- CatBoostRanker với `YetiRank` và candidate disease theo từng query.

Mỗi hướng phải vượt qua smoke test GPU 10 iterations, save/load và predict trước khi benchmark 100 iterations. Script không fallback sang CPU.

Chạy từ thư mục gốc `weather_disease_ai_v3`:

```bash
python benchmarks/pretrain_model_selection/benchmark_models.py
```

Mọi model, query sample, log và kết quả đều nằm trong thư mục này. Đây không phải full train H3/H7/H14 và không tạo model chính thức.
