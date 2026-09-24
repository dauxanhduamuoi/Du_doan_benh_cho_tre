# WHO Reviewed Search — Bounded Relevant-Result Retrieval Fix V1

## Status

PASS. WHO Reviewed search now treats `N` as the maximum number of **relevant returned results**, not as the number of raw records fetched from page 0.

No commit was created and no push was performed.

## Exact old bug

The Reviewed orchestrator called WHO once with `max_results=N`, normalized only those first raw records, and then applied the strict local disease-and-factor relevance gate. A live observation showed `Total=294`, `fetched=10`, and `normalized=10`. If none of those first 10 records matched both anchors, the UI returned zero without examining the remaining WHO matches.

## Audited WHO pagination contract

- Existing official route retained: `GET https://www.who.int/publications/b/search/Publications`.
- Query parameters retained: `term`, `sort=0`, `pageSize`, and `pageNumber`.
- `pageNumber` is zero-based; the first page is `0`.
- `pageSize` is bounded by the provider at 25.
- Response pagination fields are `Total`, `PagesCount`, and `Results`.
- The provider reports `page_number` and `pages_count` to Reviewed orchestration.
- The route does not provide a uniqueness guarantee between pages, so cross-page duplicates are handled locally.
- Existing time, response-size, redirect, official-host, and JSON-shape safety controls remain in place.

## Chosen deterministic retrieval policy

This policy applies only to WHO in the Reviewed workflow:

- `batch_size = min(25, max(10, target_relevant))`
- `max_pages = 4`
- `max_raw_candidates = min(100, batch_size * 4)`
- Generic orchestration also clamps any provider policy to 25 records per page, 4 page requests, and 100 raw candidates.

Therefore, the normal `N=10` search can inspect at most four batches of 10 (40 raw candidates). The maximum allowed `N=25` can inspect at most 100 raw candidates. These limits follow the existing WHO 25-result provider ceiling and prevent unbounded retrieval.

## Retrieval and stopping behavior

For each WHO page, the service fetches official search metadata, normalizes it, deduplicates it, applies the existing strict disease and factor checks, and appends only unique relevant records. Retrieval stops when any of these occurs:

1. The relevant target `N` is reached (`TARGET_REACHED`).
2. `Total`, `PagesCount`, an empty/short terminal page, or the examined count shows that the provider is exhausted (`PROVIDER_EXHAUSTED`).
3. The page/raw-candidate budget is reached (`CANDIDATE_BUDGET_REACHED`).
4. A typed provider error occurs (`PROVIDER_ERROR`).

Returning fewer than `N`, including zero, remains valid. The relevance threshold is never weakened to fill the requested count.

## Relevance and duplicate handling

- WHO still requires a disease match **and** a factor match on the same normalized record.
- Reviewed humidity vocabulary still includes `moisture`.
- Existing Unicode, case, punctuation, and hyphen normalization remains active.
- No LLM classification, HTML/PDF scraping, OCR, browser rendering, arbitrary page fetch, or new endpoint was added.
- Candidates are deduplicated across pages and query attempts using existing strong identities: provider/external ID, canonical URL, and DOI where available. A repeated record cannot consume the relevant-result target twice.

## Partial provider failure

If WHO fails before any usable relevant result, the group remains `PROVIDER_ERROR`; a timeout is never converted to `NO_RESULTS`. If an earlier page produced valid relevant records and a later page fails, those records are retained, the group remains renderable as a successful partial result, and `provider_status`, the group warning, and the attempt stop reason expose the typed partial provider failure safely.

## Diagnostics and UI

The Reviewed response and technical panel now expose:

- `requested_relevant_count`
- `provider_total_available`
- `pages_fetched`
- `raw_candidates_examined`
- `normalized_candidates`
- disease, factor, relevant, and returned counts
- `budget_exhausted`
- `provider_exhausted`
- `stop_reason`

A successful WHO zero-result state explains how many raw WHO results were checked. Reaching the candidate budget is shown in technical diagnostics and is not displayed as an error banner.

## Isolated live WHO smoke

Run once on 2026-09-14 for `Plague + humidity`, `N=10`, WHO only:

| Diagnostic | Value |
|---|---:|
| WHO `Total` | 294 |
| Pages fetched | 4 |
| Raw candidates examined | 40 |
| Normalized candidates | 39 |
| Disease matches | 1 |
| Factor matches | 1 |
| Relevant (disease AND factor) | 0 |
| Returned | 0 |
| Provider exhausted | false |
| Budget exhausted | true |
| Stop reason | `CANDIDATE_BUDGET_REACHED` |

The smoke proves the corrected behavior: the provider inspected more than the first raw `N=10` candidates. The zero result is explainable because the disease and factor matches did not occur on the same record within the bounded search; quality was not weakened.

Live PubMed calls: 0. Live Groq calls: 0. Production data writes: 0.

## Compatibility and database

- Auto WHO discovery is unchanged and still calls its existing single bounded provider search.
- PubMed Reviewed behavior and its Guided fallback plan are unchanged.
- Per-provider `N` remains independent for PubMed and WHO.
- Draft eligibility is unchanged.
- WHO trust and license gates are unchanged.
- No database model/schema change or migration was added for this fix.
- No SQLite-specific business logic was added; SQL Server portability is preserved.

## Validation

- New bounded retrieval suite: 18 passed.
- Focused Reviewed/WHO/Settings/Import/PubMed/Auto regression set: 509 passed.
- Full backend suite: 871 passed.
- Full frontend suite: 292 passed.
- TypeScript typecheck: passed.
- Production build: passed.
- `git diff --check`: passed (line-ending notices only).

Repository state was preserved: **NO COMMIT**, **NO PUSH**, no reset, and no discarded work.
