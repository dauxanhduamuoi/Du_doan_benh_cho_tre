# Weather Disease AI V3

Workspace độc lập để chuẩn bị dữ liệu cho bài toán **multi-label disease ranking / candidate scoring**.

Mục tiêu:

> Dựa trên tuổi, giới tính và điều kiện thời tiết hiện tại cùng 3/7 ngày nhìn về quá khứ, xếp hạng các nhóm bệnh đáng chú ý trong H3, H7 hoặc H14.

Đây không phải mô hình chẩn đoán cá nhân, không dự báo thời tiết và không diễn giải số lượt bệnh viện thành xác suất mắc bệnh trong cộng đồng.

## Quy ước

- Weather current: ngày `D`.
- Weather 3d: `D-2 .. D`.
- Weather 7d: `D-6 .. D`.
- H3: lượt ghi nhận `D .. D+2`.
- H7: lượt ghi nhận `D .. D+6`.
- H14: lượt ghi nhận `D .. D+13`.
- `anchor_date` chỉ là metadata/key; model feature sau này chỉ dùng `month`, `season`, `day_of_year_sin`, `day_of_year_cos`.
- Cột raw `month` của bệnh nhân là tuổi theo tháng và chỉ dùng làm fallback khi thiếu ngày sinh.

## Cấu trúc

- `data/raw/`: bản copy nguyên vẹn của Excel bệnh viện và CSV thời tiết.
- `data/processed/daily_cases.csv.gz`: lượt ghi nhận theo ngày/tuổi/giới/nhóm bệnh.
- `data/processed/contexts.csv.gz`: query context, không chứa target bệnh.
- `data/processed/targets.csv.gz`: positive target sparse cho H3/H7/H14.
- `data/processed/disease_catalog.csv`: catalog candidate và support TRAIN từng horizon.
- `data/splits/`: query ID split theo thời gian, có purge gap.
- `src/data_pipeline.py`: toàn bộ logic chuẩn bị dữ liệu và assertion.
- `src/baseline.py`: frequency-ranking baseline skeleton, chỉ fit bằng TRAIN.
- `src/metrics.py`: Recall@K, NDCG@K và MRR cho multi-label ranking.
- `notebooks/01_prepare_data.ipynb`: giao diện 12 bước gọi chung pipeline.

Do môi trường hiện tại không có `pyarrow`, artifact bảng được lưu dạng `csv.gz` thay cho Parquet.

## Chạy

Từ thư mục workspace:

```bash
python -m src.data_pipeline
pytest -q
jupyter lab notebooks/01_prepare_data.ipynb
```

Giai đoạn này chỉ chuẩn bị dữ liệu, baseline/metrics skeleton và kiểm tra leakage. **Chưa huấn luyện bất kỳ model nào.**
