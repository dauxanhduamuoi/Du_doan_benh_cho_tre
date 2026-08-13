# Data Preparation Report

Pipeline này chỉ xử lý dữ liệu; không huấn luyện model và không tạo SHAP.

## Nguồn thực tế

- Bệnh nhân/ICD: `data/raw/train_history.xlsx`
- Thời tiết: `data/raw/weather_hcm_history.csv`

## Kết quả

- Lượt bệnh nhi ban đầu: 257,771
- Lượt ánh xạ thành công: 257,769
- Nhóm bệnh: 235
- Thời gian bệnh: 2021-01-01 đến 2025-04-26
- Thời gian thời tiết: 2021-01-01 đến 2025-04-30
- Dòng dataset cuối: 148,760
- Tổng `case_count`: 257,769
- Hỗ trợ high/medium/low/insufficient: 50/45/71/70

### Cột thời tiết thực tế

- `time`
- `temperature_2m (°C)`
- `relative_humidity_2m (%)`
- `precipitation (mm)`
- `rain (mm)`
- `weather_code (wmo code)`
- `wind_speed_10m (km/h)`
- `wind_gusts_10m (km/h)`

## Chia theo thời gian

- train: 2021-01-01 đến 2024-01-20 (1,075 ngày, 92,742 dòng)
- validation: 2024-01-21 đến 2024-09-06 (230 ngày, 28,452 dòng)
- test: 2024-09-07 đến 2025-04-26 (232 ngày, 27,566 dòng)

### Nhóm không được train hỗ trợ

- `114`
- `15`
- `158`
- `16`
- `2`
- `219`
- `280`
- `294`
- `295`
- `298`
- `35`
- `40`
- `61`
- `67`

## Dữ liệu thiếu hoặc vấn đề còn lại

- 2 lượt có ICD không ánh xạ được.
- 0 ngày khám không có dữ liệu thời tiết.
- Thiếu nguồn bệnh nhân: {'date_of_birth': 3, 'month': 3}.
- Thiếu nguồn thời tiết: không có.
- Các giá trị thiếu của cửa sổ 3/7/14 ngày chỉ nằm ở đầu chuỗi, trước khi đủ lịch sử (1d=0 dòng, 3d=8 dòng, 7d=50 dòng, 14d=131 dòng); số thiếu bất thường sau khi đủ lịch sử đều bằng 0.

## File đã tạo/chỉnh sửa

- `README.md`
- `requirements.txt`
- `src/__init__.py`
- `src/data/__init__.py`
- `src/data/io.py`
- `src/data/patients.py`
- `src/data/audit.py`
- `src/data/dataset.py`
- `src/features/__init__.py`
- `src/features/weather.py`
- `scripts/02_audit_data.py`
- `scripts/03_build_dataset.py`
- `tests/conftest.py`
- `tests/test_data_pipeline.py`
- `tests/test_generated_artifacts.py`
- `reports/audit/*`
- `data/interim/positive_cases.csv.gz`
- `data/interim/weather_daily_features_v2.csv.gz`
- `data/processed/*`
- `data/splits/*`
- `reports/DATA_PREPARATION_REPORT.md`

## Lệnh và kiểm tra

```bash
python scripts/02_audit_data.py
python scripts/03_build_dataset.py
pytest
```

Kết quả xác minh khi bàn giao: audit thành công, build thành công, `12 passed`; 15 artifact sinh ra có SHA-256 giống hệt sau hai lần build liên tiếp.
