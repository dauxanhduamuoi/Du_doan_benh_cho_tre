# WHO Provider Runtime Search Reliability Fix V1 Report

## STATUS

`BLOCKED_WHO_SEARCH_CONTRACT`

The runtime failure was reproduced and isolated to a transport read timeout before WHO returned HTTP response headers. No parser, endpoint, redirect, response-size or timeout-limit change can be justified from the evidence collected. The adapter therefore remains fail-closed and the product keeps its existing per-provider degradation behavior.

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- `git_commit_created=false`
- `git_push_performed=false`

## Git safety and worktree

Initial status was intentionally dirty with the uncommitted WHO Provider V1, Source Settings V1 and Multi-Source Library Import Fix V1 work. All existing changes were preserved. The initial status contained 23 modified tracked files and the existing untracked provider/settings/migration/test/report paths listed by `git status --short`.

Final status remains intentionally dirty. No file was reset, overwritten from Git, committed or pushed. This task changed only the uncommitted WHO adapter/test files and added this report directory; the prior stacked work remains present.

## EXACT_REPRODUCED_FAILURE

The direct `WhoMedicalEvidenceProvider.search()` path used by Reviewed was exercised without persistence.

Reproduction 1:

- host: `www.who.int`
- path: `/publications/b/search/Publications`
- parameter names: `term`, `sort`, `pageSize`, `pageNumber`
- representative term: `influenza humidity children pediatric`
- timeout: 15 seconds
- outcome: `MedicalEvidenceProviderTimeoutError`
- HTTP status: unavailable because no headers arrived
- content type/content length: unavailable because no headers arrived
- redirect status: unavailable because no headers arrived

The current Reviewed query builder was also inspected offline. For Influenza + humidity it produces the provider-appropriate plain query `Influenza humidity relative humidity absolute humidity children pediatric`; it contains catalog disease aliases, factor vocabulary and pediatric terms and does not contain PubMed/MeSH syntax or patient data.

After offline tests, the final direct provider smoke used the shorter `Influenza humidity children` query through the same route and parameter contract. It also timed out before response headers. The typed diagnostic was:

- code: `WHO_SEARCH_TIMEOUT`
- stage: `transport`
- exception: `MedicalEvidenceProviderTimeoutError`

An independent bounded retrieval of that exact official route also timed out. This rules out the response parser as the current failing layer and shows that simply reducing term expansion does not restore service from this environment.

## Exact failing layer and root cause

Failure layer: `transport`.

The exact observable failure is that the official page-owned WHO Biblio search route does not deliver HTTP headers within the configured 15-second bounded timeout. DNS resolves, but there is no HTTP status, MIME type, content length, redirect or JSON body to inspect. Consequently:

- this is not a JSON wrapper/parser failure;
- this is not a MIME-type mismatch;
- this is not a response-size-limit failure;
- this is not an observed redirect, 403, 429, 404 or 5xx;
- the shorter query failing identically means query expansion is not the demonstrated root cause;
- increasing the timeout to the 30-second cap would be speculative and was not done.

## Current official WHO surface

Only official WHO sources were used:

- [WHO Publications search](https://www.who.int/publications/b/search) remains the official publication search UI and currently exposes keyword search and publication results.
- [WHO Publications REST API help](https://www.who.int/api/hubs/publications/sfhelp) still documents `GET /api/hubs/publications({key})` with a required `System.Guid` key.
- [WHO Publications](https://www.who.int/publications) still points users to WHO publication and repository surfaces.

No official evidence showed a replacement for the page-owned `/publications/b/search/Publications` search route. The route/parameters were therefore not changed and no Sitefinity/OData endpoint was invented. The stable documented UUID detail surface remains available as the Direct Lookup contract, but a live detail call was not made because the two-call provider smoke budget was exhausted.

## Code change

The transport/parser behavior remains bounded and fail-closed. The safe improvement is machine-readable diagnostics on existing typed WHO errors:

- `WHO_SEARCH_TIMEOUT`, with `stage=transport` or `stage=http`;
- `WHO_SEARCH_RATE_LIMITED`, preserving bounded `Retry-After` metadata;
- `WHO_SEARCH_HTTP_STATUS`;
- `WHO_SEARCH_BAD_CONTENT_TYPE`;
- `WHO_SEARCH_RESPONSE_SHAPE_CHANGED`;
- codes for redirect, malformed JSON/encoding, empty response and oversized response.

No raw response body is exposed. Existing exception inheritance is preserved, so Reviewed and Auto provider isolation continue to catch the same generic provider boundary errors. The Staff-facing generic warning remains unchanged.

No search-runtime fix is claimed: `who_search_runtime_fixed=false`. Per the task blocker rule, the implementation does not follow arbitrary redirects, crawl HTML/PDF, raise the response-size cap, increase timeout blindly, or fall back to an unofficial endpoint.

## Parser, transport and security

- Request construction continues to use standard `httpx` parameter encoding, including UTF-8.
- Accepted success MIME types remain `application/json` and `application/*+json`.
- Redirect following remains disabled; no redirect was observed in live reproduction.
- 429 remains typed and no retry loop was added; `Retry-After` is retained as safe diagnostic metadata.
- Timeout remains 15 seconds by default and capped at 30 seconds; it was not changed.
- Response reads remain bounded at the configured limit, capped at 5 MB; no limit was increased.
- Unknown JSON wrappers fail as `WHO_SEARCH_RESPONSE_SHAPE_CHANGED`; no generic recursive list finder was added.
- SSRF protections and the official-host allowlists are unchanged.

## Normalization, license and trust

Offline fixtures cover the official Biblio `Total`/`PagesCount`/`Results` wrapper and numeric identity `73164` with canonical URL `https://www.who.int/publications/b/73164`. Numeric Biblio IDs remain distinct from REST UUIDs. Metadata-only WHO records remain `UNTRUSTED`, contain no PMID requirement and remain Draft-ineligible.

The WHO license allowlist, summary-excerpt limit, trust classification, pediatric/disease/factor gates and Evidence Qualification behavior are unchanged. No HTML, PDF, OCR or full-text ingestion was added.

Because the current live endpoint produced no response body, a new current-date successful wire fixture could not honestly be captured. The tested Biblio fixture represents the previously observed official response contract; this limitation is recorded as `who_search_current_response_fixture=false`.

## Regression results

- Focused WHO/provider/settings/import architecture suite: `165 passed`.
- Complete backend suite: `804 passed`.
- `git diff --check`: passed (only existing line-ending notices).
- Frontend: not run because this task made no frontend/UI change.
- Schema/migration: no task change.
- Production DB: not opened or written.
- Production jobs: none started.

The passing backend suite includes PubMed behavior, Reviewed provider isolation, Source Settings defaults/toggles, Auto orchestration, WHO trust/qualification, WHO metadata-only library import, mixed PubMed+WHO import, Direct Lookup fixtures, 429, 5xx, timeout, invalid MIME, redirect, oversized response and unknown response shape.

Expected degradation remains:

- PubMed succeeds + WHO fails: PubMed results plus WHO warning.
- WHO succeeds + PubMed fails: WHO results plus PubMed warning.
- all selected providers fail: provider failure, not “insufficient evidence”.

No setting was mutated by provider failures. WHO was not auto-enabled.

## External calls

- `live_groq_calls=0`
- `live_pubmed_calls=0`
- `live_pmc_calls=0`
- `live_who_calls=2` direct isolated provider calls
- `live_cdc_calls=0`

Official WHO pages/documentation were additionally inspected through the research browser; these are source-verification reads, not application/provider smoke calls. No unrelated provider was contacted.

## Remaining limitation and product fallback

WHO Biblio search is a page-owned interface without the standalone specification/stability of the REST UUID detail API. It is currently not reachable within the application's bounded timeout from this environment. Direct Lookup remains implemented against the official UUID contract, but Biblio search cannot be marked operational until WHO returns a valid bounded JSON response again or publishes a stable replacement search contract.

Recommended fallback: keep WHO optional and independently controlled in Source Settings, preserve PubMed results and the WHO warning when the route is unavailable, and do not substitute arbitrary website crawling.

## Manual test required

When the WHO route is responsive again, in a non-production environment:

1. run one isolated provider search and confirm status 200, JSON MIME, bounded `Total`/`Results` shape and at least one normalized official URL;
2. enable WHO for Reviewed only, select PubMed + WHO and confirm merged results;
3. add one numeric WHO Biblio result to the Topic Source Library and confirm `usable_for_draft=false`;
4. disable WHO Reviewed again if operational stability is not acceptable.

Do not perform this retest by increasing the call budget in the current run. No commit or push was performed.
