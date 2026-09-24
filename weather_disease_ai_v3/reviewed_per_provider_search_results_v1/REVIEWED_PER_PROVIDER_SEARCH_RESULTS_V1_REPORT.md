# Reviewed Medical Knowledge — Per-Provider Search Results V1

## STATUS

PASS — Reviewed search now treats `max_results` as the maximum for each selected provider, preserves provider groups and provider-specific failures, and supports selection/import across tabs. No commit or push was performed.

## Root-cause audit

The old Reviewed orchestration treated `max_results` as one shared global budget. It calculated `divmod(max_results, provider_count)`, assigned the quotient/remainder to providers in deterministic order, merged all returned records, performed cross-provider deduplication, and sliced the merged list again to `max_results`.

For example, two providers with `max_results=10` received about five slots each rather than ten each. The final ordered merge/dedup/slice also allowed earlier providers to consume the visible global cap, so a later provider could return fewer visible items or disappear without a provider-level state. The frontend then rendered the flat `results` array as one mixed list, which obscured the source-specific count and failure state.

## New Reviewed semantics

- `max_results=N` means up to `N` results for every selected Reviewed provider.
- The orchestrator does not divide `N` by provider count and does not apply a final global `N` slice.
- Each provider receives `effective_limit = min(N, provider.max_search_results)`. PubMed and WHO currently advertise a safe maximum of 25.
- Two providers at `N=10` can expose up to 20 candidates; at `N=20`, up to 40 candidates.
- Provider order remains deterministic from enabled settings/registry order.
- Query syntax is provider-owned through `build_reviewed_query`; the orchestrator remains provider-generic and the fake-third-provider test proves extension without provider-specific branching.

## Response DTO and provider grouping

The typed response now includes aggregate metadata plus `providers[]`. Each group contains:

- `provider_id`, `display_name`;
- `requested_count`, `effective_limit`, `returned_count`, `total_available`;
- `status`: `SUCCESS`, `NO_RESULTS`, or `PROVIDER_ERROR`;
- the provider-owned `query`, optional safe `warning`, and that provider's `results`.

Aggregate fields are `requested_count`, `provider_count`, `max_candidates`, `count`, and `unique_count`. The legacy additive `results`, `queries`, and `warnings` fields remain temporarily for import/client compatibility, but the new UI renders `providers[]` and does not default to one flat mixed list.

Provider exceptions produce a visible `PROVIDER_ERROR` group without discarding successful groups. A successful empty search produces `NO_RESULTS`, which is distinct from provider failure.

## Cross-provider dedup decision

Deduplication occurs inside each provider group before its effective limit is applied. A strong duplicate returned by two providers remains visible in both provider contexts, so one provider cannot visually hide another. `unique_count` uses the existing generic identity foundation to report unique evidence across all groups. Topic Source Library/import remains the authoritative downstream deduplication boundary, so duplicate evidence is not treated as independent downstream evidence.

## Frontend design

- Results render as provider tabs with friendly names, returned counts, selected counts, and provider status.
- The first non-error provider opens by default; only its cards are displayed.
- `PROVIDER_ERROR` and `NO_RESULTS` have separate provider-local messages.
- Selection keys use `provider_id:external_id`, survive tab changes, and show one global selected count plus per-provider counts.
- "Chọn tất cả" is scoped to the active provider. The final add action supports one mixed-provider request.
- Saved/reference-only/AI-readable states remain visible on result cards.

## Search modes and limits

Guided search uses provider-neutral wording and lets each provider build its own syntax. The main guided action is `Tìm tài liệu`.

Free query mode remains PubMed-specific and is explicitly labelled `Chỉ áp dụng cho PubMed / PMC`; non-PubMed providers are excluded/disabled in that mode. Direct PMID lookup is explicitly labelled as PubMed-only and does not imply WHO support.

The control is labelled `Số kết quả mỗi nguồn` and shows the selected-provider multiplication (for example, `2 nguồn × 20 → tối đa 40 kết quả`). This search-candidate limit is independent from AI Draft: Draft still accepts exactly 1–10 selected usable sources, with maximum 10.

## Safety and compatibility

- Auto discovery budgets and behavior were not changed by this feature and have a focused regression test.
- Provider settings semantics were not changed by this feature; only providers enabled for `REVIEWED` are selectable, independently from `AUTO`.
- WHO transport reliability, trust classification, license allowlist, evidence qualification, approval/publication, Parent visibility, and regeneration behavior were not changed.
- No database model or migration was added for this feature. No SQLite-specific business logic was added; repository/SQL Server portability is preserved.
- No production database, data, or jobs were touched.

## Validation

- Focused backend: `15 passed` in `tests/test_reviewed_per_provider_search_results_v1.py`.
- Full backend: `819 passed`.
- Focused frontend: `147 passed` across the Reviewed page and general-factor/form suites.
- Full frontend: `285 passed` across 12 test files.
- TypeScript: `tsc --noEmit -p tsconfig.json` passed.
- Production build: Vite build passed (2309 modules transformed).
- `git diff --check` passed; only Git's existing LF-to-CRLF working-copy notices were emitted.
- Tests used fakes/mocks. Live calls: Groq 0, PubMed 0, PMC 0, WHO 0, CDC 0.

## Git state

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting/current HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Git commit created: no.
- Git push performed: no.
