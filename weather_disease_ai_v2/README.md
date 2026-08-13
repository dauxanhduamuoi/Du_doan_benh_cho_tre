# Weather Disease AI v2

Workspace độc lập để phát triển phiên bản mới của AI dự đoán nhóm bệnh theo thời tiết.

## Cấu trúc

```text
config/             Cấu hình dự án
data/raw/           Dữ liệu nguồn chính, giữ nguyên trạng
data/reference/     Kết quả cũ chỉ dùng để đối chiếu
data/interim/       Dữ liệu trung gian trong các giai đoạn sau
data/processed/     Dữ liệu đã xử lý trong các giai đoạn sau
data/splits/        Các tập train/validation/test trong các giai đoạn sau
src/                Mã nguồn data, features, models, explain và inference
scripts/            Script vận hành workspace
models/             Model sinh ra trong các giai đoạn sau
reports/            Audit, metrics, explanations và logs
tests/              Kiểm thử
legacy_reference/   Bản sao code và tài liệu cũ để tham khảo
```

Hai file dữ liệu nguồn chính là `data/raw/train_history.xlsx` và
`data/raw/weather_hcm_history.csv`. Các file trong `data/reference/` không phải dữ
liệu nguồn chính.

## Chuẩn bị workspace

Chạy từ thư mục `weather_disease_ai_v2`:

```bash
python scripts/prepare_workspace.py
```

Giai đoạn này chỉ chuẩn bị thư mục và sao chép dữ liệu nguyên trạng; chưa xử lý dữ
liệu và chưa huấn luyện mô hình.

## Chuẩn bị dataset V2

Kích hoạt môi trường Python đã cài các gói trong `requirements.txt`, rồi chạy:

```bash
python scripts/02_audit_data.py
python scripts/03_build_dataset.py
pytest
```

Pipeline V2 chỉ tạo audit, ca bệnh tổng hợp, đặc trưng thời tiết và các tập dữ liệu
chia theo thời gian. Pipeline không tạo mẫu âm ngẫu nhiên, không huấn luyện model,
không làm SHAP và không thay đổi backend/frontend.

## Huấn luyện CatBoost GPU

Notebook theo dõi từng bước nằm tại
`notebooks/01_train_weather_disease_catboost_v2.ipynb`. Mở bằng môi trường riêng:

```bash
python -m jupyter lab
```

Hoặc chạy cùng pipeline qua CLI:

```bash
python scripts/04_train_model.py
python scripts/05_evaluate_model.py
pytest
```

Pipeline bắt buộc dùng GPU `0`, chạy smoke test trước bốn experiment và không tự
fallback sang CPU. Log đang chạy được flush vào `reports/logs/training_gpu.log`.
