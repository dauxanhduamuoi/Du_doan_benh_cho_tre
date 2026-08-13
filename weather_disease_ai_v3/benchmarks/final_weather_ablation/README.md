# Final Weather Ablation Benchmark

Đây là benchmark tạm để kiểm tra weather contribution
và GPU memory trước full train.
Có thể xóa toàn bộ thư mục này mà không ảnh hưởng dataset/model chính.

Benchmark cố định CatBoost Multi-label `MultiLogloss`, cấu hình LIGHT_A và H7. WITH_WEATHER/NO_WEATHER dùng đúng sample cũ nhưng chạy trong hai Python/CUDA process riêng. Nếu WITH_WEATHER thành công, một process thứ ba chỉ chạy đúng 10 iterations trên toàn bộ TRAIN để kiểm tra GPU memory; đây không phải full training.

TEST không được load trong script. Không có Ranker, SHAP, tuning, H3/H14 hoặc model chính thức.

Chạy từ `weather_disease_ai_v3`:

```bash
python benchmarks/final_weather_ablation/final_ablation.py
```
