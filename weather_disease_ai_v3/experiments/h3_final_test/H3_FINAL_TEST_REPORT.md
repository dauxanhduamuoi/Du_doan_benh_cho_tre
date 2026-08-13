# H3 Final Test Report

## 1. MODEL LOCK

- H3 WITH WEATHER SHA-256: `ee02631de0d08f6036167a23effaff17352d04f11ffa19560b1d5dd02002fe98`; tree count: 18.
- H3 NO WEATHER SHA-256: `eddead712366969afa5a08586fc74af3f648b9ca9bc20276d674b7adc0c979ff`; tree count: 15.
- H3 đã được chọn bằng VALIDATION trước khi TEST được load. Không retrain, tuning, resume training hay chọn iteration mới.

## 2. TEST DATA

- TEST queries: 2772; date range: 2024-08-26 → 2025-04-13.
- Supported diseases từ TRAIN: 221; target shape: `2772x221`.
- Positive diseases/query: mean=20.220, median=23.000; zero-positive=470.
- Query tham gia mean metric: 2302 / 2772.
- Positive TEST pairs ngoài TRAIN-supported universe, không được chấm như label model: 1384.

## 3. WITH WEATHER

- 45 features theo đúng schema/order model; prediction time=0.023 giây.

## 4. NO WEATHER

- 6 features theo đúng schema/order model; prediction time=0.013 giây.

## 5. BASELINE

Baseline H3 rebuild từ TRAIN-only theo `age_group + gender + month → age_group + month → month → global`, dùng `case_count_h3` làm frequency prior. TEST chỉ được evaluate.

## 6. TEST METRICS

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.7533 | 0.7480 | 0.7447 | 0.005300 | 0.008688 |
| Recall@5 | 0.1711 | 0.1674 | 0.1639 | 0.003742 | 0.007165 |
| NDCG@5 | 0.7631 | 0.7627 | 0.7551 | 0.000332 | 0.007996 |
| Precision@10 | 0.6866 | 0.6868 | 0.6837 | -0.000217 | 0.002911 |
| Recall@10 | 0.2974 | 0.3021 | 0.2953 | -0.004772 | 0.002032 |
| NDCG@10 | 0.7287 | 0.7329 | 0.7230 | -0.004242 | 0.005701 |

## 7. WEATHER DELTA

- Weather-NoWeather NDCG@5: 0.000332.
- Weather-NoWeather NDCG@10: -0.004242.

Weather delta chỉ là bằng chứng dự báo thống kê trong bộ dữ liệu hiện tại, không phải quan hệ nhân quả.

## 8. BASELINE DELTA

- Weather-Baseline NDCG@5: 0.007996.
- Weather-Baseline NDCG@10: 0.005701.

## 9. VALIDATION VS TEST

| Metric | Validation Weather | Test Weather | Difference (Test-Validation) |
|---|---:|---:|---:|
| Precision@5 | 0.7276 | 0.7533 | 0.025777 |
| Recall@5 | 0.1587 | 0.1711 | 0.012374 |
| NDCG@5 | 0.7364 | 0.7631 | 0.026650 |
| NDCG@10 | 0.7168 | 0.7287 | 0.011850 |

### Weather gain: VALIDATION vs TEST

| Metric | Validation Weather Gain | Test Weather Gain |
|---|---:|---:|
| NDCG@5 | 0.014707 | 0.000332 |
| NDCG@10 | 0.004618 | -0.004242 |
| Precision@5 | 0.010887 | 0.005300 |
| Recall@5 | 0.002315 | 0.003742 |

## 10. BOOTSTRAP CI

Paired query bootstrap: 1000 repetitions, random_seed=42; prediction cố định, không retrain.

| Statistic | Estimate | 95% CI lower | 95% CI upper |
|---|---:|---:|---:|
| with_weather_ndcg_at_5 | 0.763065 | 0.749847 | 0.777443 |
| no_weather_ndcg_at_5 | 0.762734 | 0.749669 | 0.776495 |
| baseline_ndcg_at_5 | 0.755069 | 0.741600 | 0.768634 |
| weather_minus_no_weather_ndcg_at_5 | 0.000332 | -0.001887 | 0.002519 |
| weather_minus_baseline_ndcg_at_5 | 0.007996 | 0.003905 | 0.012278 |
| weather_minus_no_weather_ndcg_at_10 | -0.004242 | -0.006050 | -0.002395 |
| weather_minus_baseline_ndcg_at_10 | 0.005701 | 0.001894 | 0.009338 |

## 11. FINAL CONCLUSION

**H3_FINAL_MODEL_GOOD_WEATHER_WEAK** — WITH WEATHER cạnh tranh baseline nhưng weather gain trên TEST gần 0 hoặc chưa đạt ngưỡng thực dụng.

Model xếp hạng các nhóm bệnh đáng chú ý dựa trên tuổi, giới tính, thời điểm trong năm và mẫu hình thời tiết hiện tại/gần đây trong dữ liệu lịch sử bệnh viện.

## 12. LIMITATIONS

- Ranking score chưa được chứng minh/calibrate thành xác suất cá nhân.
- Đây không phải mô hình chẩn đoán và không chứng minh weather gây ra disease.
- TEST là final holdout; không được dùng lại như validation cho tuning sau báo cáo này.

## 13. INTEGRITY

- Model/source/training artifact checksum sau evaluation: **PASS**.
- Không train model, không sửa H3, không test H7/H14, không SHAP, API, backend hay frontend.
- Mọi artifact mới chỉ nằm trong `experiments/h3_final_test/`.
