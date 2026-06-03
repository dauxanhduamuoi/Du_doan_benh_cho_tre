# Seasonal Disease Backend

Backend FastAPI cho hệ thống phân tích dữ liệu bệnh nhi theo mùa vụ.

## Cách chạy

```bash
cd seasonal_disease_backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/create_admin.py
python -m uvicorn app.main:app --reload --port 8000
```

Mở Swagger:

```text
http://127.0.0.1:8000/docs
```

Tạo tài khoản admin bằng `create_admin.py`. Script sẽ hỏi mật khẩu hoặc có thể truyền qua biến môi trường:

```bash
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="mat_khau_manh"
python scripts/create_admin.py
```

## Luồng làm việc

1. Đăng nhập `/api/auth/login`.
2. Import file train history `/api/import/train-history`.
3. Import file predict current `/api/import/predict-current`.
4. Xem dashboard `/api/dashboard/overview`.
5. Chạy dự báo `/api/forecast/run`.
6. Phụ huynh xem cảnh báo public `/api/public/current-risks`.

## Ghi chú

- Bản này dùng SQLite cho dễ chạy demo.
- Dữ liệu import được lưu trong `database.db`.
- File model `.pkl` nên đặt trong `app/ml/seasonal_disease_forecast_model.pkl`.
- Nếu chưa có model, API forecast sẽ báo lỗi rõ ràng.
