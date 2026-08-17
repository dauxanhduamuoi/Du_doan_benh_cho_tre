# PRE-TIER-2 Weather-heavy Filtering Report

## Phạm vi và kết quả join

Đây chỉ là bước post-processing kết quả disease-level SHAP đã có. Không huấn luyện, không tuning, không chọn model, không dùng TEST target và không tạo giải thích y khoa/nhân quả.

Join theo disease_id **PASS**:

- Disease trong SHAP summary: **221**
- Model trong manifest: **221**
- Disease join thành công: **221/221**
- Duplicate trong SHAP: **0**
- Duplicate trong manifest: **0**
- Thiếu ở SHAP hoặc manifest: **0**

positive_fit_queries là số query trong TRAIN + VALIDATION có target positive cho disease đó; đây **không phải số bệnh nhân**.

## Phân bố support

| Thống kê | positive_fit_queries |
|---|---:|
| Min | 14 |
| Q1 | 187.00 |
| Median | 1012.00 |
| Q3 | 4106.00 |
| Max | 9598 |
| Mean | 2433.29 |

| Support tier | Quy tắc | Số disease | Tỷ lệ |
|---|---|---:|---:|
| LOW | < 100 | 39 | 17.65% |
| MODERATE | 100–199 | 18 | 8.14% |
| BETTER | 200–499 | 25 | 11.31% |
| STRONG | >= 500 | 139 | 62.90% |

Các ngưỡng trên là **project-level heuristic** (quy tắc thực hành của project), không phải chuẩn y khoa và không phải ngưỡng thống kê chính thức.

Có **164 disease** đủ support (positive_fit_queries >= 200) để nằm trong bảng xếp hạng chính trước Tầng 2. Top 20 dưới đây chỉ là danh sách ưu tiên để thực hiện giải thích y khoa ở bước sau.

## Top 20 WEATHER_HEAVY_ELIGIBLE

| Rank | disease_id | disease_name | positive_fit_queries | n_estimators_locked | weather | seasonal | demographic | support | complexity |
|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 161 | Viêm tĩnh mạch, viêm tĩnh mạch huyết khối, nghẽn mạch và huyết khối tĩnh mạch - Phlebitis, thrombophlebitis,venous embolism and thrombosis | 613 | 1 | 0.519889 | 0.127484 | 0.352627 | STRONG | VERY_SIMPLE_MODEL |
| 2 | 58 | U ác môi, khoang miệng, họng - Malignant neoplasm of lip, oral cavity and pharynx | 370 | 4 | 0.485399 | 0.141178 | 0.373423 | BETTER | SIMPLE_MODEL |
| 3 | 38 | Viêm gan virut khác - Other viral hepatitis | 322 | 5 | 0.483591 | 0.067075 | 0.449334 | BETTER | SIMPLE_MODEL |
| 4 | 313 | COVID-19 * U07.1 là bệnh nhân COVID-19 có kết quả xét nghiệm SARS-CoV-2 dương tính cập nhật theo hướng dẫn chẩn đoán và điều trị của Bộ Y tế. | 3776 | 21 | 0.435035 | 0.251472 | 0.313494 | STRONG | NORMAL_MODEL |
| 5 | 81 | U ác mắt và các phần phụ - Malignant neoplasm of eye and adnexa | 208 | 15 | 0.424610 | 0.099245 | 0.476145 | BETTER | NORMAL_MODEL |
| 6 | 254 | Gai đôi cột sống - Spina bifida | 308 | 200 | 0.421427 | 0.147431 | 0.431142 | BETTER | NORMAL_MODEL |
| 7 | 142 | Bệnh khác của tai và xương chũm - Other diseases of the ear and mastoid process | 378 | 49 | 0.406487 | 0.150573 | 0.442940 | BETTER | NORMAL_MODEL |
| 8 | 4 | Lỵ Amip - Amoebiasis | 294 | 1 | 0.396245 | 0.138283 | 0.465471 | BETTER | VERY_SIMPLE_MODEL |
| 9 | 74 | U ác khác cơ quan sinh dục nữ - Malignant neoplasms of female genital organs | 407 | 195 | 0.394889 | 0.068176 | 0.536934 | BETTER | NORMAL_MODEL |
| 10 | 5 | Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. | 7727 | 158 | 0.388926 | 0.066579 | 0.544495 | STRONG | NORMAL_MODEL |
| 11 | 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 7445 | 200 | 0.386398 | 0.080184 | 0.533419 | STRONG | NORMAL_MODEL |
| 12 | 124 | Động kinh - Epilepsy | 8356 | 145 | 0.383667 | 0.091207 | 0.525125 | STRONG | NORMAL_MODEL |
| 13 | 96 | U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour | 8892 | 119 | 0.378852 | 0.106695 | 0.514453 | STRONG | NORMAL_MODEL |
| 14 | 83 | U ác các phần khác của hệ thần kinh trung ương - Malignant neoplasm of other parts of central nervous system | 218 | 1 | 0.375865 | 0.115588 | 0.508547 | BETTER | VERY_SIMPLE_MODEL |
| 15 | 69 | U ác xương và sụn khớp - Malignant neoplasms of bone and articular cartilage | 4138 | 101 | 0.371621 | 0.044127 | 0.584252 | STRONG | NORMAL_MODEL |
| 16 | 185 | Bệnh khác của thực quản, dạ dày và tá tràng - Other diseases of oesophagus, stomach, duodenum | 9330 | 105 | 0.368703 | 0.047694 | 0.583604 | STRONG | NORMAL_MODEL |
| 17 | 8 | Các dạng lao khác - Other tuberculosis | 828 | 90 | 0.368518 | 0.150112 | 0.481371 | STRONG | NORMAL_MODEL |
| 18 | 144 | Bệnh thấp tim mãn - Chronic rheumatic disease | 276 | 24 | 0.368001 | 0.171857 | 0.460142 | BETTER | NORMAL_MODEL |
| 19 | 199 | Bệnh khác của da và mô tế bào dưới da - Other diseases of skin and subcutaneous tissue | 8240 | 101 | 0.367873 | 0.077010 | 0.555117 | STRONG | NORMAL_MODEL |
| 20 | 272 | Gãy xương cổ, ngực, khung chậu - Fracture of neck, thorax or pelvis. | 204 | 17 | 0.367469 | 0.170359 | 0.462172 | BETTER | NORMAL_MODEL |

Không áp dụng ngưỡng phần trăm weather tùy ý. Các disease đủ support chỉ được xếp giảm dần theo weather_importance.

## Top 10 trong nhóm STRONG support

Có **139 disease** thuộc nhóm STRONG.

| Rank | disease_id | disease_name | positive_fit_queries | n_estimators_locked | weather | seasonal | demographic | support | complexity |
|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 161 | Viêm tĩnh mạch, viêm tĩnh mạch huyết khối, nghẽn mạch và huyết khối tĩnh mạch - Phlebitis, thrombophlebitis,venous embolism and thrombosis | 613 | 1 | 0.519889 | 0.127484 | 0.352627 | STRONG | VERY_SIMPLE_MODEL |
| 2 | 313 | COVID-19 * U07.1 là bệnh nhân COVID-19 có kết quả xét nghiệm SARS-CoV-2 dương tính cập nhật theo hướng dẫn chẩn đoán và điều trị của Bộ Y tế. | 3776 | 21 | 0.435035 | 0.251472 | 0.313494 | STRONG | NORMAL_MODEL |
| 3 | 5 | Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. | 7727 | 158 | 0.388926 | 0.066579 | 0.544495 | STRONG | NORMAL_MODEL |
| 4 | 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 7445 | 200 | 0.386398 | 0.080184 | 0.533419 | STRONG | NORMAL_MODEL |
| 5 | 124 | Động kinh - Epilepsy | 8356 | 145 | 0.383667 | 0.091207 | 0.525125 | STRONG | NORMAL_MODEL |
| 6 | 96 | U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour | 8892 | 119 | 0.378852 | 0.106695 | 0.514453 | STRONG | NORMAL_MODEL |
| 7 | 69 | U ác xương và sụn khớp - Malignant neoplasms of bone and articular cartilage | 4138 | 101 | 0.371621 | 0.044127 | 0.584252 | STRONG | NORMAL_MODEL |
| 8 | 185 | Bệnh khác của thực quản, dạ dày và tá tràng - Other diseases of oesophagus, stomach, duodenum | 9330 | 105 | 0.368703 | 0.047694 | 0.583604 | STRONG | NORMAL_MODEL |
| 9 | 8 | Các dạng lao khác - Other tuberculosis | 828 | 90 | 0.368518 | 0.150112 | 0.481371 | STRONG | NORMAL_MODEL |
| 10 | 199 | Bệnh khác của da và mô tế bào dưới da - Other diseases of skin and subcutaneous tissue | 8240 | 101 | 0.367873 | 0.077010 | 0.555117 | STRONG | NORMAL_MODEL |

## LOW/MODERATE có weather SHAP cao

Các disease dưới đây đứng đầu theo weather_importance trong nhóm có positive_fit_queries < 200. Chúng vẫn được giữ trong model, nhưng được gắn cờ DO_NOT_USE_AS_PRIMARY_WEATHER_EXAMPLE và không dùng làm ví dụ disease-level chính.

| Rank | disease_id | disease_name | positive_fit_queries | n_estimators_locked | weather | seasonal | demographic | support | complexity |
|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 245 | Bệnh lí thai nhi và sơ sinh do biến chứng thai nghén, chửa, đẻ - Fetus and newborn affected by maternal factors and by complications of pregnancy, labour and delivery | 14 | 1 | 0.913809 | 0.000000 | 0.086191 | LOW | VERY_SIMPLE_MODEL |
| 2 | 115 | Tâm thần phân liệt, rối loạn dạng phân liệt và hoang tưởng - Schizophrenia, schiztypal and delusional disorders | 119 | 4 | 0.849386 | 0.135717 | 0.014897 | MODERATE | SIMPLE_MODEL |
| 3 | 242 | Các biến chứng khác của chửa đẻ - Other complications pregnancy and delivery | 14 | 1 | 0.815396 | 0.000000 | 0.184604 | LOW | VERY_SIMPLE_MODEL |
| 4 | 191 | Bệnh túi thừa của ruột non - Diverticular disease of intestine | 62 | 2 | 0.593976 | 0.406024 | 0.000000 | LOW | VERY_SIMPLE_MODEL |
| 5 | 155 | Tai biến mạch máu não, không xác định rõ chảy máu hoặc do nhồi máu - Stroke, not specified as haemorrhage or infarction | 14 | 16 | 0.592902 | 0.281460 | 0.125637 | LOW | NORMAL_MODEL |
| 6 | 107 | Thiếu vitamin khác - Other vitamin deficiencies. | 84 | 128 | 0.585275 | 0.097349 | 0.317376 | LOW | NORMAL_MODEL |
| 7 | 92 | U cơ trơn tử cung - Leiomyoma of uterus | 14 | 200 | 0.537039 | 0.279598 | 0.183363 | LOW | NORMAL_MODEL |
| 8 | 290 | Tai nạn giao thông - Transport accidént | 70 | 196 | 0.533620 | 0.208841 | 0.257539 | LOW | NORMAL_MODEL |
| 9 | 47 | Các nhiễm khuẩn do sán lá - Other fluke infections | 14 | 199 | 0.528254 | 0.290333 | 0.181413 | LOW | NORMAL_MODEL |
| 10 | 289 | Di chứng, thương tổn do chấn thương, do ngộ độc và hậu quả khác do nguyên nhân bên ngoài - Sequalae of injuries, of poisoning and of other consequences of external causes | 70 | 32 | 0.524166 | 0.310293 | 0.165541 | LOW | NORMAL_MODEL |

## Cảnh báo model rất đơn giản

Số model theo cờ diễn giải:

- VERY_SIMPLE_MODEL (<= 2 cây): **32**
- SIMPLE_MODEL (3–5 cây): **9**
- NORMAL_MODEL (> 5 cây): **180**

Trong Top 20 WEATHER_HEAVY_ELIGIBLE có **3** disease dùng model chỉ 1–2 cây. Đây là cảnh báo khi diễn giải, không phải hard filter.

| Rank | disease_id | disease_name | positive_fit_queries | n_estimators_locked | weather | seasonal | demographic | support | complexity |
|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 161 | Viêm tĩnh mạch, viêm tĩnh mạch huyết khối, nghẽn mạch và huyết khối tĩnh mạch - Phlebitis, thrombophlebitis,venous embolism and thrombosis | 613 | 1 | 0.519889 | 0.127484 | 0.352627 | STRONG | VERY_SIMPLE_MODEL |
| 2 | 4 | Lỵ Amip - Amoebiasis | 294 | 1 | 0.396245 | 0.138283 | 0.465471 | BETTER | VERY_SIMPLE_MODEL |
| 3 | 83 | U ác các phần khác của hệ thần kinh trung ương - Malignant neoplasm of other parts of central nervous system | 218 | 1 | 0.375865 | 0.115588 | 0.508547 | BETTER | VERY_SIMPLE_MODEL |

Để audit mà không đặt ngưỡng weather tùy ý, dưới đây là các model VERY_SIMPLE_MODEL được xếp theo weather_importance (tối đa 10 dòng):

| Rank | disease_id | disease_name | positive_fit_queries | n_estimators_locked | weather | seasonal | demographic | support | complexity |
|---:|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | 245 | Bệnh lí thai nhi và sơ sinh do biến chứng thai nghén, chửa, đẻ - Fetus and newborn affected by maternal factors and by complications of pregnancy, labour and delivery | 14 | 1 | 0.913809 | 0.000000 | 0.086191 | LOW | VERY_SIMPLE_MODEL |
| 2 | 242 | Các biến chứng khác của chửa đẻ - Other complications pregnancy and delivery | 14 | 1 | 0.815396 | 0.000000 | 0.184604 | LOW | VERY_SIMPLE_MODEL |
| 3 | 191 | Bệnh túi thừa của ruột non - Diverticular disease of intestine | 62 | 2 | 0.593976 | 0.406024 | 0.000000 | LOW | VERY_SIMPLE_MODEL |
| 4 | 13 | Các dạng uốn ván khác - Other tetanus | 33 | 1 | 0.522445 | 0.477555 | 0.000000 | LOW | VERY_SIMPLE_MODEL |
| 5 | 161 | Viêm tĩnh mạch, viêm tĩnh mạch huyết khối, nghẽn mạch và huyết khối tĩnh mạch - Phlebitis, thrombophlebitis,venous embolism and thrombosis | 613 | 1 | 0.519889 | 0.127484 | 0.352627 | STRONG | VERY_SIMPLE_MODEL |
| 6 | 258 | Không có, tịt hoặc hẹp ruột non - Absence, atresia and stenosis of small intestine | 89 | 2 | 0.515085 | 0.208571 | 0.276345 | LOW | VERY_SIMPLE_MODEL |
| 7 | 148 | Bệnh tim thiếu máu cục bộ khác - Other ischaemic heart diseases | 42 | 1 | 0.515061 | 0.314447 | 0.170492 | LOW | VERY_SIMPLE_MODEL |
| 8 | 39 | Nhiễm HIV - Human immuno deficiency virus disease | 112 | 2 | 0.505392 | 0.387728 | 0.106880 | MODERATE | VERY_SIMPLE_MODEL |
| 9 | 201 | Bệnh thoái hoá khớp - Arthrosis | 42 | 1 | 0.497229 | 0.420987 | 0.081785 | LOW | VERY_SIMPLE_MODEL |
| 10 | 123 | Xơ cứng nhiều nơi - Multiple sclerosis | 168 | 1 | 0.478664 | 0.378245 | 0.143091 | MODERATE | VERY_SIMPLE_MODEL |

## “Weather-heavy” nghĩa là gì?

Weather-heavy means that weather features account for a relatively large share of SHAP contribution within that disease-specific model.

It does NOT mean that weather causes the disease.

Nói cách khác, đây là xếp hạng mức độ model sử dụng feature thời tiết tương đối nhiều trong từng model disease-specific. Kết quả không chứng minh thời tiết gây bệnh, không phải giải thích y khoa và không tự loại disease dựa trên tên bệnh.

## Không thay đổi kết luận global SHAP

Filtering này chỉ áp dụng khi xếp hạng disease-level weather contribution. Nó không tính lại hoặc sửa các kết luận global SHAP về demographic, weather, seasonal/calendar, current, 3d hay 7d contribution.

## Kiểm tra integrity

- Checksum hai input được ghi trong filter_config.json.
- Kiểm tra SHA-256 của **221 model files** theo manifest: **PASS**.
- SHAP không chạy lại; 221 model không bị sửa.
- TEST target không được đọc hoặc sử dụng.
