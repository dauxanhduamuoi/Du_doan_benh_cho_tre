# Data Audit

Báo cáo chỉ chứa thống kê tổng hợp; không chứa ngày sinh, địa chỉ hoặc thông tin nhận dạng cá nhân.

## Bệnh nhi và ánh xạ ICD

- Số lượt ban đầu: 257,771
- Khoảng ngày khám: 2021-01-01 đến 2025-04-26
- Số mã ICD chính duy nhất: 3,206
- Số nhóm bệnh đã ánh xạ: 235
- Lượt ánh xạ thành công: 257,769/257,771 (99.9992%)
- Lượt không ánh xạ: 2
- Dòng trùng hoàn toàn trong sheet bệnh nhân: 73

### Thiếu dữ liệu trong các trường nguồn cần dùng

- `icdNV`: 0
- `icdxuatvien`: 0
- `check_in_date`: 0
- `date_of_birth`: 3
- `month`: 3
- `gender`: 0

### Phân bố giới tính

- Nam: 153,695
- Nữ: 104,074

### Phân bố nhóm tuổi

- 1-5 tuổi: 113,757
- 11-15 tuổi: 29,767
- 6-10 tuổi: 53,347
- Dưới 1 tuổi: 57,237
- Không rõ: 10
- Trên 15 tuổi: 3,651

## Hỗ trợ theo nhóm bệnh

- Tổng nhóm trong dữ liệu ca thật: 236
- `under_20`: 70 nhóm
- `under_50`: 96 nhóm
- `under_100`: 123 nhóm
- `under_200`: 141 nhóm

## Thời tiết

- Khoảng ngày: 2021-01-01 đến 2025-04-30
- Số ngày: 1,581
- Ngày khám không có thời tiết tương ứng: 0
- Timestamp trùng: 0

### Cột thực tế

- `time`
- `temperature_2m (°C)`
- `relative_humidity_2m (%)`
- `precipitation (mm)`
- `rain (mm)`
- `weather_code (wmo code)`
- `wind_speed_10m (km/h)`
- `wind_gusts_10m (km/h)`

### Thiếu dữ liệu thời tiết

- `temperature_2m`: 0
- `relative_humidity_2m`: 0
- `precipitation`: 0
- `rain`: 0
- `weather_code`: 0
- `wind_speed_10m`: 0
- `wind_gusts_10m`: 0
