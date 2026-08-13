# LightGBM One-vs-Rest H3/H7/H14 Report

## 1. Environment

- LightGBM `4.7.0`, Python `3.14.5`.
- CPU: 16 physical / 32 logical; RAM: 15.3 GiB.
- Strategy: disease loop tuần tự, outer parallel=1, mỗi classifier n_jobs=8; không nested parallelism.

## 2. Dataset

- TRAIN/VALIDATION: 12864 / 2748 queries.
- TRAIN-supported diseases: 221; cùng universe cho H3/H7/H14.
- TEST không có path trong benchmark script và không được load.

## 3. One-vs-Rest design

Mỗi disease là một binary classifier `has_case_h*`; positive-class score của 221 classifier được ghép thành query×disease matrix và xếp hạng. Natural TRAIN prevalence được giữ nguyên: không class weight, scale_pos_weight, oversampling hay SMOTE.

## 4. Config

`binary`, `gbdt`, n_estimators=200, learning_rate=0.05, num_leaves=15, max_depth=4, min_child_samples=20, subsample=0.9, colsample_bytree=0.9, reg_lambda=1, seed=42; early stopping 20 theo VALIDATION binary_logloss.

## 5. H3 result

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather gain | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.7359 | 0.7274 | 0.7187 | 0.008516 | 0.017208 |
| Recall@5 | 0.1658 | 0.1579 | 0.1572 | 0.007925 | 0.008625 |
| NDCG@5 | 0.7491 | 0.7434 | 0.7245 | 0.005726 | 0.024634 |
| Precision@10 | 0.6799 | 0.6837 | 0.6696 | -0.003819 | 0.010272 |
| Recall@10 | 0.2946 | 0.2920 | 0.2856 | 0.002564 | 0.008979 |
| NDCG@10 | 0.7227 | 0.7247 | 0.7049 | -0.002092 | 0.017740 |

Best iterations WITH: mean=58.50, median=47.0, range=1–200; NO: mean=60.08, median=48.0, range=1–200.

## 6. H7 result

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather gain | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.8334 | 0.8225 | 0.8154 | 0.010971 | 0.018024 |
| Recall@5 | 0.1276 | 0.1236 | 0.1252 | 0.004050 | 0.002376 |
| NDCG@5 | 0.8401 | 0.8364 | 0.8154 | 0.003694 | 0.024637 |
| Precision@10 | 0.8021 | 0.7984 | 0.7876 | 0.003700 | 0.014541 |
| Recall@10 | 0.2342 | 0.2301 | 0.2285 | 0.004133 | 0.005714 |
| NDCG@10 | 0.8268 | 0.8256 | 0.8067 | 0.001186 | 0.020071 |

Best iterations WITH: mean=62.68, median=51.0, range=1–200; NO: mean=61.76, median=54.0, range=1–200.

## 7. H14 result

| Metric | WITH WEATHER | NO WEATHER | Baseline | Weather gain | Weather-Baseline |
|---|---:|---:|---:|---:|---:|
| Precision@5 | 0.8875 | 0.8740 | 0.8696 | 0.013455 | 0.017882 |
| Recall@5 | 0.1031 | 0.1010 | 0.1049 | 0.002106 | -0.001865 |
| NDCG@5 | 0.8955 | 0.8832 | 0.8684 | 0.012304 | 0.027096 |
| Precision@10 | 0.8609 | 0.8559 | 0.8466 | 0.004991 | 0.014236 |
| Recall@10 | 0.1886 | 0.1883 | 0.1900 | 0.000275 | -0.001347 |
| NDCG@10 | 0.8754 | 0.8683 | 0.8560 | 0.007094 | 0.019367 |

Best iterations WITH: mean=64.16, median=53.0, range=1–200; NO: mean=63.38, median=58.0, range=1–200.

## 8. Weather gain

| Horizon | LightGBM gain NDCG@5 | CatBoost gain NDCG@5 | LightGBM gain NDCG@10 | CatBoost gain NDCG@10 |
|---|---:|---:|---:|---:|
| H3 | 0.005726 | 0.014707 | -0.002092 | 0.004618 |
| H7 | 0.003694 | 0.002596 | 0.001186 | -0.000261 |
| H14 | 0.012304 | -0.002297 | 0.007094 | -0.005998 |

## 9. NDCG@5: baseline/CatBoost comparison

| Horizon | LightGBM Weather | LightGBM NoWeather | Baseline | Weather Gain | CatBoost Weather | LGBM-CatBoost |
|---|---:|---:|---:|---:|---:|---:|
| H3 | 0.7491 | 0.7434 | 0.7245 | 0.005726 | 0.7364 | 0.012730 |
| H7 | 0.8401 | 0.8364 | 0.8154 | 0.003694 | 0.8259 | 0.014141 |
| H14 | 0.8955 | 0.8832 | 0.8684 | 0.012304 | 0.8833 | 0.012149 |

## 10. NDCG@10: baseline/CatBoost comparison

| Horizon | LightGBM Weather | LightGBM NoWeather | Baseline | Weather Gain | CatBoost Weather | LGBM-CatBoost |
|---|---:|---:|---:|---:|---:|---:|
| H3 | 0.7227 | 0.7247 | 0.7049 | -0.002092 | 0.7168 | 0.005826 |
| H7 | 0.8268 | 0.8256 | 0.8067 | 0.001186 | 0.8247 | 0.002155 |
| H14 | 0.8754 | 0.8683 | 0.8560 | 0.007094 | 0.8724 | 0.002967 |

## 11. Runtime/resource

| Run | Train time (s) | Predict time (s) | Classifiers | Peak RSS (MiB) | Peak delta (MiB) | Mean CPU share (%) | Serialized size (MiB) |
|---|---:|---:|---:|---:|---:|---:|---:|
| H3 WITH | 13.89 | 0.41 | 221 | 275.4 | 23.4 | 24.8 | 16.22 |
| H3 NO | 6.15 | 0.29 | 221 | 269.9 | 2.6 | 24.9 | 16.66 |
| H7 WITH | 14.09 | 0.42 | 221 | 281.2 | 8.7 | 24.9 | 17.65 |
| H7 NO | 6.30 | 0.29 | 221 | 274.2 | 3.8 | 24.8 | 17.53 |
| H14 WITH | 14.04 | 0.46 | 221 | 283.6 | 10.5 | 24.9 | 18.39 |
| H14 NO | 6.41 | 0.31 | 221 | 279.7 | 3.4 | 24.9 | 18.05 |

Tổng wall-clock benchmark: **64.65 giây**. 1.326 model strings có tổng size được đo nhưng không persist để tránh rải nhiều file; score matrices và label metadata đã lưu trong `artifacts/`.

## 12. Recommendation

**BEST_LIGHTGBM_HORIZON: H14** — Chỉ horizon này đạt weather-gain gate và cạnh tranh baseline.

**LIGHTGBM_VS_CATBOOST: LIGHTGBM_PROMISING** — Ít nhất một horizon cạnh tranh CatBoost và cho weather gain đủ ngưỡng.

Weather gain chỉ là tín hiệu dự báo thống kê trong TRAIN/VALIDATION, không phải quan hệ nhân quả.

## 13. Integrity

- Raw/processed/TRAIN/VALIDATION/CatBoost validation checksum: **PASS**.
- TEST không có path trong script, không load feature/target/prediction/metric.
- Không retrain CatBoost; không đọc CatBoost TEST result; không SHAP/tuning/API/frontend/backend.
- Mọi artifact mới chỉ nằm trong `benchmarks/lightgbm_ovr_h3_h7_h14/`.
