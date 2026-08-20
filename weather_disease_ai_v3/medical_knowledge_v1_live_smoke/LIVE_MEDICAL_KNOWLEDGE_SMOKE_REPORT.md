# Weather AI V3 — Medical Knowledge V1 Live Smoke Re-validation

## Final result

- **Status:** `BLOCKED`
- **Decision:** `NEEDS_CORRECTION_BEFORE_APPROVAL`
- **Preflight completed:** `2026-08-19T11:32:09.6727099+07:00`
- **Timezone:** `Asia/Ho_Chi_Minh`
- **Reason:** production configuration reported all three required values as absent. The requested mandatory stop condition was therefore applied before temporary-database setup or any live request.

No production code was fixed. No draft was approved or published. Parent runtime was not changed.

## Environment verification

The generic `conda` command was not on this shell's `PATH`, but the exact Conda installation and requested environment were found and verified directly.

| Check | Observed | Result |
|---|---|---|
| Conda executable | `D:\Users\LENOVO\anaconda3\Scripts\conda.exe` | Verified |
| Conda version | `26.1.1` | Verified |
| Required environment | `seasonal_backend` | Verified |
| `sys.executable` | `D:\Users\LENOVO\anaconda3\envs\seasonal_backend\python.exe` | Verified |
| `sys.prefix` | `D:\Users\LENOVO\anaconda3\envs\seasonal_backend` | Verified |
| Python version | `3.11.15` | Verified |
| Project `.venv` used | No | Pass |
| Global/other Python used | No | Pass |

Both `sys.executable` and `sys.prefix` belong to the requested `seasonal_backend` environment.

## Configuration presence

Presence was checked through the production `app.config` module using the verified environment. Values were neither printed nor saved.

| Variable | Required | Present |
|---|---:|---:|
| `NCBI_EMAIL` | Yes | No |
| `OPENAI_API_KEY` | Yes | No |
| `OPENAI_MODEL` | Yes | No |
| `NCBI_API_KEY` | No | No |

The same required values were also absent from the current process, Conda environment metadata/activation scripts, and Windows user/machine environment configuration.

## Mandatory stop and request accounting

Because required configuration was missing:

- Temporary SQLite database created: **no**
- Production PubMed search requests: **0**
- PubMed import requests: **0**
- OpenAI generation requests: **0**
- Secondary LLM quality-review requests: **0**
- Web-search/tool requests by the model: **0**
- Patient data sent: **no**

## Live PubMed smoke

- Result: `BLOCKED`
- Planned case: A09 / gastroenteritis with precipitation, subject to canonical deployed-group confirmation
- Canonical deployed group confirmed: no; the run stopped before the application flow
- Production query: not generated
- Result count: `0`
- Imported sources: none
- Selected PMIDs: none

## Live LLM draft smoke

- Result: `BLOCKED`
- Provider: `openai`
- Model: unavailable because `OPENAI_MODEL` is absent
- Production service/prompt invoked: no
- Structured output received: no
- `store=false` live-verified: no request occurred
- Tools/web search enabled: no request occurred
- Main generation count: `0`

## Actual output and quality review

There is no actual model output to reproduce verbatim. The required fields are therefore reported exactly as absent rather than synthesized:

```json
{
  "evidence_level": null,
  "evidence_scope": null,
  "short_explanation_vi": null,
  "detailed_explanation_vi": null,
  "limitations_vi": null,
  "source_assessments": []
}
```

Manual comparison against selected PubMed abstracts was not possible because no PubMed search/import or LLM generation occurred.

| Review item | Result |
|---|---|
| Grounding classification | `NOT_RUN` |
| Causal overclaim | `NOT_RUN` |
| Unsupported mechanism | `NOT_RUN` |
| Fabricated numbers | `NOT_RUN` |
| Fabricated PMID/DOI/year/authors | `NOT_RUN` |
| Disease-subtype → whole-group overgeneralization | `NOT_RUN` |

No `SUPPORTED_BY_SELECTED_ABSTRACT`, `NOT_CLEARLY_SUPPORTED`, or `OVERCLAIM_RISK` judgment can truthfully be assigned without a draft and selected abstracts.

## Draft persistence checks

- DRAFT revision created in temporary DB: no
- `parent_display_allowed=false` verified: no
- `published_revision_id` unchanged in temporary DB: not applicable
- DRAFT readback: not run
- DRAFT edit: not run
- Provider called again on edit: no; edit was not run
- Approval/publish actions: none

## Integrity

### Production database

- Path: `seasonal_disease_backend/database.db`
- SHA-256 before: `D076B8BFDDFE870794A3308B62019E8E2EE31EB58FF8C6CFDDDEF0C5ECF48714`
- SHA-256 after: `D076B8BFDDFE870794A3308B62019E8E2EE31EB58FF8C6CFDDDEF0C5ECF48714`
- Size before/after: `188575744` bytes
- Modified time before/after: `2026-08-15T09:38:27.9239926Z`
- Unchanged: **yes**

### Production source code

- Fingerprint scope: `Frontend/src`, `seasonal_disease_backend/app`, backend `requirements.txt`, and frontend `package.json`; Python cache files excluded
- Files fingerprinted: `119`
- Aggregate SHA-256 before: `A3C596E02EA6D12A3BC80621B741AFF4931BB77251EBD2704AE4F11BF4100FC1`
- Aggregate SHA-256 after: `A3C596E02EA6D12A3BC80621B741AFF4931BB77251EBD2704AE4F11BF4100FC1`
- Modified by this validation: **no**

The repository already had uncommitted changes before this re-validation. Integrity is assessed relative to the preflight baseline, not to `HEAD`. Only the two requested report artifacts were rewritten by this task.

## Required remediation

Configure non-empty `NCBI_EMAIL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` values for the `seasonal_backend` execution context without committing secrets, then re-run this validation. No production-code bug was diagnosed by this blocked run.
