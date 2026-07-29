# So sánh Decision Tree và Random Forest

## Dữ liệu
- Nguồn đọc: `D:\OS_C\Bài học trên trường\Thực tập\Fullstack_2\ThucTap-main\Train_5\results\train_monthly_statistics.csv`
- Số dòng dữ liệu tháng ban đầu: 48516
- Số dòng dùng để train/evaluate sau khi tạo lag: 47583
- Khoảng thời gian dữ liệu: 2021-02 đến 2025-04
- Tập train: 2021-02 đến 2024-05 (40 tháng)
- Tập test: 2024-06 đến 2025-04 (11 tháng)

## Kết quả so sánh
| Model | MAE | RMSE | R2 | Thời gian train eval (giây) |
|---|---:|---:|---:|---:|
| Random Forest | 2.2293 | 7.7975 | 0.923617 | 69.9000 |
| Decision Tree | 2.9306 | 10.6656 | 0.857092 | 1.3192 |

## Kết luận
Random Forest có MAE thấp hơn Decision Tree khoảng 23.93% và RMSE thấp hơn khoảng 26.89% trên tập test theo thời gian.
Điều này cho thấy Random Forest dự đoán ổn định hơn vì dùng nhiều cây quyết định và lấy trung bình kết quả, nhờ đó giảm overfit so với một Decision Tree đơn.

## File đã tạo
- `models/decision_tree_model.pkl`
- `models/random_forest_model.pkl`
- `results/model_comparison_metrics.csv`
- `results/test_predictions.csv`
- `results/decision_tree_feature_importance.csv`: feature importance của Decision Tree
- `results/random_forest_feature_importance.csv`: feature importance của Random Forest