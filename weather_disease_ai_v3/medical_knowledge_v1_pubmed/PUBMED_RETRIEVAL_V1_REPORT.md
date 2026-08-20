# PubMed Retrieval V1 Backend Report

## Status

**PASS** — PubMed Retrieval Backend V1 đã được triển khai với ESearch, batch EFetch, XML parsing, protected search/import endpoints và reuse PMID trong `medical_evidence_sources`. Không triển khai LLM, workflow, UI hay runtime Tier 2.

## Audit architecture

- Backend: FastAPI, router/service sync.
- ORM/database: SQLAlchemy 2.x và SQLite `database.db`; session đi qua `get_db()`.
- HTTP dependency có sẵn: `httpx 0.28.1`; không thêm dependency.
- Foundation xác nhận tồn tại đủ model/schema/repository/migration và bốn bảng Medical Knowledge V1.
- Repository convention: repository `flush`, caller/service sở hữu `commit`/`rollback`.
- Config convention: module-level values lấy từ `os.getenv()` trong `app/config.py`.
- Error convention: router map domain/provider error thành `HTTPException`, không trả stack trace.
- Router hiện hữu dùng `/api/...`; endpoint mới dùng prefix `/api/medical-knowledge/pubmed`.

## Auth findings

Authentication hiện hữu dùng OAuth2 Bearer JWT qua `get_current_user`. Role canonical được admin module giới hạn là `admin` và `staff`.

Dependency mới `require_staff_or_admin` tái sử dụng auth hiện hữu:

- anonymous/invalid token: `401` theo OAuth2/JWT convention;
- authenticated role ngoài `admin`/`staff`: `403`;
- `admin`: được phép search/import;
- `staff`: được phép search/import.

Không tạo auth framework hoặc permission store mới.

## Disease-group validation source

Validation đọc nhẹ `disease_order` và `model_count` từ deployment manifest:

`weather_disease_ai_v3/deployment/lightgbm_h14_weather/model_manifest.json`

Manifest hiện khai báo đúng 221 disease-group ID đã deploy. Loader chỉ đọc/cache JSON metadata và kiểm tra count/uniqueness; không import model registry, không load LightGBM booster và không đọc model artifact. ID request phải có trong universe này, nếu không trả `404`.

## HTTP client choice và NCBI config

Provider dùng sync `httpx.Client`, phù hợp router/service sync hiện tại. Official base URL cố định:

`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

Config environment:

- `NCBI_TOOL`: default `weather_ai_v3_medical_knowledge`, identifier không có space;
- `NCBI_EMAIL`: không có default giả; bắt buộc khi endpoint thực sự gọi provider;
- `NCBI_API_KEY`: optional.

Thiếu `NCBI_EMAIL` không làm application startup thất bại; PubMed endpoint trả lỗi cấu hình `503`. API key không được trả response, ghi raw metadata hay ghi log từ code. Request dùng POST form nên API key và query dài không nằm trong request URL/access log.

Theo hướng dẫn NCBI chính thức, limiter process-local giữ tối đa bảo thủ 3 request/giây khi không có key và 10 request/giây khi có key. Client có timeout 10 giây, tối đa 2 retries (3 attempts tổng), exponential bounded backoff, xử lý `429`, `5xx`, timeout và network errors. Retry không vô hạn. Tham chiếu: [NCBI E-utilities Help](https://www.ncbi.nlm.nih.gov/books/NBK25497/) và [NCBI E-utilities parameters](https://www.ncbi.nlm.nih.gov/books/NBK25499/).

## File layout

- API schema: `seasonal_disease_backend/app/pubmed_schemas.py`
- Query builder: `seasonal_disease_backend/app/services/pubmed_query_builder.py`
- NCBI client + XML parser: `seasonal_disease_backend/app/services/pubmed_client.py`
- Orchestration/database service: `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- Protected router: `seasonal_disease_backend/app/routers/medical_knowledge_pubmed.py`
- Provider/parser tests: `seasonal_disease_backend/tests/test_pubmed_client.py`
- Service/API/auth tests: `seasonal_disease_backend/tests/test_pubmed_api_service.py`

File lớn nhất trong production code là PubMed client/parser 269 dòng; mỗi file giữ một responsibility tương đối rõ. Không có import cycle.

## Query builder design

Query deterministic có hai component bắt buộc:

`(disease terms) AND (weather search terms)`

Mỗi term được quote và scope vào `[Title/Abstract]`. Request giới hạn tối đa 8 disease terms, mỗi term 2–120 ký tự; quote, square bracket và newline bị chặn để không phá cấu trúc query. `max_results` giới hạn 1–25. Optional `year_from`/`year_to` tạo PubMed publication-date range.

Weather search vocabulary tập trung:

| Medical Knowledge factor | PubMed search terms |
|---|---|
| `temperature` | temperature, heat, cold |
| `humidity` | humidity |
| `precipitation` | rainfall, precipitation, flood, flooding |
| `wind` | wind, wind speed |
| `weather_condition` | weather, meteorological conditions |

Các synonym chỉ là retrieval terms; code không coi chúng là evidence, không suy luận causality và không tạo medical explanation.

## Endpoint contracts

### `POST /api/medical-knowledge/pubmed/search`

Authenticated `admin`/`staff` only.

Request fields:

- `disease_group_id: string`;
- `weather_factor: string`;
- `disease_terms: string[1..8]`;
- `max_results: integer` (default 10, range 1–25);
- `year_from`, `year_to`: optional 1800–2100.

Response fields:

- `disease_group_id`, `weather_factor`, generated `query`;
- `count`: số structured result thực trả;
- `results[]`: `pmid`, `title`, nullable `authors`, `journal`, `publication_year`, `doi`, `abstract_text`, và `pubmed_url`.

Search chỉ discovery; không tự lưu kết quả.

### `POST /api/medical-knowledge/pubmed/import`

Authenticated `admin`/`staff` only. Request chỉ nhận `pmids` (1–25 numeric IDs), không nhận title/abstract từ frontend. Backend batch-fetch lại record từ PubMed rồi trả:

- `count`, `created_count`, `reused_count`;
- `sources[]`: database `id`, `pmid`, `created`, `title`, `retrieved_at`.

Không tạo topic/revision/link, không approve/publish.

## PubMed client và XML parser

Search pipeline:

1. ESearch nhận deterministic query và bounded `retmax`.
2. Parse `IdList`.
3. Nếu rỗng, trả empty list mà không gọi EFetch.
4. Nếu có ID, gửi toàn bộ bounded PMID list trong **một batch EFetch** với `retmode=xml`.

Parser dùng standard-library `xml.etree.ElementTree`, không dùng regex để parse XML structure. Regex chỉ được dùng sau XML parsing để trích năm bốn chữ số từ `MedlineDate`.

Parser xử lý:

- PMID và nested title text;
- personal author, initials fallback và collective author;
- DOI từ `ArticleId` hoặc `ELocationID`;
- journal title;
- Year, ArticleDate, DateCompleted hoặc năm trong MedlineDate;
- multi-section abstract đúng thứ tự, giữ label (`BACKGROUND: ... METHODS: ...`);
- missing DOI/abstract/year an toàn;
- malformed XML thành provider error;
- malformed individual article bị skip trong khi valid article khác vẫn được giữ.

## Import, dedup và database interaction

Sau khi hoàn tất network fetch, service mới query/write database, tránh giữ transaction mở trong lúc chờ NCBI. Record được map vào `medical_evidence_sources`:

- `source_type = PUBMED`;
- PMID, DOI, title, authors, journal, publication year, abstract, canonical PubMed URL;
- `retrieved_at` UTC theo timestamp convention hiện hữu;
- normalized `raw_metadata_json`: provider, PMID, DOI, publication types, languages, journal identifiers.

Repository bổ sung lookup `get_source_by_pmid()`. Nếu PMID PUBMED đã tồn tại, service reuse row và không tạo duplicate. Không thêm migration/unique constraint vì database hiện có thể đã chứa data và normalization/concurrent-write policy chưa được audit cho DB-level rollout; giới hạn race giữa các concurrent import được ghi ở limitations.

Service sở hữu `commit`/`rollback`; client/parser không biết database và repository không commit.

## Error mapping

| Condition | HTTP semantics |
|---|---:|
| Pydantic request validation | 422 |
| Disease group ngoài deployed universe | 404 |
| Anonymous/invalid authentication | 401 |
| Authenticated role không hợp lệ | 403 |
| Thiếu NCBI config/manifest inconsistency | 503 |
| NCBI 429 sau bounded retries | 503 |
| Timeout/network/5xx/invalid XML/provider error | 502 |
| Valid zero-result search | 200 + empty results |
| Unexpected internal failure | 500 generic detail |

Không trả absolute path, stack trace hoặc API key.

## Files added

- `seasonal_disease_backend/app/pubmed_schemas.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_pubmed.py`
- `seasonal_disease_backend/app/services/pubmed_query_builder.py`
- `seasonal_disease_backend/app/services/pubmed_client.py`
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- `seasonal_disease_backend/tests/test_pubmed_client.py`
- `seasonal_disease_backend/tests/test_pubmed_api_service.py`
- `weather_disease_ai_v3/medical_knowledge_v1_pubmed/PUBMED_RETRIEVAL_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_pubmed/pubmed_retrieval_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/config.py`: NCBI environment config.
- `seasonal_disease_backend/app/security.py`: reusable admin/staff dependency.
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`: PMID lookup.
- `seasonal_disease_backend/app/main.py`: include protected PubMed router.

Không có schema/migration mới trong PubMed task.

## Tests and validation

- Focused PubMed tests: **33 passed, 0 failed**.
- Foundation tests: **14 passed, 0 failed**.
- Full backend tests: **71 passed, 0 failed** (33 PubMed + 14 foundation + 24 existing backend/Weather AI).
- HTTP tests dùng `httpx.MockTransport`; không phụ thuộc Internet.
- Compile: `python -m compileall -q app migrations tests` — **PASS**.
- Import/startup-module sanity và xác nhận hai route — **PASS**.
- `git diff --check` — **PASS**.
- `LIVE_SMOKE_TEST = NOT_RUN`: environment không có `NCBI_EMAIL`; không tự bịa email và không gọi live provider.

## Code-quality và security review

- HTTP client không import FastAPI, DB hoặc Weather AI.
- Query builder không gọi network và có unit test độc lập.
- XML parser không nằm trong router.
- Router chỉ auth, call service và map exception.
- Service dùng deployment metadata, không load model registry/booster.
- API key không nằm trong response, raw metadata, URL hay application log message.
- Input/query/result count bị bound; retry hữu hạn; không polling/background/cache infrastructure.
- Không giữ DB transaction trong network wait.
- Không có secret/email cá nhân hardcoded.
- LightGBM unchanged; model artifacts unchanged; model registry unchanged; feature builder unchanged; SHAP unchanged; ranking unchanged; Weather AI response unchanged; Parent runtime unchanged; Tier 2 runtime unchanged; frontend unchanged; `medical_knowledge_base.json` unchanged.
- No LLM, OpenAI/Gemini/Claude, WHO/CDC/Crossref, training or tuning added.

## Remaining limitations

1. Rate limiter là process-local; deployment nhiều worker cần shared throttling/gateway nếu lưu lượng tăng.
2. Dedup PMID là lookup/reuse ở application layer; không bảo vệ tuyệt đối trước hai concurrent imports ở hai transaction/process khác nhau.
3. Chưa có scheduled/background ingestion, cache hoặc pagination ngoài bounded 25 result V1.
4. Không tự dịch disease group; admin/staff phải cung cấp verified English/search terms.
5. Parser tập trung PubmedArticle phổ biến; record hiếm/thiếu PMID/title bị skip an toàn.
6. Live NCBI behavior chưa smoke-test do thiếu `NCBI_EMAIL`; mocked provider boundary đã cover success/failure semantics.

## Recommended NEXT step (không triển khai)

Xây admin workflow để người dùng xem search result, chọn/reuse source và attach source vào revision draft. Trước production concurrency cao, audit data hiện có rồi cân nhắc partial/normalized unique strategy cho PubMed PMID và shared rate limiting. Không triển khai các bước này trong task hiện tại.

