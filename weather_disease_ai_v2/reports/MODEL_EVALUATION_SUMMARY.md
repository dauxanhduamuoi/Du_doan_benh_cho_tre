# Model Evaluation Summary

> Model xếp hạng các nhóm bệnh thường được ghi nhận trong những trường hợp có tuổi, giới tính và điều kiện thời tiết tương tự.

Báo cáo này đánh giá khả năng xếp hạng thống kê, không phải mô hình chẩn đoán bệnh và không được dùng thay cho đánh giá y khoa.

## Kết luận

**C. Model chưa tốt hơn baseline đủ đáng kể.**

CatBoost đạt weighted Top-5 38.61%, so với baseline 39.11%: chênh lệch -0.50 điểm phần trăm (-1.27% tương đối).
Có 8 nhóm đạt tiêu chí “tương đối tốt”; 188 nhóm có mặt trong TEST thuộc diện rất yếu hoặc unsupported, trong đó 9 nhóm unsupported.

Rubric kết luận: A khi Top-5 tăng ít nhất 3 điểm phần trăm và 10% tương đối; B khi tăng ít nhất 1 điểm phần trăm hoặc 5% tương đối; còn lại là C.

## Phạm vi và kiểm tra tính toàn vẹn

- Chỉ load model `models/weather_disease_catboost_v2.cbm`; không huấn luyện hoặc cập nhật CatBoost.
- SHA-256 model: `69d80fb0c71dcaf70ae04ad2a44ef7c0cfcd380b5f2c9a76ee9979253d855aff`; khớp `model_metadata.json`.
- Train: 92,742 dòng, 162,247 lượt; TEST: 27,566 dòng, 47,349 lượt.
- Universe: 235 nhóm; model support 221 nhóm.
- Không có ngày giao nhau giữa train, validation và TEST.
- Metric headline và recall theo lớp đều weighted bằng `case_count`; unweighted được trình bày bổ sung.
- Baseline được tính từ train theo thứ tự `age_group + gender + month` → `age_group + month` → `month` → toàn bộ train.

## So sánh trên TEST

### Case-weighted (metric chính)

| Phương pháp | Top-1 | Top-5 | Top-10 | Log loss |
|---|---:|---:|---:|---:|
| Baseline tần suất | 16.10% | 39.11% | 54.61% | 5.229412 |
| CatBoost hiện tại | 14.79% | 38.61% | 53.80% | 4.681424 |

- Cải thiện Top-5 tuyệt đối: **-0.50 điểm phần trăm**.
- Cải thiện Top-5 tương đối: **-1.27%**.
- CatBoost có log loss thấp hơn baseline 0.547989; phân phối xác suất tốt hơn theo log loss, nhưng Top-1/5/10 đều thấp hơn baseline.

### Unweighted (tham khảo theo dòng tổng hợp)

| Phương pháp | Top-1 | Top-5 | Top-10 | Log loss |
|---|---:|---:|---:|---:|
| Baseline tần suất | 5.26% | 22.13% | 37.04% | 6.175822 |
| CatBoost hiện tại | 5.10% | 21.95% | 36.78% | 5.175279 |

## Quy tắc phân tích theo nhóm

- Danh sách tốt/kém chỉ xét nhóm `high` hoặc `medium` và có ít nhất 20 lượt TEST.
- “Tương đối tốt”: đủ support và Top-5 recall ≥ 50%.
- “Rất yếu”: có mặt trong TEST và Top-5 recall < 10%, hoặc model không support.
- Hạng thật trung bình là thứ hạng case-weighted của nhãn đúng trong toàn bộ 235 nhóm; unsupported để trống vì xác suất luôn bằng 0.

## 20 nhóm Top-5 recall tốt nhất (20 nhóm đủ điều kiện)

| ID | Tên nhóm bệnh | Train lượt | Test lượt | Support | Top-1 recall | Top-5 recall | Hạng thật TB |
|---|---|---:|---:|---:|---:|---:|---:|
| 169 | Các bệnh viêm phổi - Pneumonia | 26,244 | 7,398 | high | 81.52% | 96.81% | 1.60 |
| 165 | Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis | 7,680 | 2,518 | high | 1.71% | 83.08% | 4.68 |
| 6 | Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases | 7,029 | 2,190 | high | 0.14% | 74.25% | 6.58 |
| 87 | Bệnh bạch cầu - Leukaemia | 6,036 | 1,577 | high | 21.12% | 73.94% | 4.20 |
| 170 | Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis | 10,004 | 2,775 | high | 6.70% | 71.24% | 5.56 |
| 32 | Sốt virut khác do tiết túc truyền và sốt virus xuất huyết - Other arthropod | 5,497 | 828 | high | 25.12% | 67.15% | 6.72 |
| 259 | Dị tật bẩm sinh khác của bộ máy sinh dục tiết niệu - Other malformations of the genitourinary system | 7,524 | 2,181 | high | 4.13% | 59.79% | 6.02 |
| 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 2,712 | 907 | high | 3.31% | 54.47% | 8.12 |
| 204 | Bệnh của hệ thống tổ chức liên kết - Systematic connective tissue disorders | 1,485 | 389 | high | 14.91% | 42.42% | 19.30 |
| 186 | Bệnh của ruột thừa - Diseases of appendix | 1,877 | 457 | high | 1.53% | 39.17% | 9.82 |
| 41 | Bệnh virut khác - Other viral diseases | 6,809 | 817 | high | 0.61% | 34.52% | 10.45 |
| 253 | Tổn thương khác có nguồn gốc trong thời kỳ chu sinh - Other conditions originating in the perinatal period | 1,833 | 725 | high | 0.00% | 27.72% | 18.96 |
| 173 | Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids | 2,683 | 733 | high | 0.55% | 20.33% | 15.33 |
| 184 | Viêm dạ dày và tá tràng - Gastritis and duodenitis | 1,347 | 584 | high | 0.00% | 17.12% | 16.75 |
| 98 | Thiếu máu khác - Other anaemias | 2,206 | 472 | high | 0.00% | 15.89% | 17.97 |
| 176 | Hen - Asthma | 4,663 | 1,162 | high | 0.00% | 13.51% | 11.40 |
| 5 | Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. | 3,930 | 2,356 | high | 0.08% | 12.99% | 11.60 |
| 99 | Tổn thương chảy máu, bệnh khác của máu và cơ quan tạo máu - Haemorrhagic conditions and other diseases of blood, blood | 2,722 | 901 | high | 0.55% | 12.32% | 11.80 |
| 190 | Tắc liệt ruột và tắc ruột không do thoát vị - Paralytic ileus, intestinal obstruction without hernia | 2,865 | 578 | high | 0.00% | 10.73% | 14.14 |
| 200 | Viêm khớp dạng thấp và viêm khớp khác - Rheumatoid arthritis, other inflamatory polyarthropaties | 585 | 251 | high | 0.00% | 9.96% | 28.65 |

## 20 nhóm Top-5 recall kém nhất (20 nhóm đủ điều kiện)

| ID | Tên nhóm bệnh | Train lượt | Test lượt | Support | Top-1 recall | Top-5 recall | Hạng thật TB |
|---|---|---:|---:|---:|---:|---:|---:|
| 270 | Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified | 2,509 | 1,132 | high | 0.00% | 0.00% | 14.24 |
| 124 | Động kinh - Epilepsy | 1,623 | 754 | high | 0.00% | 0.00% | 22.57 |
| 167 | Viêm cấp đường hô hấp trên khác - Other acute upper respiratory infections | 1,688 | 697 | high | 0.00% | 0.00% | 24.85 |
| 199 | Bệnh khác của da và mô tế bào dưới da - Other diseases of skin and subcutaneous tissue | 2,015 | 628 | high | 0.00% | 0.00% | 18.82 |
| 261 | Dị dạng bẩm sinh của bộ máy sinh dục tiết niệu - Congenital malformations of genital organs | 2,259 | 511 | high | 0.00% | 0.00% | 16.42 |
| 198 | Bệnh nhiễm khuẩn da và mô tế bào dưới da - Infections of skin and subcutaneous tissue | 1,694 | 413 | high | 0.00% | 0.00% | 21.29 |
| 281 | Các tổn thương khác do chấn thương xác định và ở nhiều nơi - Other injuries of specified, unspecified and multiple body regions | 1,141 | 361 | high | 0.00% | 0.00% | 27.68 |
| 194 | Các bệnh khác của gan - Other diseases of liver | 1,129 | 333 | high | 0.00% | 0.00% | 25.54 |
| 311 | Bệnh do tiếp xúc với dịch vụ y tế phải chăm sóc và khám xét đặc biệt - Persons encountering health services for specific procedures and health care | 811 | 292 | high | 0.00% | 0.00% | 37.08 |
| 182 | Bệnh khác của khoang miệng, tuyến nước bọt và hàm - Other diseases of the oral cavity, salivary glands and jaws | 959 | 283 | high | 0.00% | 0.00% | 29.00 |
| 120 | Viêm hệ thần kinh trung ương - Inflamatory diseases of the central nervous system | 661 | 281 | high | 0.00% | 0.00% | 40.60 |
| 166 | Viêm thanh, khí quản cấp - Acute laryngitis and tracheitis | 762 | 279 | high | 0.00% | 0.00% | 31.56 |
| 260 | Tinh hoàn lạc chỗ - Undescended testicle | 1,211 | 273 | high | 0.00% | 0.00% | 22.55 |
| 278 | Thương tổn do chấn thương trong sọ - Intracranial injury | 684 | 266 | high | 0.00% | 0.00% | 38.41 |
| 217 | Bệnh khác của bộ máy tiết niệu - Other diseases of the urnary system | 1,027 | 265 | high | 0.00% | 0.00% | 34.18 |
| 265 | Dị dạng bẩm sinh khác - Other congenital malformations | 941 | 250 | high | 0.00% | 0.00% | 34.82 |
| 111 | Bệnh khác về nội tiết, dinh dưỡng và chuyển hoá - Other endocrine, nutritional and metabolic disorders | 676 | 243 | high | 0.00% | 0.00% | 41.25 |
| 192 | Bệnh khác của ruột non và màng bụng - Other diseases of intestine peritoneum | 1,153 | 239 | high | 0.00% | 0.00% | 30.44 |
| 86 | U bạch huyết không phải Hodgkin - Non-Hodgkin's lymphoma | 820 | 198 | high | 0.00% | 0.00% | 25.25 |
| 72 | U ác mạc treo và các mô mềm - Malignantneoplasms of mesothelial and soft tissue | 1,167 | 190 | high | 0.00% | 0.00% | 28.74 |

## Nhóm unsupported (14 nhóm; 9 có mặt trong TEST)

| ID | Tên nhóm bệnh | Train lượt | Test lượt | Support | Top-1 recall | Top-5 recall | Hạng thật TB |
|---|---|---:|---:|---:|---:|---:|---:|
| 35 | Sởi - Measles | 0 | 1,547 | unsupported | 0.00% | 0.00% | — |
| 15 | Ho gà - Whooping cough | 0 | 16 | unsupported | 0.00% | 0.00% | — |
| 219 | Tổn thương khác của tuyến tiền liệt - Other disorders of prostate | 0 | 2 | unsupported | 0.00% | 0.00% | — |
| 294 | Tai nạn do khói, lửa, đám cháy - expossure to smoke, fire and fpames | 0 | 2 | unsupported | 0.00% | 0.00% | — |
| 40 | Quai bị - Mumps | 0 | 2 | unsupported | 0.00% | 0.00% | — |
| 61 | U ác đại tràng - Malignant neoplasm of colon | 0 | 2 | unsupported | 0.00% | 0.00% | — |
| 16 | Nhiễm khuẩn não mô cầu - Meningococcal infection | 0 | 1 | unsupported | 0.00% | 0.00% | — |
| 2 | Thương hàn, phó thương hàn - Typhoid and paratyphoid fevers | 0 | 1 | unsupported | 0.00% | 0.00% | — |
| 295 | Tai nạn do tiếp xúc với các chất nóng - contact with heat and hot | 0 | 1 | unsupported | 0.00% | 0.00% | — |
| 114 | Rối loạn tâm thần và ứng xử liên quan dùng các chất kích thích tâm lí khác - Mental and behavioural disorders due to other psychoactive substances use | 0 | 0 | unsupported | — | — | — |
| 158 | Bệnh mạch máu ngoại vi khác - Other peripheral vascular disease | 0 | 0 | unsupported | — | — | — |
| 280 | Chấn thương dập nát và cắt cụt đã xác định và nhiều vùng trong cơ thể - Fracture of other lim bones | 0 | 0 | unsupported | — | — | — |
| 298 | Tự tử - Intentional self-harm | 0 | 0 | unsupported | — | — | — |
| 67 | U ác khí quản, phế quản và phổi - Malignant neoplasms of trachea, bronchus and lung | 0 | 0 | unsupported | — | — | — |

## Nhóm insufficient nhưng model có support (57 nhóm)

| ID | Tên nhóm bệnh | Train lượt | Test lượt | Support | Top-1 recall | Top-5 recall | Hạng thật TB |
|---|---|---:|---:|---:|---:|---:|---:|
| 19 | Giang mai bẩm sinh - Congenital syphilis | 19 | 8 | insufficient | 0.00% | 0.00% | 147.25 |
| 39 | Nhiễm HIV - Human immuno deficiency virus disease | 4 | 8 | insufficient | 0.00% | 0.00% | 186.62 |
| 272 | Gãy xương cổ, ngực, khung chậu - Fracture of neck, thorax or pelvis. | 11 | 4 | insufficient | 0.00% | 0.00% | 157.75 |
| 42 | Nấm - Mycoses | 11 | 4 | insufficient | 0.00% | 0.00% | 139.75 |
| 191 | Bệnh túi thừa của ruột non - Diverticular disease of intestine | 4 | 4 | insufficient | 0.00% | 0.00% | 172.50 |
| 143 | Thấp khớp cấp - Acute rheumatic heart disease | 3 | 4 | insufficient | 0.00% | 0.00% | 184.50 |
| 292 | Tai nạn chết đuối, chết chìm - Accident drowning and submersion | 5 | 3 | insufficient | 0.00% | 0.00% | 129.00 |
| 33 | Nhiễm virut Héc-pét - Herpesviral infections | 4 | 3 | insufficient | 0.00% | 0.00% | 192.33 |
| 37 | Viêm gan B cấp - Acute hepatitis B | 3 | 3 | insufficient | 0.00% | 0.00% | 192.67 |
| 168 | Cúm - Influenza | 1 | 3 | insufficient | 0.00% | 0.00% | 192.33 |
| 53 | Bệnh giun sán khác - Other Helminthiases | 12 | 2 | insufficient | 0.00% | 0.00% | 145.50 |
| 81 | U ác mắt và các phần phụ - Malignant neoplasm of eye and adnexa | 12 | 2 | insufficient | 0.00% | 0.00% | 126.50 |
| 123 | Xơ cứng nhiều nơi - Multiple sclerosis | 10 | 2 | insufficient | 0.00% | 0.00% | 117.00 |
| 64 | U ác tụy - Malignant neoplasm of pancreas | 9 | 2 | insufficient | 0.00% | 0.00% | 145.50 |
| 146 | Bệnh tăng huyết áp khác - Other hypertensive diseases | 7 | 2 | insufficient | 0.00% | 0.00% | 182.50 |
| 107 | Thiếu vitamin khác - Other vitamin deficiencies. | 6 | 2 | insufficient | 0.00% | 0.00% | 178.50 |
| 116 | Rối loạn khí sắc - Mood ( affective) disorders. | 6 | 2 | insufficient | 0.00% | 0.00% | 158.00 |
| 94 | U lành cơ quan tiết niệu - Benign neoplasm of urinary organs | 5 | 2 | insufficient | 0.00% | 0.00% | 187.00 |
| 115 | Tâm thần phân liệt, rối loạn dạng phân liệt và hoang tưởng - Schizophrenia, schiztypal and delusional disorders | 4 | 2 | insufficient | 0.00% | 0.00% | 163.50 |
| 1 | Tả - Cholera | 1 | 2 | insufficient | 0.00% | 0.00% | 179.50 |
| 137 | Tật khúc xạ, các rối loạn điều tiết - Disorders of refraction and accomodation | 1 | 2 | insufficient | 0.00% | 0.00% | 214.50 |
| 130 | Viêm mi mắt - Inflammation of eyelid | 17 | 1 | insufficient | 0.00% | 0.00% | 191.00 |
| 230 | Rối loạn kinh nguyệt - Disorders of menstruation | 11 | 1 | insufficient | 0.00% | 0.00% | 100.00 |
| 70 | U ác hắc tố da - Malignant melanoma of skin | 10 | 1 | insufficient | 0.00% | 0.00% | 166.00 |
| 171 | Viêm xoang mạn tính - Chronic sinusitis | 7 | 1 | insufficient | 0.00% | 0.00% | 192.00 |
| 18 | Các bệnh do vi khuẩn khác - Other bacterial diseases | 7 | 1 | insufficient | 0.00% | 0.00% | 187.00 |
| 126 | Cơn thiếu máu não thoáng qua và các hội chứng tương tự - Transient cerebral ischaemic attacks and related syndromes | 6 | 1 | insufficient | 0.00% | 0.00% | 154.00 |
| 224 | Viêm vòi trứng và viêm buồng trứng - Salpingitis and oophoritis | 6 | 1 | insufficient | 0.00% | 0.00% | 155.00 |
| 258 | Không có, tịt hoặc hẹp ruột non - Absence, atresia and stenosis of small intestine | 4 | 1 | insufficient | 0.00% | 0.00% | 154.00 |
| 277 | Thương tổn do chấn thương ở mắt và hốc mắt - Injury of eye and orbit | 3 | 1 | insufficient | 0.00% | 0.00% | 220.00 |
| 148 | Bệnh tim thiếu máu cục bộ khác - Other ischaemic heart diseases | 2 | 1 | insufficient | 0.00% | 0.00% | 180.00 |
| 201 | Bệnh thoái hoá khớp - Arthrosis | 2 | 1 | insufficient | 0.00% | 0.00% | 201.00 |
| 155 | Tai biến mạch máu não, không xác định rõ chảy máu hoặc do nhồi máu - Stroke, not specified as haemorrhage or infarction | 1 | 1 | insufficient | 0.00% | 0.00% | 220.00 |
| 180 | Sâu răng - Dental caries | 1 | 1 | insufficient | 0.00% | 0.00% | 202.00 |
| 245 | Bệnh lí thai nhi và sơ sinh do biến chứng thai nghén, chửa, đẻ - Fetus and newborn affected by maternal factors and by complications of pregnancy, labour and delivery | 1 | 1 | insufficient | 0.00% | 0.00% | 177.00 |
| 60 | U ác dạ dày - Malignant neoplasm of stomach | 1 | 1 | insufficient | 0.00% | 0.00% | 212.00 |
| 205 | Trật đốt sống cổ và các đốt sống khác - Cervical and other interverbral disc disorders | 8 | 0 | insufficient | — | — | — |
| 297 | Tai nạn ngộ độc do các chất độc - Accident poisoning by and exposure to noxious substances | 8 | 0 | insufficient | — | — | — |
| 132 | Viêm giác mạc, tổn thương khác của củng mạc và giác mạc - Keratitis and other disorders of sclera and cornea. | 7 | 0 | insufficient | — | — | — |
| 62 | U ác chỗ nối trực tràng sigma, trực tràng, hậu môn và ống hậu môn - Malignant neoplasm of rectosigmoid function, rectum, anus and anal canal | 6 | 0 | insufficient | — | — | — |
| 159 | Nghẽn và huyết khối động mạch - Arterial embolism and thrombosis | 5 | 0 | insufficient | — | — | — |
| 290 | Tai nạn giao thông - Transport accidént | 5 | 0 | insufficient | — | — | — |
| 289 | Di chứng, thương tổn do chấn thương, do ngộ độc và hậu quả khác do nguyên nhân bên ngoài - Sequalae of injuries, of poisoning and of other consequences of external causes | 4 | 0 | insufficient | — | — | — |
| 13 | Các dạng uốn ván khác - Other tetanus | 3 | 0 | insufficient | — | — | — |
| 160 | Bệnh khác của động mạch, tiểu động mạch và mao mạch - Other diseases of arteries, arterioles and capillaries | 3 | 0 | insufficient | — | — | — |
| 101 | Tổn thương tuyến giáp liên quan đến thiếu iod - Iodine deficiency- related thyroid disorders | 2 | 0 | insufficient | — | — | — |
| 218 | Quá sản tuyến tiền liệt - Hyperplasia of prostate | 2 | 0 | insufficient | — | — | — |
| 135 | Glôcôm - Glaucoma | 1 | 0 | insufficient | — | — | — |
| 141 | Mất thính giác - Hearing loss | 1 | 0 | insufficient | — | — | — |
| 24 | Nhiễm khuẩn khác lây truyền qua đường tình dục - Other infection with a predominantly sexual mode of transmission | 1 | 0 | insufficient | — | — | — |
| 242 | Các biến chứng khác của chửa đẻ - Other complications pregnancy and delivery | 1 | 0 | insufficient | — | — | — |
| 247 | Các chấn thương sản khoa - Birth trauma | 1 | 0 | insufficient | — | — | — |
| 47 | Các nhiễm khuẩn do sán lá - Other fluke infections | 1 | 0 | insufficient | — | — | — |
| 48 | Sán Echinococ - Echinococcosis | 1 | 0 | insufficient | — | — | — |
| 73 | U ác vú - Malignant neoplasm of breast | 1 | 0 | insufficient | — | — | — |
| 9 | Dịch hạch - Plague | 1 | 0 | insufficient | — | — | — |
| 92 | U cơ trơn tử cung - Leiomyoma of uterus | 1 | 0 | insufficient | — | — | — |

## Kiểm tra thiên lệch về nhóm phổ biến

**Nhận định:** Có dấu hiệu tập trung rất mạnh vào một tập nhỏ các nhóm phổ biến.

- Model chỉ chọn 19/235 nhóm làm Top-1 ít nhất một lần trên TEST.
- 20 nhóm Top-1 phổ biến nhất chiếm 100.00% toàn bộ lượt dự đoán; 20 nhóm thực tế lớn nhất chiếm 68.74% lượt TEST.
- Trong 19 nhóm model từng chọn Top-1, 13 nhóm nằm trong 20 nhóm thực tế lớn nhất.
- Spearman giữa tần suất train và số lượt được dự đoán Top-1: 0.456; giữa tần suất TEST và số lượt dự đoán Top-1: 0.416.

### Tối đa 20 nhóm model dự đoán Top-1 nhiều nhất (19 nhóm có dự đoán khác 0)

| ID | Tên nhóm bệnh | Top-1 dự đoán | Tỷ trọng dự đoán | Thực tế TEST |
|---|---|---:|---:|---:|
| 169 | Các bệnh viêm phổi - Pneumonia | 30,783 | 65.01% | 7,398 |
| 87 | Bệnh bạch cầu - Leukaemia | 5,872 | 12.40% | 1,577 |
| 32 | Sốt virut khác do tiết túc truyền và sốt virus xuất huyết - Other arthropod | 3,836 | 8.10% | 828 |
| 259 | Dị tật bẩm sinh khác của bộ máy sinh dục tiết niệu - Other malformations of the genitourinary system | 1,957 | 4.13% | 2,181 |
| 170 | Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis | 1,316 | 2.78% | 2,775 |
| 204 | Bệnh của hệ thống tổ chức liên kết - Systematic connective tissue disorders | 1,007 | 2.13% | 389 |
| 165 | Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis | 751 | 1.59% | 2,518 |
| 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 601 | 1.27% | 907 |
| 313 | COVID-19 * U07.1 là bệnh nhân COVID-19 có kết quả xét nghiệm SARS-CoV-2 dương tính cập nhật theo hướng dẫn chẩn đoán và điều trị của Bộ Y tế. | 382 | 0.81% | 2 |
| 41 | Bệnh virut khác - Other viral diseases | 229 | 0.48% | 817 |
| 186 | Bệnh của ruột thừa - Diseases of appendix | 225 | 0.48% | 457 |
| 98 | Thiếu máu khác - Other anaemias | 89 | 0.19% | 472 |
| 99 | Tổn thương chảy máu, bệnh khác của máu và cơ quan tạo máu - Haemorrhagic conditions and other diseases of blood, blood | 70 | 0.15% | 901 |
| 190 | Tắc liệt ruột và tắc ruột không do thoát vị - Paralytic ileus, intestinal obstruction without hernia | 59 | 0.12% | 578 |
| 173 | Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids | 58 | 0.12% | 733 |
| 6 | Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases | 48 | 0.10% | 2,190 |
| 5 | Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. | 37 | 0.08% | 2,356 |
| 253 | Tổn thương khác có nguồn gốc trong thời kỳ chu sinh - Other conditions originating in the perinatal period | 17 | 0.04% | 725 |
| 200 | Viêm khớp dạng thấp và viêm khớp khác - Rheumatoid arthritis, other inflamatory polyarthropaties | 12 | 0.03% | 251 |

### 20 nhóm thực tế xuất hiện nhiều nhất trong TEST

| ID | Tên nhóm bệnh | Thực tế TEST | Tỷ trọng thực tế | Top-1 dự đoán |
|---|---|---:|---:|---:|
| 169 | Các bệnh viêm phổi - Pneumonia | 7,398 | 15.62% | 30,783 |
| 170 | Viêm phế quản và viêm tiểu phế quản cấp - Acute bronchitis and acute bronchiolitis | 2,775 | 5.86% | 1,316 |
| 165 | Viêm họng và viêm amidan cấp - Acute pharyngitis and acute tonsillitis | 2,518 | 5.32% | 751 |
| 5 | Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. | 2,356 | 4.98% | 37 |
| 6 | Các bệnh nhiễm khuẩn ruột khác - Other intestinal infectious diseases | 2,190 | 4.63% | 48 |
| 259 | Dị tật bẩm sinh khác của bộ máy sinh dục tiết niệu - Other malformations of the genitourinary system | 2,181 | 4.61% | 1,957 |
| 87 | Bệnh bạch cầu - Leukaemia | 1,577 | 3.33% | 5,872 |
| 35 | Sởi - Measles | 1,547 | 3.27% | 0 |
| 176 | Hen - Asthma | 1,162 | 2.45% | 0 |
| 270 | Các triệu chứng, dấu hiệu và kết quả bất thường về khám lâm sàng và xét nghiệm khác, chưa xếp ở chỗ khác - Other symptoms, signs and abnormal clinical and laboratory findings, not elsewhere classified | 1,132 | 2.39% | 0 |
| 274 | Gãy các phần khác của chi do lao động và giao thông - Fracture of other lim bones | 907 | 1.92% | 601 |
| 99 | Tổn thương chảy máu, bệnh khác của máu và cơ quan tạo máu - Haemorrhagic conditions and other diseases of blood, blood | 901 | 1.90% | 70 |
| 32 | Sốt virut khác do tiết túc truyền và sốt virus xuất huyết - Other arthropod | 828 | 1.75% | 3,836 |
| 41 | Bệnh virut khác - Other viral diseases | 817 | 1.73% | 229 |
| 124 | Động kinh - Epilepsy | 754 | 1.59% | 0 |
| 173 | Bệnh mạn tính của amidan và của VA - Chronic diseases of tonsils and adenoids | 733 | 1.55% | 58 |
| 253 | Tổn thương khác có nguồn gốc trong thời kỳ chu sinh - Other conditions originating in the perinatal period | 725 | 1.53% | 17 |
| 167 | Viêm cấp đường hô hấp trên khác - Other acute upper respiratory infections | 697 | 1.47% | 0 |
| 187 | Thoát vị bẹn - Inguinal hernia | 694 | 1.47% | 0 |
| 96 | U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour | 657 | 1.39% | 0 |

## Hạn chế diễn giải

- Một dòng dữ liệu là tổ hợp ngày/tuổi/giới/nhóm bệnh với `case_count`; đây không phải hồ sơ dự đoán độc lập theo từng bệnh nhân.
- Các lớp không xuất hiện trong train không thể được model dự đoán; chúng vẫn được tính là sai trong metric TEST đầy đủ.
- Average rank và recall mô tả khả năng xếp hạng trên tập lịch sử này, không chứng minh quan hệ nhân quả giữa thời tiết và bệnh.
- Chênh lệch nhỏ so với baseline cần được xem xét cùng mức tập trung dự đoán vào các nhóm phổ biến.

Chi tiết đầy đủ cho 235 nhóm nằm tại `reports/metrics/per_class_evaluation.csv`.
