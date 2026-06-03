# Import dữ liệu và dữ liệu train đi kèm model

## 1. Dữ liệu người dùng import qua giao diện

Frontend chỉ cần 2 loại import chính:

```text
Import DS-MaBenh (.xlsx)
Import DS-BenhNhan (.xlsx)
```

Quy trình đúng:

```text
1. Import DS-MaBenh trước
2. Kiểm tra danh sách mã bệnh đã import
3. Import DS-BenhNhan để phân tích/dashboard/forecast
4. Chạy dự báo
```

DS-MaBenh người dùng được lưu vào bảng:

```text
disease_codes
```

DS-BenhNhan người dùng được lưu vào:

```text
patient_records      data_type='predict_current'
monthly_statistics   data_type='predict_current'
```

## 2. Dữ liệu train của model dự báo tháng tiếp theo

Dữ liệu train của model không import qua API nữa.
Mỗi model forecast đi kèm đúng 1 file Excel:

```text
seasonal_disease_backend/app/ml/seasonal_forecast_data/train_history.xlsx
```

File này phải có 2 sheet:

```text
DS-BenhNhan
DS-MaBenh
```

Khi chạy forecast, backend đọc file `train_history.xlsx` này trực tiếp, xử lý trong RAM thành monthly statistics, rồi đưa vào model.

Nếu thay model mới:

```text
app/ml/seasonal_disease_forecast_model.pkl
app/ml/seasonal_forecast_data/train_history.xlsx
```

Sau đó restart backend.

## 3. Các bảng DB không còn dùng cho dữ liệu train model

Backend hiện tại không còn dùng:

```text
model_disease_codes
model_metadata
weather_records
monthly_statistics data_type='train_history'
```

Các bảng này đã được dọn khỏi code backend. Nếu trong DB cũ còn tồn tại, có thể drop sau khi đã backup.
