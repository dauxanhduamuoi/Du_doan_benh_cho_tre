# Reviewed Multi-Provider Execution Audit & WHO Zero-Result Fix V1

Date: 2026-09-14
Branch: `feature/medical-knowledge-v1-20260820`
Baseline commit: `dca4c7d1d79ab3863601fb24691acafaec965085`

## Status

PASS.

Reviewed provider routing is independently verified for WHO-only, PubMed-only, PubMed+WHO, and a fake third provider. A selected provider cannot silently disappear from a successful response. Provider failure is represented as `PROVIDER_ERROR`; a successful invocation whose candidates fail local relevance is represented as `NO_RESULTS`.

No commit or push was performed. Existing uncommitted Medical Knowledge work was preserved.

## Exact root cause

There was no backend PubMed substitution and no PubMed prerequisite for WHO. The request schema preserved the selected provider IDs, settings validation checked that each was enabled for `REVIEWED`, registry resolution was provider-generic, and the orchestration loop called every selected provider independently.

The suspicious WHO zero was produced after provider execution: the current Reviewed safety rule requires a normalized candidate to match both a disease term and a factor term. Candidates missing either signal were correctly removed, but the previous response exposed only the combined relevant count. The UI therefore showed `0 kết quả phù hợp` without proving whether WHO had been called, whether the provider succeeded, or which local relevance gate removed the candidates.

The matcher also lacked the valid Reviewed humidity metadata term `moisture`. This task adds it to a Reviewed-only vocabulary; Auto vocabulary and qualification are unchanged. Disease matching remains mandatory, so generic moisture/child-health records are still rejected.

A separate frontend inconsistency existed: a single PubMed Guided selection could use the legacy PubMed endpoint, whereas WHO-only and multi-provider Guided selections used the provider endpoint. This did not suppress WHO, but it made Guided execution paths inconsistent. In a multi-provider-capable configuration, all Guided selections now use provider-neutral orchestration even when only one provider is selected. The legacy endpoint remains only for PubMed FREE mode and backward compatibility with a deployment whose settings inventory contains PubMed alone.

## Selected-provider trace

| Stage | Expected | Audited/current behavior |
|---|---|---|
| Frontend checkboxes | Preserve enabled user selection | `Set<string>` is serialized as the selected array; WHO-only sends `['WHO']` |
| API DTO | Preserve IDs, remove duplicate/case noise | `provider_ids` uppercases and deduplicates without inserting PubMed |
| Settings validation | Reject disabled providers | Requested IDs must be a subset of enabled `REVIEWED` IDs; no substitution occurs |
| Registry resolution | Resolve provider-specific implementation | Each selected ID is resolved with `registry.get(provider_id)` |
| Orchestration | Invoke every selected provider independently | Deterministic loop creates one result group per selected provider |
| Provider search | Use provider-owned query plan | WHO and PubMed receive their own builders; generic providers use the protocol fallback |
| Relevance | Apply local gates only when the attempt requests them | WHO requires disease + factor; PubMed fallback provenance remains unchanged |
| Response | Never hide selected groups | Success, no-results, and provider-error groups are all retained |
| Frontend | One tab per response group | WHO-only renders exactly WHO; mixed searches retain both tabs even on error/zero |

## Invocation evidence

Deterministic counter tests produced these results:

| Selection | PubMed calls | WHO calls | Other calls | Groups |
|---|---:|---:|---:|---|
| WHO only | 0 | 1 | 0 | WHO only |
| PubMed only | 1 | 0 | 0 | PubMed only |
| PubMed + WHO | 1 | 1 | 0 | PubMed and WHO |
| PubMed + WHO + FUTURE | 1 | 1 | 1 | all three, registry order |

The tests use one-attempt fake providers so the count proves routing rather than PubMed's intentional progressive query attempts.

## WHO query and relevance behavior

The deployed disease catalog contains `Dịch hạch - Plague`; `Plague` is therefore the canonical Reviewed English disease term. `Yersinia pestis` was not found in the deployed catalog and was not invented or hardcoded for disease ID 9.

Current WHO Reviewed query for the regression topic:

```text
Plague humidity relative humidity absolute humidity moisture children pediatric
```

Query construction and local relevance are separate:

- WHO receives bounded plain search terms with the disease anchor.
- Local matching reads only normalized title, available summary/abstract, publisher, and bounded explicit provider metadata.
- Matching uses NFKC normalization, case folding, punctuation/hyphen normalization, and whole normalized phrases.
- A title-only result cannot infer a factor that may exist on an unavailable page or summary.
- Disease and factor matches are counted independently before applying the conjunctive relevance rule.
- No arbitrary webpage fetch and no LLM classification is used.

Example successful-zero diagnostic now represented by the API:

```text
provider_invoked=true
provider_status=SUCCESS
raw=10
normalized=10
disease_match=2
factor_match=0
relevant=0
returned=0
group_status=NO_RESULTS
```

A timeout instead produces:

```text
provider_invoked=true
provider_status=PROVIDER_ERROR
group_status=PROVIDER_ERROR
safe_error_code=WHO_SEARCH_TIMEOUT
```

It is never labeled as evidence absence.

## Live WHO diagnostic

Exactly one live WHO provider search was run after all offline tests passed. It was a direct provider call with no database persistence.

```json
{
  "live_who_calls": 1,
  "query": "Plague humidity relative humidity absolute humidity moisture children pediatric",
  "provider_status": "SUCCESS",
  "provider_match_count": 294,
  "fetched_count": 10,
  "normalized_count": 10
}
```

This confirms that WHO was callable and returned raw candidates during this validation. It does not claim all ten candidates are relevant; the local disease+factor gate remains authoritative.

## UI behavior

- `SUCCESS`: displays the number of relevant results.
- `NO_RESULTS`: displays `0 kết quả phù hợp` and the no-matching-evidence panel.
- `PROVIDER_ERROR`: displays `Tạm thời không khả dụng`, never zero-result wording.
- WHO-only: exactly one WHO result tab; no PubMed request or query is generated in the multi-provider-capable Guided path.
- PubMed+WHO: both groups remain visible when either provider returns zero or errors.
- PubMed FREE mode remains PubMed-specific and excludes WHO intentionally.
- Technical details show provider name, called status, provider status, requested/effective limits, raw/normalized/disease/factor/relevant/returned counts, query attempts, and safe error codes. Raw response bodies and secrets are not exposed.

## Safety and compatibility

- Per-provider `N` remains unchanged.
- Source Library and mixed-provider import behavior remain unchanged.
- WHO trust, license, and metadata-only Draft rules remain unchanged.
- PubMed FREE mode behavior is unchanged.
- Auto Medical Knowledge behavior is unchanged.
- No database model, migration, or production data was changed.
- No SQLite-specific business SQL was added; SQL Server portability is preserved.
- Live calls: WHO 1, PubMed 0, Groq 0.

## Tests

| Validation | Result |
|---|---:|
| New backend execution audit tests | 15 passed |
| Focused backend routing/quality suites | 49 passed |
| Relevant backend settings/import/WHO/PubMed/Auto suites | 423 passed |
| Full backend suite | 853 passed |
| Medical Knowledge frontend component | 119 passed |
| Full frontend suite | 291 passed |
| TypeScript typecheck | passed |
| Frontend production build | passed, 2309 modules transformed |
| `git diff --check` | passed; line-ending notices only |

## Main implementation files

- `seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py`
- `seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py`
- `seasonal_disease_backend/app/services/auto_evidence_relevance.py`
- `seasonal_disease_backend/app/services/who_evidence_provider.py`
- `seasonal_disease_backend/tests/test_reviewed_provider_execution_fix_v1.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
