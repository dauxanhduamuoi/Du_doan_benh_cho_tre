# Seasonal Disease Forecast — Bệnh viện Nhi Đồng 2

Hệ thống phân tích + dự báo ca bệnh nhi theo mùa, tích hợp dữ liệu thời tiết.

## Stack

- **Backend**: FastAPI · SQLAlchemy · SQLite · scikit-learn (HistGradientBoosting).
- **Frontend**: React 18 · Vite · TypeScript · Tailwind CSS · Recharts.

## Cấu trúc

```
src/
├── seasonal_disease_backend/   # FastAPI backend
│   ├── app/
│   │   ├── routers/            # auth, admin, dashboard, forecast, reports, import_data
│   │   ├── services/           # forecast_service (mùa vụ), forecast_weather_service
│   │   ├── models.py           # SQLAlchemy models
│   │   └── ml/                 # *.pkl (gitignored)
│   ├── scripts/                # Tools: import, retrain, migrate
│   └── database.db             # SQLite (gitignored)
├── Frontend/                   # React UI
│   └── src/
│       └── app/components/     # DashboardOverview, Forecast, Settings, Account...
└── data/                       # Excel data nguồn (gitignored, chứa PII)
```

## Chạy local

### Backend

```powershell
cd seasonal_disease_backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 1. Tạo admin mặc định (admin / admin123)
python scripts/create_admin.py

# 2. Migrate sessions + login tracking (idempotent)
python scripts/migrate_user_sessions.py

# 3. Chạy server
python -m uvicorn app.main:app --reload --port 8000
```

Swagger: http://127.0.0.1:8000/docs

### Frontend

```powershell
cd Frontend
npm install
npm run dev
```

Mở http://localhost:5173.

## Luồng làm việc

1. Đăng nhập (`admin / admin123`).
2. Tab **Tổng quan**: import file `train_history.xlsx` (1 file duy nhất là đủ).
3. (Tuỳ chọn) Import file `thoitietTPHCM.xlsx` để bật mô hình tích hợp thời tiết.
4. Tab **Dự báo**: chọn mô hình (Mùa vụ / Thời tiết) → bấm **Chạy dự báo**.
5. Tab **Báo cáo**: xuất CSV/PDF theo các filter.

## Mô hình

- **Mùa vụ** (`/api/forecast/run`): HistGradientBoosting + lag features (lag_1..5,
  rolling_3/5, change_1) + month sin/cos. Recursive forecast multi-step (output
  của tháng t-1 dùng làm lag cho tháng t).
- **Thời tiết** (`/api/forecast/run-weather`): chạy mùa vụ làm baseline rồi
  điều chỉnh ±30% theo correlation lịch sử giữa số ca và (rain_total,
  temp_mean, humidity_mean).

## Notes

- Dữ liệu bệnh nhân + DB không được commit (xem `.gitignore`).
- Tài khoản và session được lưu trong `users` + `login_sessions` của SQLite.
- Để re-train model mùa vụ: chạy notebook trong `seasonal_disease_backend/notebooks/`
  rồi copy file `.pkl` vào `app/ml/`.
