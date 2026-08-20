# Weather AI V3 — Safe `.env` Configuration + Service Status UI

## Status

- **Status:** `PASS`
- **Completed at:** `2026-08-19T12:48:47.7334626+07:00`
- **Backend environment:** verified `seasonal_backend`
- **Python:** `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` (`3.11.15`)
- No approval or publication workflow was run.

## Config audit and dependency choice

The original `app/config.py` read configuration directly through `os.getenv(...)` and had no `.env` loader. `python-dotenv` was already installed in `seasonal_backend` (`1.2.2`) but was not declared in `requirements.txt`.

Implementation:

- declared `python-dotenv==1.2.2` in backend requirements;
- added one canonical loader in `app/config.py`;
- resolved the file from `Path(__file__)`, not the process working directory;
- canonical local file is `seasonal_disease_backend/.env`;
- loader runs once when backend config is imported;
- existing `os.getenv` constants and typed conversions remain the single config surface;
- no service, router, or `main.py` duplicates dotenv loading.

## `.env` behavior

- A local `seasonal_disease_backend/.env` was created because it did not exist.
- It contains only empty `NCBI_EMAIL`, `NCBI_API_KEY`, `OPENAI_API_KEY`, and `OPENAI_MODEL` entries.
- No fake email, fake API key, key-like placeholder, or real secret was inserted.
- Missing `.env` is safe: the loader returns without preventing application import/startup.
- Missing NCBI/OpenAI values remain optional at application startup.
- `load_dotenv(..., override=False)` ensures a real OS/System/Conda environment value takes priority over `.env`.
- Tests verified OS `OPENAI_MODEL=model-from-os` is not replaced by a different `.env` value.
- New values take effect on backend process restart; no secret hot-reload mechanism was added.

## `.env.example` and Git protection

- Added `seasonal_disease_backend/.env.example` with concise Vietnamese guidance.
- The example covers PubMed/NCBI, OpenAI, provider, prompt version, timeout, and bounded-input defaults.
- `.gitignore` now uses `.env`, `.env.*`, and `!.env.example`.
- `git check-ignore` result:
  - `seasonal_disease_backend/.env`: ignored;
  - `seasonal_disease_backend/.env.example`: not ignored and committable.

## Protected backend service status

Added admin/staff-only endpoints:

- `GET /api/medical-knowledge/service-status`
- `POST /api/medical-knowledge/service-status/pubmed/test`
- `POST /api/medical-knowledge/service-status/llm/test`

The status response exposes only:

- PubMed configured/email-configured/API-key-configured booleans;
- LLM configured/API-key-configured booleans;
- provider and non-secret model identifier.

It never returns the NCBI email, NCBI API key, OpenAI API key, or absolute `.env` path. Anonymous access returned `401` against the running local backend; unit tests verified unauthorized roles receive `403` and both admin/staff roles are allowed.

## PubMed connection test

- Reuses the production `PubMedClient`.
- Performs one small ESearch request with `retmax=1`.
- Does not fetch/import papers or create topics/revisions.
- Missing configuration maps to `503`; provider failure maps to a short safe `502` response.
- Unit tests verified Medical Knowledge database table counts remain unchanged.

`PUBMED_CONNECTION_LIVE = NOT_RUN` because `NCBI_EMAIL` is still empty.

## OpenAI connection test

- Reuses `OpenAIMedicalKnowledgeDraftGenerator` and its existing HTTP client lifecycle/error abstraction.
- Adds a minimal `test_connection()` operation; it does not use disease, PubMed, or patient data.
- Sends strict `json_schema` structured output for `{ "ok": true }`.
- Sends `store=false`.
- Supplies no tools and enables no web search.
- Uses the configured bounded provider timeout.
- Does not create a medical revision or write to the database.
- Missing configuration maps to `503`; provider/output failures map to a safe `502` response.

This request shape follows the [official OpenAI Responses API documentation](https://developers.openai.com/api/reference/java/resources/beta/subresources/responses) for JSON Schema structured output and stateless `store=false` operation.

`OPENAI_CONNECTION_LIVE = NOT_RUN` because `OPENAI_API_KEY` and `OPENAI_MODEL` are still empty.

## Admin UI

Added the compact `ServiceConfigurationPanel` to “Kho kiến thức y khoa”. It:

- loads service status only for the existing admin/staff workspace;
- shows configured/missing state for PubMed and OpenAI;
- shows the configured model identifier but never a key or email value;
- provides separate “Kiểm tra kết nối” buttons;
- never auto-runs either connection test on page load;
- displays the small-cost warning before the OpenAI action;
- shows safe loading/success/failure states;
- tells users to edit `seasonal_disease_backend/.env` and restart the backend;
- contains no secret editor and never stores configuration in localStorage.

Interactive in-app browser inspection was unavailable in this environment. UI behavior was instead validated by 12 focused component tests, the existing Medical Knowledge page tests, TypeScript typecheck, and a production build.

## Files added

- `seasonal_disease_backend/.env` — local and Git-ignored
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/app/routers/medical_knowledge_service_status.py`
- `seasonal_disease_backend/tests/test_service_configuration.py`
- `Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.tsx`
- `Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.test.tsx`
- `weather_disease_ai_v3/service_configuration_v1/SERVICE_CONFIGURATION_V1_REPORT.md`
- `weather_disease_ai_v3/service_configuration_v1/service_configuration_v1_validation.json`

## Files modified

- `.gitignore`
- `seasonal_disease_backend/requirements.txt`
- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/app/main.py`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

The worktree already contained the Medical Knowledge V1 work and other uncommitted changes before this task; those unrelated changes were preserved.

## Validation

| Validation | Result |
|---|---:|
| Focused backend config/service + existing Medical Knowledge tests | `78 passed` |
| Full backend pytest | `134 passed, 0 failed` |
| Focused service panel + Medical Knowledge page tests | `40 passed` |
| Full frontend tests | `72 passed, 0 failed` |
| Parent Weather AI frontend tests | `30 passed` within full suite |
| TypeScript typecheck | `PASS` |
| Vite production build | `PASS` |
| Python compileall | `PASS` |
| Backend import and route-registration sanity | `PASS` |
| Live local anonymous status protection | `401`, `PASS` |
| `git diff --check` | `PASS` |

## Security and integrity review

- No secret exposed through API or frontend.
- No secret logged or written to either report.
- No secret stored in the database or localStorage.
- No second PubMed HTTP implementation was added.
- No second OpenAI client was added.
- Connection-test actions contain no Medical Knowledge database write path; in-memory integration tests confirmed relevant table counts are unchanged.
- The existing development server was running with `uvicorn --reload`, so ordinary application reload activity changed the production DB file timestamp during source edits. This feature did not add a database model, migration, secret persistence, PubMed import, topic write, or revision write.
- Protected Weather AI/Parent/Tier 2 file fingerprint remained unchanged: `827A3255DD2D6631A8B01BE5711D8042AA808E82B54D777E26FF9C7548C8E021` across 239 files.
- No Parent runtime change.
- No LightGBM change.
- No SHAP change.
- No ranking change.
- No Tier 2 runtime change.
- No training or tuning run.

## Remaining limitations

- Real PubMed/OpenAI connectivity is not proven until the user fills the required `.env` values and explicitly presses the corresponding test button.
- Configuration is intentionally startup-scoped; the backend must be restarted after editing `.env`.
- Interactive browser visual inspection was unavailable; automated component tests and the production build passed.
