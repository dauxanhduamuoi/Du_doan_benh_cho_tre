# CatBoost Multi-label Lightweight Benchmark

Đây là benchmark tạm.
Xóa toàn bộ thư mục benchmarks/multilabel_lightweight/
không ảnh hưởng raw data, processed data hoặc model chính thức.

Benchmark chỉ dùng H7, đúng TRAIN/VALIDATION query sample của benchmark trước và disease universe được tính lại từ TRAIN. TEST không được đọc để train, chọn cấu hình hoặc tính metric.

Ba run tối đa:

- `LIGHT_A`: depth 4, có weather;
- `LIGHT_B`: depth 5, có weather;
- `BEST_LIGHT_NO_WEATHER`: cùng hyperparameter với cấu hình tốt nhất, bỏ toàn bộ weather feature.

Mỗi run dùng GPU process riêng, smoke test 10 iterations trước 100 iterations, không CPU fallback. Không chạy Ranker, SHAP, tuning lớn hoặc full train H3/H7/H14.

Chạy từ thư mục `weather_disease_ai_v3`:

```bash
python benchmarks/multilabel_lightweight/benchmark_lightweight.py
```
