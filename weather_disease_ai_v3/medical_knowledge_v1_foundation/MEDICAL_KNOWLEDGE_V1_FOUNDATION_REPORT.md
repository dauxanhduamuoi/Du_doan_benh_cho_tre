# Medical Knowledge V1 Database Foundation Report

## Kết quả

**PASS** — Medical Knowledge V1 database foundation đã được triển khai và kiểm chứng độc lập với Weather AI runtime. Không có API/UI/workflow PubMed/LLM/publish nào được thêm.

## Audit stack và kiến trúc hiện có

- Backend: FastAPI `0.141.1`, Python `3.11.x` trong Conda environment `seasonal_backend`.
- ORM: SQLAlchemy `2.0.52`, declarative mapping bằng `DeclarativeBase`, `Mapped` và `mapped_column`.
- Database canonical: SQLite, URL `sqlite:///.../seasonal_disease_backend/database.db`, được định nghĩa duy nhất trong `app/database.py`.
- Migration framework trước task: không có Alembic hoặc framework migration/version table. Startup dùng `Base.metadata.create_all()` và một helper schema riêng cho area.
- Tổ chức trước task: model tập trung trong `app/models.py`, schema trong `app/schemas.py`, logic truy cập dữ liệu chủ yếu nằm trong router/service; chưa có repository pattern chung.
- Naming: tên bảng/cột `snake_case`; PK số nguyên; constraint/index có tên; timestamp là `DateTime` với `datetime.utcnow` (UTC không kèm timezone); trạng thái hiện hữu thường lưu dạng chuỗi.
- User/staff identity: bảng `users`, `users.id` là `INTEGER`; role lưu ở `users.role` (`admin`/`staff`). Các cột actor mới tham chiếu `users.id` và dùng `ON DELETE SET NULL`.
- SQLite foreign-key enforcement được bật bằng `PRAGMA foreign_keys=ON` cho connection của application. Điều này làm các FK mới có hiệu lực thực tế.

## Disease-group canonical identity

Weather AI V3 đọc catalog canonical từ `weather_disease_ai_v3/data/processed/disease_catalog.csv`, được trỏ bởi `WEATHER_AI_V3_DISEASE_CATALOG`. Catalog có cột `disease_group_id`; runtime chuẩn hóa ID bằng `str(...)`. Audit hiện tại ghi nhận 311 ID duy nhất.

Bảng `disease_codes` có `group_id VARCHAR(100)` nhưng một group lặp lại trên nhiều ICD row, không có unique constraint và không phải bảng catalog group độc lập. Vì vậy không thể tạo FK hợp lệ từ topic tới bảng này. Foundation lưu `disease_group_id VARCHAR(100)` để tương thích trực tiếp với Weather AI, không tạo catalog thứ hai và không migrate artifact vào database.

## Weather-factor vocabulary

Giá trị thực tế:

- `temperature`
- `humidity`
- `precipitation`
- `wind`
- `weather_condition`

Bốn giá trị đầu tái sử dụng đúng vocabulary lowercase mà `weather_ai_explanations.py` hiện trả về. `weather_condition` được bổ sung theo family V1 với cùng naming convention; không tạo biến thể uppercase song song.

## Schema đã triển khai

### `medical_knowledge_topics`

| Column | Type | Nullable | Ghi chú |
|---|---|---:|---|
| `id` | INTEGER | no | PK |
| `disease_group_id` | VARCHAR(100) | no | ID chuỗi tương thích Weather AI catalog |
| `weather_factor` | VARCHAR(32) | no | CHECK theo vocabulary V1 |
| `published_revision_id` | INTEGER | yes | FK revisions.id, `ON DELETE SET NULL` |
| `created_by` | INTEGER | yes | FK users.id, `ON DELETE SET NULL` |
| `created_at` | DATETIME | no | UTC default |
| `updated_at` | DATETIME | no | UTC default/on-update |

- Unique: `uq_medical_topics_group_factor(disease_group_id, weather_factor)`.
- Index: `ix_medical_topics_disease_group_id`.
- Circular reference được xử lý bằng cách tạo topic table trước revision table (SQLite cho phép referenced table được tạo sau), nullable pointer, `post_update` ở ORM và explicit nulling trong downgrade.
- Repository `set_published_revision()` kiểm tra revision phải thuộc chính topic trước khi gán.

### `medical_knowledge_revisions`

| Column | Type | Nullable | Ghi chú |
|---|---|---:|---|
| `id` | INTEGER | no | PK |
| `topic_id` | INTEGER | no | FK topics.id, `ON DELETE CASCADE` |
| `revision_number` | INTEGER | no | CHECK > 0 |
| `evidence_level` | VARCHAR(32) | no | CHECK vocabulary |
| `evidence_scope` | VARCHAR(20) | no | CHECK vocabulary |
| `short_explanation_vi` | TEXT | no |  |
| `detailed_explanation_vi` | TEXT | no |  |
| `limitations_vi` | TEXT | no |  |
| `status` | VARCHAR(16) | no | default `DRAFT`, CHECK vocabulary |
| `parent_display_allowed` | BOOLEAN | no | default false, CHECK boolean |
| `generated_by_llm` | BOOLEAN | no | default false, CHECK boolean |
| `llm_model` | VARCHAR(100) | yes | metadata only |
| `prompt_version` | VARCHAR(100) | yes | metadata only |
| `created_by` | INTEGER | yes | FK users.id, `ON DELETE SET NULL` |
| `reviewed_by` | INTEGER | yes | FK users.id, `ON DELETE SET NULL` |
| `review_note` | TEXT | yes |  |
| `created_at` | DATETIME | no | UTC default |
| `updated_at` | DATETIME | no | UTC default/on-update |
| `reviewed_at` | DATETIME | yes |  |

- Unique: `uq_medical_revisions_topic_number(topic_id, revision_number)`.
- Indexes: `ix_medical_revisions_topic_id`, `ix_medical_revisions_status`.
- Evidence level: `SUPPORTED`, `LIMITED_OR_INDIRECT`, `CONFLICTING`, `INSUFFICIENT`.
- Evidence scope: `WHOLE_GROUP`, `PARTIAL_GROUP`.
- Status: `DRAFT`, `APPROVED`, `REJECTED`.
- Xóa topic cascade revision riêng của topic; không cascade tới evidence source.

### `medical_evidence_sources`

| Column | Type | Nullable | Ghi chú |
|---|---|---:|---|
| `id` | INTEGER | no | PK |
| `source_type` | VARCHAR(16) | no | CHECK vocabulary |
| `pmid` | VARCHAR(32) | yes | indexed |
| `doi` | VARCHAR(255) | yes | indexed |
| `title` | TEXT | no |  |
| `authors` | TEXT | yes |  |
| `journal` | VARCHAR(255) | yes |  |
| `publication_year` | INTEGER | yes |  |
| `abstract_text` | TEXT | yes |  |
| `url` | TEXT | yes |  |
| `retrieved_at` | DATETIME | yes |  |
| `raw_metadata_json` | JSON | yes | SQLAlchemy JSON, serialized phù hợp SQLite |
| `created_at` | DATETIME | no | UTC default |

- Source type: `PUBMED`, `WHO`, `CDC`, `OTHER`.
- Indexes: `ix_medical_sources_pmid`, `ix_medical_sources_doi`, `ix_medical_sources_type`.
- PMID/DOI không đặt unique: task chưa xác định normalization/dedup policy và SQLite cho phép nhiều NULL; index thường hỗ trợ lookup mà không gây reject dữ liệu provider hợp lệ.

### `medical_revision_sources`

| Column | Type | Nullable | Ghi chú |
|---|---|---:|---|
| `revision_id` | INTEGER | no | composite PK; FK revisions.id, `ON DELETE CASCADE` |
| `source_id` | INTEGER | no | composite PK; FK sources.id, `ON DELETE CASCADE` |
| `source_role` | VARCHAR(16) | no | CHECK `PRIMARY`/`SUPPORTING` |
| `sort_order` | INTEGER | no | default 0, CHECK >= 0 |
| `relevance_note` | TEXT | yes |  |

- Unique: `uq_medical_revision_sources_pair(revision_id, source_id)`; composite PK cũng bảo vệ cặp này ở DB.
- Index: `ix_medical_revision_sources_source_id`; PK đã hỗ trợ lookup theo revision.
- Cascade chỉ xóa association khi revision/source bị xóa. Xóa topic không xóa evidence source dùng chung.

## Model, schema, repository và migration layout

- Model/domain constants: `seasonal_disease_backend/app/medical_knowledge_models.py`.
- Pydantic input validation: `seasonal_disease_backend/app/medical_knowledge_schemas.py`.
- Repository: `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`.
- Migration: `seasonal_disease_backend/migrations/v001_medical_knowledge_v1.py`.
- Focused tests: `seasonal_disease_backend/tests/test_medical_knowledge_foundation.py`.

Repository cung cấp create/get/list topic; lookup group+factor; create/get/list revision; create/get/list/search source; attach/list revision-source; và validation pointer cùng-topic. Repository chỉ `flush`, không tự `commit`, để caller sở hữu transaction. Không có import từ model runtime hoặc artifact mutation.

Do project chưa có migration framework, migration V1 là module SQLAlchemy nhỏ với `upgrade(bind)` và `downgrade(bind)`, không thêm Alembic/dependency mới. Upgrade tạo đúng bốn bảng theo thứ tự an toàn; downgrade chỉ xóa bốn bảng mới theo thứ tự an toàn và không chạm bảng/dữ liệu cũ.

## Files thay đổi

- `seasonal_disease_backend/app/database.py`: bật SQLite FK enforcement.
- `seasonal_disease_backend/app/main.py`: đăng ký model mới với `Base.metadata` để convention `create_all()` hiện tại tiếp tục hoạt động.

## Files thêm

- `seasonal_disease_backend/app/medical_knowledge_models.py`
- `seasonal_disease_backend/app/medical_knowledge_schemas.py`
- `seasonal_disease_backend/app/repositories/__init__.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/migrations/__init__.py`
- `seasonal_disease_backend/migrations/v001_medical_knowledge_v1.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_foundation.py`
- `weather_disease_ai_v3/medical_knowledge_v1_foundation/MEDICAL_KNOWLEDGE_V1_FOUNDATION_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_foundation/medical_knowledge_v1_validation.json`

## Tests và validation

- Focused foundation suite: **14 passed, 0 failed** (`pytest tests/test_medical_knowledge_foundation.py -q`).
- Full backend suite: **38 passed, 0 failed** (`pytest -q`), gồm 14 test mới và 24 test có trước.
- Migration trên SQLite tạm: upgrade **PASS**, downgrade **PASS**, re-upgrade **PASS**.
- Schema introspection: đủ 4 bảng, PK/FK/unique/index đúng thiết kế.
- FK runtime: **PASS**; orphan revision bị chặn và xóa published revision đặt pointer về NULL.
- Compile: `python -m compileall -q app migrations tests` **PASS**.
- Import/startup-module sanity: import `app.main:app` và kiểm tra FastAPI application **PASS**. Không chạy lifespan trên `database.db` thật để tránh tự ý mutate database hiện hữu.
- `git diff --check`: **PASS**.

## Compatibility và code-quality review

- Weather AI runtime, feature builder, model registry, ranking, SHAP, prediction response, public parent endpoint và Tier 2 runtime: **không thay đổi**.
- LightGBM/model artifacts, `medical_knowledge_base.json`, frontend: **không thay đổi**.
- Không training, tuning, đọc test target, gọi Internet/API, thêm PubMed, thêm LLM dependency, admin API/UI hay parent UI.
- Domain mới tách model/validation/repository/migration theo trách nhiệm; không tạo import cycle và không hardcode disease ID.
- Không refactor backend ngoài phạm vi. Thay đổi shared database connection chỉ bật enforcement cho FK đã khai báo.

## Decisions, deviations và limitations

1. Không có FK cho `disease_group_id`: canonical identity nằm trong Weather AI CSV artifact, chưa có bảng group unique phù hợp. Dùng `VARCHAR(100)` tương thích với runtime là lựa chọn ít xâm lấn nhất.
2. Không thêm Alembic: project chưa có migration framework. Migration reversible bằng SQLAlchemy phù hợp convention hiện tại nhưng chưa có version ledger/CLI tự động.
3. Model/schema mới dùng tên module riêng thay vì chuyển `app/models.py` và `app/schemas.py` thành package, tránh refactor/import break toàn backend.
4. `published_revision_id` cùng-topic được bảo vệ ở repository business validation; cross-table CHECK thuần SQLite không thể biểu diễn rule này. Caller tương lai phải dùng repository/service.
5. `APPROVED` không tự bật `parent_display_allowed` và không tự gán published pointer; workflow chưa thuộc task.
6. Timestamp giữ convention hiện hữu là naive UTC `DateTime`, chưa chuyển toàn hệ thống sang timezone-aware.
7. Chưa có dedup normalization cho PMID/DOI, catalog existence validation, API, authorization hay runtime lookup.

## NEXT step được khuyến nghị (không triển khai)

Thiết kế admin service/API cho source ingestion và draft/review/publish workflow, đồng thời validate `disease_group_id` qua canonical Weather AI catalog ở boundary. Trước khi production rollout, nên chọn một migration/versioning strategy chính thức cho toàn backend. Không thực hiện các bước này trong foundation hiện tại.

