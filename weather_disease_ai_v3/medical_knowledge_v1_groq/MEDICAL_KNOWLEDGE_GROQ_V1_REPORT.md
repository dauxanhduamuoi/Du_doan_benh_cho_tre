# MEDICAL KNOWLEDGE GROQ V1 REPORT

## Status

**PASS** — Groq is now a third provider behind the existing `MedicalKnowledgeDraftGenerator` abstraction. Ollama and OpenAI remain intact, all provider selection stays centralized, strict structured output is enforced and revalidated, and all backend/frontend regression checks pass.

`GROQ_LIVE_TEST=NOT_RUN`: `GROQ_API_KEY` is not configured in the current environment. This is explicitly non-blocking. No Groq account, API key, payment method, tier upgrade, or billing action was created or attempted.

## Source audit

The implementation was based on the current workspace source: backend configuration and canonical `.env` loader, `.env.example`, requirements, provider protocol/factory, OpenAI and Ollama providers, provider-agnostic draft service, shared prompt, Pydantic proposal schema, draft/status/options/PubMed paths, backend tests, the admin service panel, frontend API types, and UI tests.

The code matched the prior Ollama report. The only architectural deviation from the new task's desired end state was the absence of Groq. `MedicalKnowledgeDraftService` was already provider-independent and required no Groq-specific change.

## Architecture before and after

Before:

```text
MedicalKnowledgeDraftGenerator
├── OllamaMedicalKnowledgeDraftGenerator
└── OpenAIMedicalKnowledgeDraftGenerator
```

After:

```text
MEDICAL_KNOWLEDGE_LLM_PROVIDER
                |
                v
create_medical_knowledge_draft_generator
        ├── groq   -> GroqMedicalKnowledgeDraftGenerator
        ├── ollama -> OllamaMedicalKnowledgeDraftGenerator
        ├── openai -> OpenAIMedicalKnowledgeDraftGenerator
        └── other  -> explicit configuration error
                |
                v
MedicalKnowledgeDraftGenerator protocol
                |
                v
MedicalKnowledgeDraftService
```

- There is no provider chain, nested fallback, or “try Groq, then OpenAI/Ollama” behavior.
- Groq lives in one cohesive provider module instead of expanding the existing multi-provider boundary into a monolith.
- The business service contains no Groq endpoint, payload, key, error, or provider-selection logic.

## Groq implementation and API choice

The provider reuses existing `httpx==0.28.1`; no Groq SDK or other dependency was added.

It uses exactly:

```text
POST https://api.groq.com/openai/v1/chat/completions
```

Chat Completions was selected instead of Groq's beta Responses API because Groq's stable [API reference](https://console.groq.com/docs/api-reference) documents the canonical endpoint and `response_format`, while the official [Structured Outputs guide](https://console.groq.com/docs/structured-outputs) provides strict-mode examples for that endpoint. This is the smallest implementation consistent with the existing HTTP-provider architecture.

The configured/recommended model is `openai/gpt-oss-20b`. Groq's current [model page](https://console.groq.com/docs/model/openai/gpt-oss-20b) lists JSON Schema Mode, and its Structured Outputs documentation lists this model among those supporting `strict: true`. `GROQ_MODEL` remains environment-configurable so a future deprecation requires configuration—not workflow code—changes.

Groq's current [rate-limit documentation](https://console.groq.com/docs/rate-limits) lists Free Plan limits for this model, but the project cannot determine the user's actual account tier or future policy. The UI therefore makes no “always free” or fixed-quota claim and states that usage depends on the account's limits/plan.

## Structured outputs and schema behavior

Generation uses this flow:

```text
MedicalKnowledgeDraftProposal.model_json_schema()
  -> small Groq strict-schema normalization
  -> response_format.type=json_schema
  -> json_schema.strict=true
  -> choices[0].message.content
  -> MedicalKnowledgeDraftProposal.model_validate_json()
```

- The existing medical proposal model is the only semantic schema.
- The strict schema preserves object shape, required fields, enums, `$defs`/references, and `additionalProperties=false`.
- A small tested helper removes only Pydantic length/item-count validation keywords not guaranteed by Groq's documented strict subset (`minLength`, `maxLength`, `minItems`, `maxItems`). The unchanged Pydantic model enforces those constraints again after receipt.
- All root and nested fields were audited as required; all objects are closed. No optional-field rewrite was needed.
- Valid output is parsed without regex. Invalid JSON, malformed responses, invalid evidence enums/scopes, or other Pydantic violations fail safely.
- Existing source-ID validation remains in the business service, so a hallucinated/unselected source ID cannot create a revision.

Request behavior is deterministic and bounded: `stream=false`, `temperature=0`, one request per explicit action, and no automatic retry. A 429 ends immediately; `Retry-After` is not used to launch another request. This avoids duplicate quota/charge surprises.

## Shared prompt and source-only grounding

Groq reuses the exact `SYSTEM_INSTRUCTIONS` and `build_generation_input` used by the other providers. Prompt version remains `medical_knowledge_v1`.

Only these fields are sent:

- canonical disease group metadata;
- selected weather factor;
- metadata and abstracts from selected imported PubMed sources.

No child age, gender, location, prediction request, JWT, user email, password, database dump, or API secret is included in the JSON body. The key exists only in the HTTPS `Authorization: Bearer ...` header to the canonical Groq host.

The request has no `tools`, `tool_choice`, `browser_search`, `code_interpreter`, remote MCP, function calling, or web-search capability. `citation_options=disabled` is explicit. Although GPT-OSS models can support browser/code tools, Groq's [browser-search documentation](https://console.groq.com/docs/tool-use/built-in-tools/browser-search) shows these capabilities require tool enablement and also notes browser search is incompatible with structured outputs; this workflow enables none of them.

## Endpoint and secret security

- The endpoint is a class constant; there is no configurable/arbitrary Groq base URL.
- HTTPS certificate verification remains enabled.
- Redirect following is explicitly disabled both on the production client and per request.
- 3xx responses are rejected. A mock test starts with a redirect-enabled injected client and proves only one request reaches `api.groq.com`; the key is never forwarded to the redirect host.
- `GROQ_API_KEY` is never returned by status APIs, sent to the frontend, written to localStorage/database/reports, included in a URL/query, or logged.
- Tests verify secrets are absent from request bodies, response APIs, and logs.

## Configuration and `.env.example`

Backend configuration now supports:

```dotenv
MEDICAL_KNOWLEDGE_LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
GROQ_TIMEOUT_SECONDS=45
```

- The implicit code default remains `ollama` for backward compatibility.
- `.env.example` explicitly recommends `groq`, while preserving complete optional Ollama and OpenAI sections.
- Groq readiness requires both key and model.
- When Groq is active, no OpenAI key/model or Ollama model is required.
- Configuration is not network-validated during startup.
- The real git-ignored `.env` was not modified. Its before/after SHA-256 is `CC5F8D478609467789FAB8DE4A6C56C888CF5F4683A1D413C46E846DB32FB18A`.

## Failure and rate-limit behavior

The manual status test maps failures without provider payloads or stack traces:

- missing key: `Chưa cấu hình GROQ_API_KEY.`
- invalid key (401/403): `Không thể xác thực với Groq.`
- missing/unavailable model: `Model Groq đã cấu hình không khả dụng.`
- 429: `Đã đạt giới hạn sử dụng Groq. Hãy thử lại sau.`
- timeout: `Groq phản hồi quá lâu.`
- invalid structured response: `Groq trả dữ liệu không đúng định dạng.`
- unavailable/5xx: `Hiện không thể kết nối Groq.`

Groq's official [error documentation](https://console.groq.com/docs/errors) confirms 404/429 semantics. There are zero automatic retries and zero fallback requests for all failures, including quota/rate limit.

## Service status and connection test

When Groq is active, status exposes only:

```json
{
  "configured": true,
  "provider": "groq",
  "mode": "cloud_api",
  "model": "openai/gpt-oss-20b",
  "api_key_configured": true,
  "local": false
}
```

The key value and Authorization header are never exposed. The existing LLM test route is provider-aware and runs only after an admin/staff click. Its Groq path sends one tiny strict-schema `{ "ok": true }` request with no PubMed, database write, patient data, tools, or draft creation.

## Frontend

`ServiceConfigurationPanel` shares one presentation and now handles all three providers:

- Groq: `Loại: API trực tuyến`, `Provider: Groq`, model, boolean key state, and `Kiểm tra kết nối`.
- Ollama: `Loại: AI cục bộ`, no API-key row, and `Kiểm tra AI cục bộ`.
- OpenAI: previous model/key/connection behavior preserved.

For Groq the panel explains that selected disease-group/weather/PubMed abstract content is sent to an external Groq server, no child data is sent, account limits/plan apply, and the project will not switch provider on failure/quota exhaustion. It does not claim medical authority, data-retention behavior, permanent free access, or a fixed quota.

Tests cover Groq rendering, online wording, model/key boolean, privacy wording, no raw key, manual-only call, loading/success, authentication/rate-limit errors, plus Ollama/OpenAI regressions. The draft-generation button and DRAFT editor remain unchanged; no Approve or Publish action was added.

In-app browser verification was **UNAVAILABLE** because no browser session was exposed. This does not block PASS because all component tests, the full frontend suite, typecheck, and production build passed.

## PubMed, DRAFT workflow, and metadata

- PubMed retrieval/import/query behavior is unchanged. Groq receives only sources already selected and imported through that flow and cannot independently search for evidence.
- Topic create/reuse, revision numbering, source attachment, readback, edit, and transaction behavior are unchanged.
- Generated revisions remain `DRAFT`, `generated_by_llm=true`, `parent_display_allowed=false`; `published_revision_id` remains unchanged.
- Provider failure creates no topic/revision/link partial write. Editing a DRAFT does not call any provider again.
- `llm_model` stores the exact configured model ID. No database migration/provider column was added because this task did not establish a requirement to change existing revision metadata semantics.

## Files added

- `seasonal_disease_backend/app/services/medical_knowledge_groq_generator.py`
- `seasonal_disease_backend/tests/test_groq_medical_knowledge_provider.py`
- `weather_disease_ai_v3/medical_knowledge_v1_groq/MEDICAL_KNOWLEDGE_GROQ_V1_REPORT.md`
- `weather_disease_ai_v3/medical_knowledge_v1_groq/medical_knowledge_groq_v1_validation.json`

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

## Dependency changes

None. `httpx` is reused; requirements were not modified by this task.

## Validation

Backend validation used only the verified environment:

- executable: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe`
- prefix: `D:\Users\LENOVO\anaconda3\envs\seasonal_backend`
- Python: `3.11.15`

| Check | Result |
|---|---:|
| Focused Groq/Ollama/factory/status/draft/PubMed tests | 157 passed |
| Full backend pytest | 195 passed, 0 failed |
| Python compileall | PASS |
| Backend startup import | PASS |
| Focused provider UI/workspace tests | 50 passed |
| Full frontend tests | 82 passed, 0 failed |
| Parent Weather AI frontend regression | 30 passed within full suite |
| TypeScript typecheck | PASS |
| Vite production build | PASS |
| `git diff --check` | PASS |
| Live Groq connection | NOT_RUN — key absent |

Production `database.db` remained byte-identical with SHA-256 `5C286FB98DB068A7C1F22D42741FB44E31A03F1C25FC24EF8C7400A8EFBC466D`. The 1,650-file non-task integrity scope remained identical before/after with aggregate SHA-256 `6915760D53E0B963DDB287493CC665C99A318B2A70954F73521B104DF2B76CE1`.

## Explicit confirmations

- No patient data sent.
- No Groq browser search, web search, tools, code interpreter, MCP, function calls, or external RAG.
- No automatic provider fallback or infinite/bounded retry; each action makes at most one Groq request.
- No payment, billing, tier upgrade, account, or key creation action.
- No approval or publish action.
- No Parent API/UI/runtime or Tier 2 integration change.
- No LightGBM, 221 deployed artifacts, feature builder, SHAP, ranking, `medical_knowledge_base.json`, training, tuning, or model-selection change.
- Ollama and OpenAI implementations remain present and their regressions pass.

## Remaining limitations and next manual setup

- A real Groq structured response was not tested because no key exists in the environment.
- Groq model availability, account tier, rate limits, pricing, and policies may change; the account's Groq Console remains the source of truth.
- Strict schema conformance does not guarantee medical factual quality. Every result remains an unpublished staff-reviewed DRAFT grounded only in selected abstracts.

Recommended manual next step: the user may obtain their own Groq API key from Groq Console, then set `MEDICAL_KNOWLEDGE_LLM_PROVIDER=groq`, `GROQ_API_KEY=<secret>`, and `GROQ_MODEL=openai/gpt-oss-20b` in `seasonal_disease_backend/.env`, restart the backend, and click **Kiểm tra kết nối**. This task intentionally did not create an account/key or perform any billing action.
