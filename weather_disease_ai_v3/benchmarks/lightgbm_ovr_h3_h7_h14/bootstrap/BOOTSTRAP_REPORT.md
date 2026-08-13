# Paired Bootstrap Report: LightGBM Weather Gain

## 1. Method

Paired percentile bootstrap ở query level, 5,000 lần, seed=42. Mỗi lần dùng cùng indices cho WITH WEATHER, NO WEATHER và target.

## 2. Validation dataset

- Validation queries: 2,748.
- Disease order: 221 nhóm, WITH/NO giống nhau.
- Zero-positive query được loại khỏi trung bình đúng như metric contract V3.

## 3. Paired bootstrap design

Score được chuyển thành đóng góp metric theo từng query bằng stable descending rank. Bootstrap lấy trung bình paired difference trực tiếp; không trừ hai confidence interval độc lập.

## 4. H3 results

| Metric | Observed gain | Bootstrap mean | Median | SE | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| precision_at_5 | +0.008516 | +0.008528 | +0.008548 | 0.002619 | [+0.003343, +0.013519] | 0.9996 | ROBUST_POSITIVE |
| recall_at_5 | +0.007925 | +0.007951 | +0.007923 | 0.001974 | [+0.004145, +0.011955] | 1.0000 | ROBUST_POSITIVE |
| ndcg_at_5 | +0.005726 | +0.005749 | +0.005704 | 0.002711 | [+0.000431, +0.011020] | 0.9822 | ROBUST_POSITIVE |
| precision_at_10 | -0.003819 | -0.003844 | -0.003903 | 0.001923 | [-0.007532, +0.000044] | 0.0280 | UNCERTAIN |
| recall_at_10 | +0.002564 | +0.002535 | +0.002517 | 0.002066 | [-0.001458, +0.006687] | 0.8886 | UNCERTAIN |
| ndcg_at_10 | -0.002092 | -0.002103 | -0.002100 | 0.002126 | [-0.006180, +0.002032] | 0.1612 | UNCERTAIN |
Zero-positive validation queries: 470.

## 5. H7 results

| Metric | Observed gain | Bootstrap mean | Median | SE | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| precision_at_5 | +0.010971 | +0.010974 | +0.010920 | 0.002240 | [+0.006575, +0.015432] | 1.0000 | ROBUST_POSITIVE |
| recall_at_5 | +0.004050 | +0.004056 | +0.004064 | 0.001251 | [+0.001579, +0.006500] | 0.9992 | ROBUST_POSITIVE |
| ndcg_at_5 | +0.003694 | +0.003672 | +0.003646 | 0.002225 | [-0.000750, +0.008147] | 0.9492 | UNCERTAIN |
| precision_at_10 | +0.003700 | +0.003696 | +0.003721 | 0.001593 | [+0.000527, +0.006828] | 0.9906 | ROBUST_POSITIVE |
| recall_at_10 | +0.004133 | +0.004146 | +0.004134 | 0.001218 | [+0.001708, +0.006506] | 0.9998 | ROBUST_POSITIVE |
| ndcg_at_10 | +0.001186 | +0.001167 | +0.001166 | 0.001585 | [-0.001975, +0.004305] | 0.7668 | UNCERTAIN |
Zero-positive validation queries: 451.

## 6. H14 results

| Metric | Observed gain | Bootstrap mean | Median | SE | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| precision_at_5 | +0.013455 | +0.013500 | +0.013478 | 0.002110 | [+0.009440, +0.017714] | 1.0000 | ROBUST_POSITIVE |
| recall_at_5 | +0.002106 | +0.002121 | +0.002116 | 0.000702 | [+0.000761, +0.003482] | 0.9986 | ROBUST_POSITIVE |
| ndcg_at_5 | +0.012304 | +0.012322 | +0.012329 | 0.002014 | [+0.008373, +0.016271] | 1.0000 | ROBUST_POSITIVE |
| precision_at_10 | +0.004991 | +0.004987 | +0.004978 | 0.001325 | [+0.002365, +0.007629] | 1.0000 | ROBUST_POSITIVE |
| recall_at_10 | +0.000275 | +0.000274 | +0.000268 | 0.000701 | [-0.001049, +0.001681] | 0.6544 | UNCERTAIN |
| ndcg_at_10 | +0.007094 | +0.007086 | +0.007068 | 0.001323 | [+0.004503, +0.009653] | 1.0000 | ROBUST_POSITIVE |
Zero-positive validation queries: 444.

## 7. NDCG@5 comparison

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | +0.005726 | [+0.000431, +0.011020] | 0.9822 | ROBUST_POSITIVE |
| H7 | +0.003694 | [-0.000750, +0.008147] | 0.9492 | UNCERTAIN |
| H14 | +0.012304 | [+0.008373, +0.016271] | 1.0000 | ROBUST_POSITIVE |

## 8. NDCG@10 comparison

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | -0.002092 | [-0.006180, +0.002032] | 0.1612 | UNCERTAIN |
| H7 | +0.001186 | [-0.001975, +0.004305] | 0.7668 | UNCERTAIN |
| H14 | +0.007094 | [+0.004503, +0.009653] | 1.0000 | ROBUST_POSITIVE |

## 9. Precision/Recall results

### precision_at_5

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | +0.008516 | [+0.003343, +0.013519] | 0.9996 | ROBUST_POSITIVE |
| H7 | +0.010971 | [+0.006575, +0.015432] | 1.0000 | ROBUST_POSITIVE |
| H14 | +0.013455 | [+0.009440, +0.017714] | 1.0000 | ROBUST_POSITIVE |

### recall_at_5

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | +0.007925 | [+0.004145, +0.011955] | 1.0000 | ROBUST_POSITIVE |
| H7 | +0.004050 | [+0.001579, +0.006500] | 0.9992 | ROBUST_POSITIVE |
| H14 | +0.002106 | [+0.000761, +0.003482] | 0.9986 | ROBUST_POSITIVE |

### precision_at_10

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | -0.003819 | [-0.007532, +0.000044] | 0.0280 | UNCERTAIN |
| H7 | +0.003700 | [+0.000527, +0.006828] | 0.9906 | ROBUST_POSITIVE |
| H14 | +0.004991 | [+0.002365, +0.007629] | 1.0000 | ROBUST_POSITIVE |

### recall_at_10

| Horizon | Observed gain | 95% CI | P(gain > 0) | Decision |
|---|---:|---:|---:|---|
| H3 | +0.002564 | [-0.001458, +0.006687] | 0.8886 | UNCERTAIN |
| H7 | +0.004133 | [+0.001708, +0.006506] | 0.9998 | ROBUST_POSITIVE |
| H14 | +0.000275 | [-0.001049, +0.001681] | 0.6544 | UNCERTAIN |

## 10. Weather contribution conclusion

**H14_HAS_STRONGEST_VALIDATION_WEATHER_SIGNAL** theo CI lower bound NDCG@5, sau đó observed gain và xác nhận NDCG@10.

- NDCG@5 robust positive: H3, H14.
- NDCG@10 robust positive: H14.
- Đây là đóng góp dự báo/thống kê trên VALIDATION, không phải bằng chứng nhân quả và không phải kết luận TEST.
- Runtime bootstrap + validation: 1.758 giây.

## 11. Integrity

- Locked input/artifact checksum: **PASS**.
- Không train lại TRAIN, LightGBM hay CatBoost; không load model và không inference lại.
- TEST không được load, predict hay đọc metric; phân tích chỉ dùng VALIDATION.
- WITH/NO paired bằng cùng query indices; seed=42.
- Sáu score matrix tái tạo chính xác benchmark metrics trước bootstrap.
- Query order được khóa bởi validation ID order, benchmark source hash và exact metric reproduction.
