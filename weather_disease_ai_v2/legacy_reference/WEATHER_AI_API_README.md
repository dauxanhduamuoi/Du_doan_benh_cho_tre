# Weather AI API

Chức năng này dự đoán **top nhóm bệnh có nguy cơ ghi nhận ca cao theo thời tiết hiện tại**.

Đây là cảnh báo thống kê, không phải chẩn đoán y tế.

## API đã thêm

### 1. Kiểm tra model

```http
GET /api/weather-ai/status
```

### 2. Lấy options cho frontend

```http
GET /api/weather-ai/options
```

Trả về:
- age_groups
- genders
- disease_catalog

### 3. Dự đoán nguy cơ theo thời tiết

```http
POST /api/weather-ai/predict-risk
```

Body đơn giản nhất:

```json
{
  "age_group": "1-5 tuổi",
  "gender": "Nam",
  "top_k": 5
}
```

Nếu không gửi `weather`, backend tự lấy weather realtime từ Open-Meteo.

Body test không cần internet:

```json
{
  "age_group": "1-5 tuổi",
  "gender": "Nam",
  "top_k": 5,
  "weather": {
    "temperature": 29.5,
    "humidity": 80,
    "rain": 5,
    "weather_code": 61,
    "wind_speed": 12,
    "wind_gusts": 25
  }
}
```

## Model file

Model nằm ở:

```text
app/ml/weather_ai_risk_model.joblib
```

Muốn train lại:

```bash
python scripts/train_weather_ai_model.py
```

## Logic model

Input:
- age_group
- gender
- disease_group_id
- report_group_code
- month
- season
- weather today
- rolling weather 3 ngày
- rolling weather 7 ngày

Output:
- probability: xác suất tổ hợp này có ca
- predicted_cases: số ca dự đoán
- risk_score: điểm xếp hạng nguy cơ
- risk_level: Cao / Trung bình / Thấp


## Lưu ý khi test Swagger

Swagger có thể tự tạo body mẫu sai kiểu:

```json
{
  "age_group": "string",
  "gender": "string",
  "weather": {}
}
```

Không dùng body đó.

Dùng realtime weather:

```json
{
  "age_group": "1-5 tuổi",
  "gender": "Nam",
  "top_k": 5
}
```

Test thủ công không cần internet:

```json
{
  "age_group": "1-5 tuổi",
  "gender": "Nam",
  "top_k": 5,
  "weather": {
    "temperature": 29.5,
    "humidity": 80,
    "rain": 5,
    "weather_code": 61,
    "wind_speed": 12,
    "wind_gusts": 25
  }
}
```

Gọi danh sách giá trị hợp lệ cho frontend:

```http
GET /api/weather-ai/options
```
