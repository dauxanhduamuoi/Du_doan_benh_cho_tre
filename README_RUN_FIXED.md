# Bản tích hợp Backend + Frontend

## Backend
```bash
cd seasonal_disease_backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Mặc định: http://127.0.0.1:8000

Tài khoản test:
- username: admin
- password: admin123

## Frontend
```bash
cd Frontend
npm install
npm run dev
```
Mặc định: http://127.0.0.1:5173

Frontend đã được nối với backend qua proxy Vite `/api -> http://127.0.0.1:8000`.

## API Weather AI mới
- `GET /api/weather-ai/status`
- `GET /api/weather-ai/options`
- `POST /api/weather-ai/predict-risk`

Frontend có tab mới: **AI thời tiết**.

## Lưu ý
- Màn hình Forecast cũ vẫn chạy dự báo tháng tiếp theo như trước.
- Dự đoán bệnh theo thời tiết nằm ở tab **AI thời tiết**, không phải chẩn đoán y tế.
