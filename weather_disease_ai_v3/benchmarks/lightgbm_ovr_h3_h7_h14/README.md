# LightGBM One-vs-Rest H3/H7/H14 Benchmark

Benchmark LightGBM One-vs-Rest trên TRAIN/VALIDATION.
Không sử dụng TEST.
Xóa thư mục benchmark này không ảnh hưởng dataset/model khác.

## Phạm vi

- Binary Relevance / One-vs-Rest cho H3, H7 và H14.
- Mỗi horizon có WITH WEATHER, NO WEATHER và baseline TRAIN-only.
- Chỉ TRAIN/VALIDATION; không đọc TEST hay CatBoost TEST result.
- Không retrain CatBoost, tuning, SHAP, backend hoặc frontend.
- LightGBM runtime được cài cô lập trong `artifacts/runtime_deps/`.

Chạy từ `weather_disease_ai_v3`:

```bash
python benchmarks/lightgbm_ovr_h3_h7_h14/benchmark_lightgbm_ovr.py
```
