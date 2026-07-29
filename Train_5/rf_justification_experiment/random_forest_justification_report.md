# Random Forest justification experiment

## Data and split
- Source: `train_history.xlsx`
- Patient rows after cleaning: 257771
- Training rows after monthly lag features: 47583
- Period range: 2021-02 to 2025-04 (51 monthly periods)
- Train periods: 2021-02 to 2024-05 (40 periods)
- Test periods: 2024-06 to 2025-04 (11 periods)

## Model comparison
| model                        |   train_time_seconds |    MAE |    RMSE |        R2 |
|:-----------------------------|---------------------:|-------:|--------:|----------:|
| Random Forest 300 cây        |              23.2043 | 2.2293 |  7.7975 |  0.923617 |
| Gradient Boosting            |              19.8675 | 2.2417 |  7.7329 |  0.924878 |
| KNN k=5                      |               0.0511 | 2.2954 |  8.7694 |  0.90339  |
| Baseline tháng trước (lag_1) |               0      | 2.3076 |  7.9993 |  0.919613 |
| Baseline TB 3 tháng          |               0      | 2.3574 |  9.0217 |  0.897749 |
| Ridge tuyến tính             |               0.1334 | 2.3901 |  7.8567 |  0.922452 |
| Baseline TB 5 tháng          |               0      | 2.5173 |  9.9672 |  0.875194 |
| Decision Tree đơn            |               1.5719 | 2.9306 | 10.6656 |  0.857092 |
| Dummy trung bình train       |               0.046  | 8.7452 | 28.2733 | -0.004244 |

## Main conclusion
Random Forest reduces MAE by 3.39% compared with the previous-month baseline.

## Top Random Forest feature importances
| feature                                                                                                                                                           |   importance |
|:------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------:|
| num__lag_1                                                                                                                                                        |     0.890696 |
| num__rolling_3                                                                                                                                                    |     0.03305  |
| num__change_1                                                                                                                                                     |     0.010075 |
| num__target_month_num                                                                                                                                             |     0.009877 |
| num__lag_2                                                                                                                                                        |     0.008443 |
| num__rolling_5                                                                                                                                                    |     0.00732  |
| num__lag_5                                                                                                                                                        |     0.007295 |
| num__lag_4                                                                                                                                                        |     0.005805 |
| num__lag_3                                                                                                                                                        |     0.005569 |
| num__target_month_cos                                                                                                                                             |     0.003896 |
| num__target_month_sin                                                                                                                                             |     0.003289 |
| num__target_year                                                                                                                                                  |     0.003027 |
| cat__disease_target_Các bệnh viêm phổi - Pneumonia                                                                                                                |     0.002876 |
| cat__disease_target_Bệnh virut khác - Other viral diseases                                                                                                        |     0.00155  |
| cat__disease_target_COVID-19 * U07.1 là bệnh nhân COVID-19 có kết quả xét nghiệm SARS-CoV-2 dương tính cập nhật theo hướng dẫn chẩn đoán và điều trị của Bộ Y tế. |     0.00086  |

Generated files stay inside this experiment folder.