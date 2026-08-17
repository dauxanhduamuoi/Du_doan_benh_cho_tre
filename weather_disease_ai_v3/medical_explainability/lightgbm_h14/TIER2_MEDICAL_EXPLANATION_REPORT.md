# TẦNG 2 — Medical / Epidemiological Explanation Report

## Kết quả chính

Đã nghiên cứu **20/20 candidate** từ PRE-TIER-2 filtering.

| Trạng thái evidence | Số disease |
|---|---:|
| SUPPORTED | 1 |
| LIMITED_OR_INDIRECT | 10 |
| INSUFFICIENT | 7 |
| CONFLICTING | 2 |

Đây là knowledge layer giải thích mối liên hệ y khoa/dịch tễ có thể có giữa weather và disease group. Nó không thay đổi model, SHAP hoặc kết quả FINAL TEST.

## Disease có evidence weather rõ nhất

**Disease 5 — Ỉa chảy, viêm dạy dày, ruột non có nguồn gốc nhiễm khuẩn - Diarrhoea and gastroenteritis of presumed infectious origin. (A09)** có evidence rõ nhất. Systematic review quy mô lớn và hướng dẫn kỹ thuật WHO đều hỗ trợ liên hệ thống kê giữa bệnh tiêu chảy với nhiệt độ, mưa lớn/lũ, chất lượng nước và vệ sinh. Đây vẫn là association ở mức quần thể, không phải bằng chứng weather gây bệnh ở từng trẻ.

## Weather-heavy nhưng evidence y khoa chưa đủ

58 — U ác môi, khoang miệng, họng - Malignant neoplasm of lip, oral cavity and pharynx, 81 — U ác mắt và các phần phụ - Malignant neoplasm of eye and adnexa, 74 — U ác khác cơ quan sinh dục nữ - Malignant neoplasms of female genital organs, 96 — U khác insitu, lành tính và các u tiến triển không chắc chắn hoặc chưa rõ - Other insitus and benign neoplasms and neoplasms of uncertain or unknown behaviour, 83 — U ác các phần khác của hệ thần kinh trung ương - Malignant neoplasm of other parts of central nervous system, 69 — U ác xương và sụn khớp - Malignant neoplasms of bone and articular cartilage, 185 — Bệnh khác của thực quản, dạ dày và tá tràng - Other diseases of oesophagus, stomach, duodenum.

Các disease này vẫn weather-heavy theo model. `INSUFFICIENT` chỉ có nghĩa chưa có cơ sở y khoa đủ sát để tạo Tầng 2; không có nghĩa model chắc chắn sai.

## Evidence mâu thuẫn

161 — Viêm tĩnh mạch, viêm tĩnh mạch huyết khối, nghẽn mạch và huyết khối tĩnh mạch - Phlebitis, thrombophlebitis,venous embolism and thrombosis, 313 — COVID-19 * U07.1 là bệnh nhân COVID-19 có kết quả xét nghiệm SARS-CoV-2 dương tính cập nhật theo hướng dẫn chẩn đoán và điều trị của Bộ Y tế..

Với các record `CONFLICTING`, runtime chỉ hiển thị Tầng 1 và không hiển thị cơ chế y khoa.

## BROAD_DISEASE_GROUP

Có **16/20** candidate là nhóm rộng. Các nhóm này bao phủ nhiều mã ICD hoặc nhiều bệnh con, vì vậy không được lấy cơ chế của một bệnh con gán cho toàn bộ nhóm. Đáng chú ý gồm B15,B17-B19 (nhiều viêm gan virus), H60-H95 (nhiều bệnh tai), L10-L99 (rất nhiều bệnh da), D00-D48 (nhiều loại u) và các nhóm gãy xương.

## Weather factor có evidence tốt nhất

**Nhiệt độ và mưa lớn/lũ trong bệnh tiêu chảy nhiễm khuẩn/waterborne disease** có evidence tốt nhất trong 20 candidate. Cơ chế dịch tễ khả dĩ gồm thay đổi khả năng tồn tại/phát triển của tác nhân và ô nhiễm nước/thực phẩm; hiệu ứng bị sửa đổi mạnh bởi tác nhân cụ thể, nước sạch, vệ sinh và hành vi.

## Ví dụ tách Tầng 1 và Tầng 2

### Ví dụ 1 — A09: tiêu chảy/viêm dạ dày-ruột nghi nhiễm khuẩn

**Tầng 1 (chỉ khi local SHAP > 0):** “Trong bối cảnh hiện tại, nhiệt độ hoặc lượng mưa gần đây đang góp phần đẩy điểm xếp hạng nhóm bệnh này lên.”

**Tầng 2:** “Nhiệt độ có thể ảnh hưởng sự tồn tại/phát triển của một số tác nhân đường ruột; mưa lớn hoặc lũ có thể làm tăng ô nhiễm nước và thực phẩm. Mức liên hệ phụ thuộc tác nhân và điều kiện nước sạch, vệ sinh.”

### Ví dụ 2 — A06: amebiasis

**Tầng 1 (chỉ khi local SHAP của precipitation > 0):** “Lượng mưa trong những ngày gần đây đang góp phần đẩy điểm xếp hạng amebiasis lên.”

**Tầng 2:** “Amebiasis có thể lây qua nước hoặc thức ăn nhiễm Entamoeba histolytica. Mưa/lũ có thể làm tăng nguy cơ ô nhiễm nước, nhưng bằng chứng weather đặc hiệu cho amebiasis còn hạn chế.”

### Ví dụ 3 — G40-G41: động kinh/trạng thái động kinh

**Tầng 1 (chỉ khi local SHAP > 0):** “Nhiệt độ hoặc độ ẩm hiện tại đang góp phần làm nhóm này được model xếp hạng cao hơn.”

**Tầng 2:** “Một số nghiên cứu quan sát thấy nhiệt độ hoặc độ ẩm liên quan cơn co giật/lượt cấp cứu ở người đã có động kinh, nhưng kết quả chưa đủ nhất quán cho kết luận chung. Weather không được coi là nguyên nhân tạo ra bệnh động kinh.”

### Ví dụ 4 — nhóm gãy xương chi

**Tầng 1 (chỉ khi local SHAP của weather liên quan > 0):** “Điều kiện thời tiết hiện tại đang góp phần đẩy điểm xếp hạng nhóm gãy xương chi lên.”

**Tầng 2:** “Weather có thể thay đổi hoạt động ngoài trời, giao thông hoặc điều kiện bề mặt và từ đó liên quan số ca chấn thương. Chiều tác động khác nhau theo nơi và hành vi; weather không trực tiếp làm xương tự gãy.”


Trong mọi ví dụ: “Thông tin này nhằm hỗ trợ theo dõi và phòng ngừa, không thay thế chẩn đoán của bác sĩ.”

## Quy tắc runtime

1. Chỉ giải thích hướng xếp hạng bằng **local SHAP** của prediction hiện tại.
2. Chỉ feature có `local SHAP > 0` mới được mô tả là đẩy score xếp hạng lên.
3. Chỉ hiển thị Tầng 2 khi status là `SUPPORTED` hoặc `LIMITED_OR_INDIRECT`, `runtime_tier2_display_allowed=true`, và factor khớp knowledge base.
4. `INSUFFICIENT` hoặc `CONFLICTING`: chỉ hiển thị Tầng 1.
5. Không hiển thị Tầng 2 cho spina bifida trong runtime hiện tại vì weather lúc ghi nhận ca không đại diện phơi nhiễm thai kỳ.

## Giới hạn bắt buộc

- `mean(abs(SHAP))` chỉ đo độ lớn đóng góp, không cho biết chiều tăng/giảm.
- `weather_importance=0.40` không có nghĩa 40% bệnh do weather.
- Model score là điểm xếp hạng tương đối, không phải xác suất trẻ mắc bệnh.
- SHAP association không phải medical causality.
- Nhiều nguồn là nghiên cứu quan sát; confounding, seasonality, hành vi, chính sách và healthcare utilization có thể giải thích liên hệ.
- Cửa sổ current/3d/7d có thể không phù hợp với thời gian ủ bệnh, phát triển ung thư, dị tật thai hoặc bệnh mạn.
- Knowledge base này hỗ trợ theo dõi/phòng ngừa và không thay thế chẩn đoán bác sĩ.

## Nguồn và truy vết

Metadata của **26 nguồn** được lưu trong `sources/source_index.json`. Mỗi record trong matrix và JSON mang URL nguồn tương ứng; không có nguồn blog, Wikipedia, SEO, diễn đàn hay nội dung AI-generated.
