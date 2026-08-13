# LightGBM OVR One-Time Final Test Report

> Endpoint/model roles were locked and written to this report before TEST was opened.

## 1. Primary / secondary endpoint lock

- **PRIMARY MODEL:** LightGBM One-vs-Rest H14 WITH WEATHER
- **PRIMARY ENDPOINT:** H14 Weather vs NoWeather NDCG@5
- **SECONDARY CONFIRMATORY:** H14 Weather vs NoWeather NDCG@10
- **SECONDARY HORIZONS:** H3 and H7; these results cannot replace H14 using this TEST.

## 2. Final training protocol

Six OVR experiments were refit on TRAIN+VALIDATION using locked per-disease best iterations. TEST was not used for fitting, early stopping, category mapping, hyperparameters or horizon selection.

## 3. NDCG@5 final TEST

| Horizon | Weather | NoWeather | Baseline | Weather gain | 95% CI | P(gain>0) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| H3 | 0.753569 | 0.754221 | 0.759857 | -0.000652 | [-0.005195, +0.003680] | 0.3698 | UNCERTAIN |
| H7 | 0.851458 | 0.853184 | 0.844156 | -0.001726 | [-0.005176, +0.001817] | 0.1688 | UNCERTAIN |
| H14 | 0.920724 | 0.916131 | 0.888334 | +0.004594 | [+0.001785, +0.007487] | 0.9992 | ROBUST_POSITIVE |

## 4. NDCG@10 final TEST

| Horizon | Weather | NoWeather | Baseline | Weather gain | 95% CI | P(gain>0) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| H3 | 0.728390 | 0.734454 | 0.731039 | -0.006064 | [-0.009460, -0.002607] | 0.0004 | ROBUST_NEGATIVE |
| H7 | 0.833986 | 0.838993 | 0.832959 | -0.005007 | [-0.007556, -0.002386] | 0.0000 | ROBUST_NEGATIVE |
| H14 | 0.900337 | 0.896393 | 0.886981 | +0.003943 | [+0.001843, +0.006104] | 0.9998 | ROBUST_POSITIVE |

## 5. All ranking metrics

### H3

| Variant | P@5 | R@5 | NDCG@5 | P@10 | R@10 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| WITH WEATHER | 0.738749 | 0.164548 | 0.753569 | 0.684883 | 0.302509 | 0.728390 |
| NO WEATHER | 0.740226 | 0.162820 | 0.754221 | 0.693397 | 0.306842 | 0.734454 |
| BASELINE | 0.750130 | 0.164571 | 0.759857 | 0.692137 | 0.299688 | 0.731039 |
### H7

| Variant | P@5 | R@5 | NDCG@5 | P@10 | R@10 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| WITH WEATHER | 0.842424 | 0.123323 | 0.851458 | 0.814589 | 0.234452 | 0.833986 |
| NO WEATHER | 0.843810 | 0.124725 | 0.853184 | 0.820173 | 0.236361 | 0.838993 |
| BASELINE | 0.844848 | 0.121953 | 0.844156 | 0.821212 | 0.234660 | 0.832959 |
### H14

| Variant | P@5 | R@5 | NDCG@5 | P@10 | R@10 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| WITH WEATHER | 0.915671 | 0.104349 | 0.920724 | 0.888139 | 0.195290 | 0.900337 |
| NO WEATHER | 0.911082 | 0.102917 | 0.916131 | 0.884502 | 0.194779 | 0.896393 |
| BASELINE | 0.895065 | 0.097853 | 0.888334 | 0.888485 | 0.194047 | 0.886981 |

## 6. TEST target contract

| Horizon | Queries | Date range | Mean positives/query | Median | Zero-positive | Included | Unsupported positive pairs excluded |
|---|---:|---|---:|---:|---:|---:|---:|
| H3 | 2772 | 2024-08-26 to 2025-04-13 | 20.220 | 23.0 | 470 | 2302 | 1384 |
| H7 | 2772 | 2024-08-26 to 2025-04-13 | 31.994 | 39.0 | 462 | 2310 | 1810 |
| H14 | 2772 | 2024-08-26 to 2025-04-13 | 43.142 | 53.0 | 462 | 2310 | 2179 |

## 7. VALIDATION vs TEST

| Horizon | Metric | Validation Weather | TEST Weather | Validation gain | TEST gain |
|---|---|---:|---:|---:|---:|
| H3 | ndcg_at_5 | 0.749145 | 0.753569 | +0.005726 | -0.000652 |
| H3 | ndcg_at_10 | 0.722650 | 0.728390 | -0.002092 | -0.006064 |
| H7 | ndcg_at_5 | 0.840083 | 0.851458 | +0.003694 | -0.001726 |
| H7 | ndcg_at_10 | 0.826819 | 0.833986 | +0.001186 | -0.005007 |
| H14 | ndcg_at_5 | 0.895461 | 0.920724 | +0.012304 | +0.004594 |
| H14 | ndcg_at_10 | 0.875410 | 0.900337 | +0.007094 | +0.003943 |

## 8. Time

| Run | Training seconds | Prediction seconds |
|---|---:|---:|
| h3_with_weather | 13.663 | 0.339 |
| h3_no_weather | 6.207 | 0.273 |
| h7_with_weather | 14.962 | 0.380 |
| h7_no_weather | 6.529 | 0.275 |
| h14_with_weather | 15.359 | 0.404 |
| h14_no_weather | 6.751 | 0.287 |

Prediction total: 2.733s; paired bootstrap: 0.797s; total wall-clock: 69.797s.

## 9. Final decisions

- **H14 PRIMARY:** H14_FINAL_CONFIRMED.
- **H3 SECONDARY:** H3_SECONDARY_UNCERTAIN.
- **H7 SECONDARY:** H7_SECONDARY_UNCERTAIN.
- These are predictive/statistical associations, not causal claims.
- H3/H7 results are descriptive secondary evaluations; another external temporal holdout is required to confirm a different horizon.

## 10. Integrity

- **PASS:** raw/processed/splits/schema/disease universe/benchmark config checksums stayed locked.
- TEST was opened only after all six models and three baselines were fit.
- TEST was not used for fitting, early stopping, category mapping, tuning, feature selection or horizon selection.
- Six TEST score matrices were generated once and persisted; metrics/bootstrap reused them without inference.
- No training occurred after TEST was opened or after TEST metrics were viewed.
