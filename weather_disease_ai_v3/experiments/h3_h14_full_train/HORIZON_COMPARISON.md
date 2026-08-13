# H3 / H7 / H14 Horizon Comparison

> So sánh VALIDATION trên cùng temporal split và cùng 221-disease universe. TEST chưa được sử dụng.

## Summary

- **H3:** H3_WEATHER_PROMISING; positive/query mean=20.72, median=24.0.
- **H7:** H7_MODEL_GOOD_BUT_WEATHER_WEAK; positive/query mean=32.57, median=40.0.
- **H14:** H14_MODEL_GOOD_BUT_WEATHER_WEAK; positive/query mean=43.68, median=54.0.

## WITH WEATHER metrics

| Metric | H3 Weather | H7 Weather | H14 Weather |
|---|---:|---:|---:|
| Precision@5 | 0.7276 | 0.8179 | 0.8806 |
| Recall@5 | 0.1587 | 0.1224 | 0.1033 |
| NDCG@5 | 0.7364 | 0.8259 | 0.8833 |
| Precision@10 | 0.6813 | 0.8052 | 0.8638 |
| Recall@10 | 0.2899 | 0.2330 | 0.1924 |
| NDCG@10 | 0.7168 | 0.8247 | 0.8724 |

## NDCG@5: weather, control và baseline

| Horizon | Weather NDCG@5 | NoWeather NDCG@5 | Baseline NDCG@5 | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| H3 | 0.7364 | 0.7217 | 0.7245 | 0.014707 | 0.011904 |
| H7 | 0.8259 | 0.8233 | 0.8154 | 0.002596 | 0.010496 |
| H14 | 0.8833 | 0.8856 | 0.8684 | -0.002297 | 0.014947 |

## NDCG@10: weather, control và baseline

| Horizon | Weather NDCG@10 | NoWeather NDCG@10 | Baseline NDCG@10 | Weather-NoWeather | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| H3 | 0.7168 | 0.7122 | 0.7049 | 0.004618 | 0.011914 |
| H7 | 0.8247 | 0.8249 | 0.8067 | -0.000261 | 0.017916 |
| H14 | 0.8724 | 0.8784 | 0.8560 | -0.005998 | 0.016400 |

## Positive support và training

| Horizon | Mean positive/query | Median | Zero-positive VALIDATION | WITH time (s) | NO time (s) |
|---|---:|---:|---:|---:|---:|
| H3 | 20.724 | 24.000 | 470 | 22.394 | 16.327 |
| H7 | 32.575 | 40.000 | 451 | 37.893 | 36.811 |
| H14 | 43.683 | 54.000 | 444 | 16.412 | 17.048 |

Recall giữa các horizon không nên so máy móc vì số positive disease/query thay đổi theo độ dài horizon.

## Recommendation

**Recommended horizon for final TEST: H3**

**Reason:** Chỉ horizon này đạt weather-gain gate, cạnh tranh baseline và không có metric suy giảm nghiêm trọng.

Không model nào được copy thành production/final và TEST chưa được chạy.
