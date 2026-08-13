# H3 Final Test

Đây là FINAL TEST của H3 đã được chọn trước bằng VALIDATION.
Không có training/tuning trong thư mục này.

- Chỉ load hai model H3 đã khóa để predict TEST.
- Baseline H3 được rebuild từ TRAIN-only bằng hierarchy đã khóa.
- Không test H7/H14, không SHAP, không retrain và không tuning sau TEST.
- Mọi artifact mới của lần đánh giá này nằm trong `experiments/h3_final_test/`.

Chạy từ `weather_disease_ai_v3`:

```bash
python experiments/h3_final_test/evaluate_h3_test.py
```
