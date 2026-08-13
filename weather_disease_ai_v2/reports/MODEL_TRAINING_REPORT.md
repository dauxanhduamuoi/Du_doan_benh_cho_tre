# Model Training Report

Giai đoạn này chỉ huấn luyện và đánh giá offline; không thay đổi backend, API hoặc frontend.

> Điểm xếp hạng các nhóm bệnh thường được ghi nhận trong những trường hợp có tuổi, giới tính và điều kiện thời tiết tương tự.

Kết quả không phải xác suất chắc chắn trẻ mắc bệnh và không phải chẩn đoán y khoa.

## Môi trường GPU

- CatBoost: `1.2.10`.
- GPU CatBoost nhận diện: `1`; cấu hình bắt buộc `task_type=GPU`, `devices=0`.
- `nvidia-smi`: `0, NVIDIA GeForce RTX 5060 Laptop GPU, 592.01, 8151 MiB, 7899 MiB`.
- GPU smoke test đã chạy thành công trước mọi experiment; pipeline không có nhánh fallback CPU.

## Dữ liệu

| Tập | Dòng | Tổng case_count | Khoảng ngày |
|---|---:|---:|---|
| Train | 92,742 | 162,247 | 2021-01-01 – 2024-01-20 |
| Validation | 28,452 | 48,173 | 2024-01-21 – 2024-09-06 |
| Test | 27,566 | 47,349 | 2024-09-07 – 2025-04-26 |

- Số lớp model học được: 221.
- Số lớp toàn catalog: 235.
- Lớp unsupported trong validation: 114, 15, 158, 16, 2, 280, 295, 298, 35, 61, 67.
- Lớp unsupported trong test: 15, 16, 2, 219, 294, 295, 35, 40, 61.
- Tổng hợp lớp unsupported: 114, 15, 158, 16, 2, 219, 280, 294, 295, 298, 35, 40, 61, 67.

Các lớp unsupported vẫn được tính trong metric toàn tập như các trường hợp model không thể xếp đúng. Chúng không được đưa vào `eval_set` early stopping vì CatBoost chưa học các nhãn này.

## Baseline tần suất trên validation

Baseline dùng lần lượt `age_group + gender + month`, `age_group + month`, `month`, rồi tần suất toàn train.

- Weighted Top-1/3/5/10: 13.2024% / 27.1957% / 37.2138% / 52.9446%.
- Weighted log loss: 4.427756.
- Weighted-sample Macro F1 / Weighted F1: 0.3520% / 4.8433%.
- Unweighted Top-5: 21.3799%.

## Bốn experiment CatBoost trên validation

| Experiment | Features | Best iteration | Time (s) | Weighted Top-5 | Weighted log loss | Unweighted Top-5 |
|---|---:|---:|---:|---:|---:|---:|
| current_only | 20 | 160 | 441.00 | 36.9834% | 3.800232 | 21.3236% |
| current_plus_3d | 33 | 170 | 465.00 | 37.3923% | 3.785195 | 21.6364% |
| current_plus_3d_7d | 46 | 183 | 4024.84 | 37.6352% | 3.779099 | 21.8860% |
| current_plus_3d_7d_14d | 59 | 158 | 444.35 | 37.3861% | 3.778244 | 21.7102% |

## Model được chọn

- Experiment: `current_plus_3d_7d` (46 features).
- Lý do: Selected only from full-validation metrics: maximize case-weighted Top-5; within 0.002 prefer lower case-weighted log loss; within 0.010 prefer fewer features/windows. No test prediction or test metric was used.
- Test không được dự đoán hoặc dùng trong quá trình chọn model.
- Validation weighted Top-5: 37.6352%.
- Validation weighted log loss: 3.779099.

## Đánh giá test một lần sau khi chọn

- Weighted Top-1/3/5/10: 14.7944% / 29.2044% / 38.6069% / 53.8005%.
- Weighted log loss: 4.681424.
- Weighted-sample Macro F1 / Weighted F1: 0.4024% / 6.4997%.
- Unweighted Top-1/3/5/10: 5.1041% / 14.2531% / 21.9546% / 36.7844%.
- Unweighted log loss: 5.175279.

## Nhóm bệnh tốt nhất và kém nhất

### Top 5 tốt nhất trong các lớp supported có mặt ở test

- `169` — Các bệnh viêm phổi - Pneumonia: Test Top-5 recall 96.81%, support 7,398 lượt.
- `165` — Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis: Test Top-5 recall 83.08%, support 2,518 lượt.
- `6` — Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases: Test Top-5 recall 74.25%, support 2,190 lượt.
- `87` — Bệnh bạch cầu - Leukaemia: Test Top-5 recall 73.94%, support 1,577 lượt.
- `170` — Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis: Test Top-5 recall 71.24%, support 2,775 lượt.

### Top 5 kém nhất trong các lớp supported có mặt ở test

- `270` — Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified: Test Top-5 recall 0.00%, support 1,132 lượt.
- `124` — Động kinh - Epilepsy: Test Top-5 recall 0.00%, support 754 lượt.
- `167` — Viêm cấp đường hô hấp trên khác - Other acute upper respiratory infections: Test Top-5 recall 0.00%, support 697 lượt.
- `199` — Bệnh khác của da và mô tế bào dưới da - Other diseases of skin and subcutaneous tissue: Test Top-5 recall 0.00%, support 628 lượt.
- `261` — Dị dạng bẩm sinh của bộ máy sinh dục tiết niệu - Congenital malformations of genital organs: Test Top-5 recall 0.00%, support 511 lượt.

## Hạn chế

- Dữ liệu mất cân bằng mạnh; model chính không bật cân bằng lớp theo yêu cầu, nên nhóm nhiều lượt có ảnh hưởng lớn hơn.
- Nhóm `low` và `insufficient` có recall biến động và không nên được diễn giải như độ tin cậy y khoa.
- Các lớp unsupported không thể được model dự đoán vì không có trong train.
- Đây là xếp hạng thống kê trên các ca đã ghi nhận, không đo quan hệ nhân quả giữa thời tiết và bệnh.
- Các cửa sổ đầu chuỗi có giá trị thiếu khi chưa đủ lịch sử; CatBoost xử lý trực tiếp giá trị số thiếu.

## File đã tạo hoặc chỉnh sửa

- `requirements.txt`
- `src/models/__init__.py`
- `src/models/common.py`
- `src/models/baseline.py`
- `src/models/metrics.py`
- `src/models/training.py`
- `src/models/evaluation.py`
- `scripts/04_train_model.py`
- `scripts/05_evaluate_model.py`
- `notebooks/01_train_weather_disease_catboost_v2.ipynb`
- `tests/test_gpu_pipeline_structure.py`
- `tests/test_model_artifacts.py`
- `models/weather_disease_catboost_v2.cbm`
- `models/model_metadata.json`
- `models/feature_schema.json`
- `models/class_mapping.json`
- `models/model_selection.json`
- `reports/metrics/baseline_metrics.json`
- `reports/metrics/experiment_comparison.csv`
- `reports/metrics/validation_metrics.json`
- `reports/metrics/test_metrics.json`
- `reports/metrics/per_class_metrics.csv`
- `reports/logs/training_gpu.log`
- `reports/MODEL_TRAINING_REPORT.md`

## Lệnh và test

```bash
python scripts/04_train_model.py
python scripts/05_evaluate_model.py
pytest
```

Các test artifact kiểm tra load model, số lớp output, tổng xác suất, ánh xạ Top-K, feature leakage, selection không dùng test và độ ổn định trước/sau serialization.

Project cũ, backend, API và frontend không bị chỉnh sửa.
