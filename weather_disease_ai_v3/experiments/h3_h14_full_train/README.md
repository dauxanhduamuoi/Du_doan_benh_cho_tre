# H3 and H14 Full-Train Experiment

Experiment này chỉ train H3 và H14 trên TRAIN,
đánh giá bằng VALIDATION.
TEST chưa được sử dụng.
Có thể xóa toàn bộ `experiments/h3_h14_full_train/`
mà không ảnh hưởng raw/processed data hoặc H7 experiment.

## Phạm vi

- CatBoost multi-label `MultiLogloss`, LIGHT_A, GPU.
- H3 và H14 đều có WITH WEATHER, NO WEATHER và baseline TRAIN-only.
- Dùng full TRAIN/full VALIDATION; không sampling.
- H7 chỉ được đọc làm reference, không retrain hoặc ghi đè.
- Không TEST, SHAP, tuning, API, frontend hoặc backend.

Chạy từ `weather_disease_ai_v3`:

```bash
python experiments/h3_h14_full_train/train_h3_h14.py
```
