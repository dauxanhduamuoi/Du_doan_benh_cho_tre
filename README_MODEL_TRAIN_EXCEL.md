# Dữ liệu train đi kèm model dự báo tháng tiếp theo

Backend đã đổi sang quy ước đơn giản:

```text
seasonal_disease_backend/app/ml/
├── seasonal_disease_forecast_model.pkl
└── seasonal_forecast_data/
    └── train_history.xlsx
```

`train_history.xlsx` là file Excel đi kèm model, gồm 2 sheet:

```text
DS-BenhNhan
DS-MaBenh
```

Backend không import file này qua API và không lưu dữ liệu train của model vào database nữa.
Khi chạy dự báo, backend đọc trực tiếp file này, xử lý thành monthly statistics trong RAM rồi đưa vào model.

Nếu thay model mới:

1. Copy model mới vào:

```text
seasonal_disease_backend/app/ml/seasonal_disease_forecast_model.pkl
```

2. Copy file train tương ứng với model mới vào:

```text
seasonal_disease_backend/app/ml/seasonal_forecast_data/train_history.xlsx
```

3. Restart backend.

Có thể kiểm tra file train bằng API:

```http
GET /api/import/model-data/status
```

API này sẽ báo file có tồn tại không và có đủ sheet `DS-BenhNhan`, `DS-MaBenh` không.

Các bảng DB đã không còn cần cho dữ liệu model:

```text
model_disease_codes
model_metadata
weather_records
monthly_statistics data_type='train_history'
```

Backend hiện tại đã dọn code để không dùng các bảng đó nữa.
