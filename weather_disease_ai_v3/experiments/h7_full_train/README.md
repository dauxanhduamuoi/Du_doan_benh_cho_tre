# H7 Full-Train Experiment

Đây là experiment full-train H7.
Xóa `experiments/h7_full_train/`
không ảnh hưởng raw/processed dataset V3.

## Phạm vi

- CatBoost multi-label `MultiLogloss`, cấu hình LIGHT_A.
- Chỉ horizon H7.
- Hai control chạy riêng: WITH WEATHER và NO WEATHER.
- Toàn bộ TRAIN dùng để fit; toàn bộ VALIDATION dùng cho early stopping và metric.
- Baseline phân cấp chỉ được fit từ TRAIN.
- TEST không được load, không tính metric và không tham gia chọn model.

## Chạy

Từ thư mục `weather_disease_ai_v3`:

```bash
python experiments/h7_full_train/train_h7.py
```

Mọi model, metric và log sinh ra bởi experiment này chỉ nằm trong thư mục hiện tại.
