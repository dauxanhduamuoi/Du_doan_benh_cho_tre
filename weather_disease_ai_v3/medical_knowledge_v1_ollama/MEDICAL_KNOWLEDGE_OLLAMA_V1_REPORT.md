# MEDICAL KNOWLEDGE OLLAMA V1 REPORT

## Status

**PASS** — Medical Knowledge V1 now has a local-only Ollama provider, Ollama is the default provider when the environment does not override it, OpenAI remains selectable, and the complete backend/frontend regression suite passes.

The optional live Ollama smoke is **UNAVAILABLE**, not a blocker: the active provider is `ollama`, the configured base URL is local, but `OLLAMA_MODEL` is empty and no process answered the read-only local `/api/tags` probe. No software or model was installed or downloaded.

## Source audit

The implementation was based on the current workspace source, including backend configuration and `.env` loading, `.env.example`, `requirements.txt`, the generator protocol and OpenAI implementation, draft service, shared prompt and Pydantic schema, Medical Knowledge/PubMed/status routers and tests, the admin workspace, service configuration panel, and frontend API layer.

The source differed from the desired end state in one important way: `MedicalKnowledgeDraftGenerator` already abstracted generation, but routers constructed `OpenAIMedicalKnowledgeDraftGenerator` directly and availability/status logic assumed OpenAI. The draft business service itself was already provider-agnostic and remains so.

## Architecture

```text
MEDICAL_KNOWLEDGE_LLM_PROVIDER
              |
              v
create_medical_knowledge_draft_generator
       |                         |
       v                         v
OllamaMedicalKnowledge-   OpenAIMedicalKnowledge-
DraftGenerator            DraftGenerator
       \                         /
        \                       /
         MedicalKnowledgeDraftGenerator
                       |
                       v
          MedicalKnowledgeDraftService
```

- Provider selection is centralized in one factory/configuration boundary.
- `provider=ollama` creates only the Ollama implementation.
- `provider=openai` preserves the existing OpenAI implementation.
- Unknown values raise an explicit configuration error; there is no implicit default or provider fallback at runtime.
- `MedicalKnowledgeDraftService` still depends only on `MedicalKnowledgeDraftGenerator` and contains no Ollama/OpenAI payload logic.

## Ollama provider

- Reuses the existing `httpx` dependency; no Ollama SDK or other dependency was added.
- Uses `GET /api/tags` to verify the configured model is present locally, then `POST /api/chat` with `stream=false`.
- Sends the existing `MedicalKnowledgeDraftProposal.model_json_schema()` directly as Ollama `format`.
- Reads `response.message.content` and validates it with the same Pydantic model; free-form regex parsing is not used.
- Sends `options.temperature=0` for deterministic drafting.
- Reuses the exact shared medical evidence system prompt and selected-source generation input.

This follows Ollama's official [structured output guidance](https://docs.ollama.com/capabilities/structured-outputs), [chat API](https://docs.ollama.com/api/chat), and [local model listing API](https://docs.ollama.com/api/tags). The retained OpenAI path still uses strict structured output and `store=false`, consistent with the official [Responses API](https://platform.openai.com/docs/api-reference/responses/create).

## Local-only and no-cost-surprise enforcement

- Only literal `http://127.0.0.1` and `http://localhost` endpoints are accepted.
- HTTPS, LAN/public IPs, arbitrary hostnames, credentials in URLs, URL paths, queries, fragments, and IPv6 alternatives are rejected before network access.
- No `Authorization` header and no `OLLAMA_API_KEY` exist in the implementation. Ollama documents that its local API does not require authentication; cloud authentication is separate ([official authentication documentation](https://docs.ollama.com/api/authentication)).
- Cloud-marked model identifiers such as `gpt-oss:120b-cloud` are rejected even if configured.
- Exact model presence in local `/api/tags` is required before chat.
- There is no OpenAI fallback, Ollama Cloud call, remote LLM call, auto-install, `ollama pull`, model download, preload, warm-up, scheduled call, or call during page load/startup/Parent prediction.
- Ollama is called only by the explicit connection-test action or explicit draft-generation action.

Mock boundary tests demonstrate `OPENAI_REQUEST_COUNT = 0` semantically: the Ollama factory returns only `OllamaMedicalKnowledgeDraftGenerator`, all observed requests target the configured loopback host, and connection failure terminates without constructing or invoking the OpenAI path.

## Configuration

New backend configuration:

```dotenv
MEDICAL_KNOWLEDGE_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=
OLLAMA_TIMEOUT_SECONDS=120
```

- The code default changed safely from `openai` to `ollama`.
- `.env.example` is Ollama-first, explains local operation in Vietnamese, leaves `OLLAMA_MODEL` blank because hardware/model licensing was not audited, and retains blank optional OpenAI fields.
- The real git-ignored `.env` was not modified. Its SHA-256 remained `CC5F8D478609467789FAB8DE4A6C56C888CF5F4683A1D413C46E846DB32FB18A` across final validation.
- When Ollama is active, `OPENAI_API_KEY` and `OPENAI_MODEL` may both remain empty.

## Grounding, prompt, and draft semantics

- The provider receives only canonical disease-group metadata, the selected weather factor, and selected imported PubMed metadata/abstracts.
- It receives no child age, gender, location, prediction payload, JWT, user identity, password, database dump, or secret.
- No web search, tool call, external RAG, or unselected evidence source is available.
- Existing conservative medical constraints remain shared: no diagnosis/patient advice, fabricated papers/identifiers/numbers, causal overclaim, or unsupported whole-group generalization.
- Output enums, scope, source assessments, and source-ID validation are unchanged. Hallucinated source IDs are still rejected by the business service.
- Revisions remain `DRAFT`, `parent_display_allowed=false`, `generated_by_llm=true`; source links and `prompt_version` are preserved; `published_revision_id` is unchanged; editing does not call the provider again; provider failure cannot create a half revision.
- `llm_model` stores the exact configured Ollama model identifier. No provider prefix or database migration was added because the existing field semantics are model identity and the active provider is already visible through configuration/status. This avoids an unnecessary schema change.

## Model existence and failure behavior

The connection and generation paths distinguish and safely expose:

- Ollama not running: `Không kết nối được AI cục bộ Ollama. Hãy mở Ollama trên máy và thử lại.`
- Model not selected: `Chưa chọn model AI cục bộ.`
- Model not installed: `Model AI cục bộ chưa được cài đặt trong Ollama.`
- Timeout: `AI cục bộ phản hồi quá lâu.`
- Invalid structured output: `AI cục bộ trả dữ liệu không đúng định dạng.`
- Unknown provider: `Cấu hình nhà cung cấp AI không hợp lệ.`

No raw provider response, stack trace, URL, or secret is returned by these paths.

## Service status and connection test

- Status reports the active provider, `mode`, `local`, configured model, and configuration readiness without exposing the base URL or any API key.
- For Ollama, configuration readiness requires a valid loopback base URL and a non-cloud model name; process reachability remains a connection state.
- The existing `/api/medical-knowledge/service-status/llm/test` route is provider-aware.
- Its Ollama path lists local models and makes one minimal structured chat request only after an explicit admin/staff click.
- It makes no database write, PubMed request, OpenAI request, patient-data request, or automatic model pull.

## Frontend

- The service panel shows `AI tạo bản nháp`, `Loại: AI cục bộ`, `Provider: Ollama`, the selected model or `Chưa chọn`, and `Kiểm tra AI cục bộ`.
- It does not render an API-key row for Ollama.
- Its helper states: `Ollama chạy trực tiếp trên máy này. Không sử dụng OpenAI API cho provider hiện tại.`
- Loading, success, Ollama-unavailable, missing-model, and model-not-installed states are covered.
- OpenAI rendering and its explicit connection path remain compatible.
- The Medical Knowledge draft button/form and DRAFT workflow are unchanged; no Approve or Publish action was added.
- In-app browser verification was **UNAVAILABLE** because no browser session was exposed. This is non-blocking because the component tests, full frontend suite, typecheck, and production build all passed.

## Files added

- `seasonal_disease_backend/tests/test_ollama_medical_knowledge_provider.py`
- `weather_disease_ai_v3/medical_knowledge_v1_ollama/MEDICAL_KNOWLEDGE_OLLAMA_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_ollama/medical_knowledge_ollama_v1_validation.json`

## Files modified

- `seasonal_disease_backend/app/config.py`
- `seasonal_disease_backend/.env.example`
- `seasonal_disease_backend/app/services/medical_knowledge_draft_generator.py`
- `seasonal_disease_backend/app/services/medical_knowledge_pubmed_service.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_drafts.py`
- `seasonal_disease_backend/app/routers/medical_knowledge_service_status.py`
- `seasonal_disease_backend/tests/test_service_configuration.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.tsx`
- `Frontend/src/app/components/medical-knowledge/ServiceConfigurationPanel.test.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`

## Dependency changes

None. The implementation reuses `httpx==0.28.1`; it does not add an Ollama SDK.

## Validation

All backend commands used the verified environment:

- executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`
- prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`
- Python: `3.11.15`

| Check | Result |
|---|---:|
| Focused Ollama/provider/draft/status/PubMed backend tests | 120 passed |
| Full backend pytest | 158 passed, 0 failed |
| Python compileall | PASS |
| Backend startup import | PASS |
| Focused service panel/workspace tests | 45 passed |
| Full frontend tests | 77 passed, 0 failed |
| Parent Weather AI frontend regression tests | 30 passed within full suite |
| TypeScript typecheck | PASS |
| Vite production build | PASS |
| `git diff --check` | PASS |
| Optional live Ollama test | UNAVAILABLE (not installed/running or not reachable; no model selected) |

The production database was not used by provider tests and remained byte-identical: SHA-256 before/after `5C286FB98DB068A7C1F22D42741FB44E31A03F1C25FC24EF8C7400A8EFBC466D`. A 1,647-file non-task integrity scope also remained identical before/after with aggregate SHA-256 `500A602E15FC68B2AA369DDA573079877BF501A27956C338DD97EA51322441AC`.

## Explicit integrity confirmation

- PubMed behavior/provider: unchanged.
- OpenAI provider: preserved and covered by regression tests.
- OpenAI request while Ollama active: none.
- Ollama Cloud or remote request: none.
- Automatic model install/download/pull: none.
- Patient data, web search, or tools: none.
- Approval/publish: none.
- Parent runtime/Tier 2 integration: unchanged.
- LightGBM, all deployed model artifacts, feature builder, SHAP, ranking, and `medical_knowledge_base.json`: unchanged.
- Training, tuning, model selection: not run.

## Remaining limitations and manual next step

- No live local model response was validated because Ollama did not answer locally and `OLLAMA_MODEL` is not selected.
- Output quality, latency, RAM/GPU use, and model license depend on the model the user chooses. Every generated result remains a staff-reviewed DRAFT.

Recommended manual next step: install/start Ollama yourself, choose and install a model appropriate for the machine and its license, set only `OLLAMA_MODEL=<exact local model identifier>` in `seasonal_disease_backend/.env`, restart the backend, then click **Kiểm tra AI cục bộ**. This task intentionally did not install Ollama or pull a model.
