# Runtime Disease–Factor Relation Parity Audit V1

## Status

**PASS** — the real PubMed-shaped climate article and the deterministic relation contract now produce the same `DIRECT_TOPIC` result through the production Reviewed orchestration path.

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Final HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- Commit created: **NO**
- Push performed: **NO**
- Initial worktree: dirty before this task (30 modified entries and 43 untracked entries); all existing changes were preserved.
- Final worktree: still dirty and uncommitted by design. This task added one production-line change inside the already-untracked disease matcher, one runtime-parity test, one bounded PubMed fixture, and this report directory.

## Exact mismatch and root cause

For PMID 32517609, the actual PubMed EFetch record contained the complete abstract, 13 article-owned MeSH descriptors, and 5 author keywords. The abstract survived provider parsing, normalization, and semantic projection. The factor matcher found `humidity` in the abstract and the disease matcher returned `STRONG` because the exact `Plague` MeSH descriptor was present.

The bug was the disease matcher's controlled-heading early return. Once MeSH established a strong disease match, it returned only `article_mesh` spans and discarded valid occurrences of the same disease alias in the title, abstract, and article keywords. `DiseaseFactorRelationMatcher` therefore saw the humidity sentence but could not see that `plague`, `plague outbreaks`, occurrence, severity, and timing were in the same article-owned semantic unit. It conservatively returned `UNRESOLVED / INSUFFICIENT_LOCAL_TOPIC_CONTEXT`, which `ReviewedEvidenceRelevance` correctly mapped to `RELATED_CONTEXT`.

This was a semantic-boundary/span-propagation defect. It was not missing provider hydration, missing normalization, sentence segmentation, DTO mapping, or frontend rendering.

## Runtime trace for PMID 32517609

| Stage | Observation before fix |
|---|---|
| PubMed EFetch/parser | Abstract present; MeSH and author keywords present |
| `NormalizedMedicalEvidence` | Abstract, 13 MeSH terms, and 5 keywords present |
| `ReviewedSemanticEvidence` | Abstract present as 7 bounded units |
| Disease match | `STRONG / ARTICLE_MEDICAL_HEADING`; only MeSH span was returned |
| Factor match | `humidity`, field `abstract` |
| Relation | `UNRESOLVED / INSUFFICIENT_LOCAL_TOPIC_CONTEXT` |
| Final relevance | `RELATED_CONTEXT` |
| DTO/frontend | DTO preserved `RELATED_CONTEXT`; badge rendered that value correctly |

After the fix, disease strength and reason remain `STRONG / ARTICLE_MEDICAL_HEADING`, while the match result retains all article-owned occurrences of the confirmed alias (`title`, `abstract`, `article_keyword`, and `article_mesh`). The factor is still matched in `abstract`; relation becomes `RELATED_TO_TOPIC / EPIDEMIOLOGY_CONTEXT`; final relevance and DTO relevance are `DIRECT_TOPIC`.

The UI label `Chỉ metadata · lưu để tham khảo` is produced from Draft usability (`content_sha256` plus persisted evidence text), not from search-time abstract availability. The runtime DTO simultaneously contains the abstract and `usability=METADATA_ONLY`. That label did not cause relation loss.

## Data flow

Old flow:

`Guided UI -> provider search endpoint -> Reviewed orchestration -> PubMed ESearch -> one batched EFetch -> PubMed parser -> normalized evidence (abstract retained) -> semantic evidence (abstract retained) -> disease matcher (MeSH early return drops text spans) -> factor matcher -> relation UNRESOLVED -> RELATED DTO -> related badge`

New flow:

`Guided UI -> provider search endpoint -> Reviewed orchestration -> unchanged PubMed retrieval/normalization -> unchanged semantic evidence -> disease matcher (MeSH establishes STRONG and retains every article-owned alias span) -> unchanged factor matcher -> unchanged relation matcher -> DIRECT DTO -> direct badge`

No enrichment request, per-result fetch, persistence, or UI transformation was added.

## Generic fix

`DiseaseConceptMatcher` now separates two concerns correctly:

1. An exact article-controlled heading establishes strong disease identity.
2. All occurrences of that already-confirmed disease alias in article-owned fields remain available to downstream relation analysis.

The change contains no PMID, title, Plague, humidity, provider, or disease-ID branch. It applies uniformly to current and future providers that supply explicit article-owned semantic fields. The relation matcher remains deterministic, provider-neutral, network-free, and DB-free.

Production code contains none of `32517609`, `30017148`, `38257588`, or the audited titles.

## Runtime outcomes

| Case | Disease | Factor | Relation | Guided result |
|---|---|---|---|---|
| PMID 32517609, climate/plague | STRONG | humidity in abstract | `RELATED_TO_TOPIC / EPIDEMIOLOGY_CONTEXT` | `DIRECT_TOPIC` |
| PMID 30017148, vaccine storage | STRONG | humidity in abstract | `INCIDENTAL / STORAGE_FORMULATION_CONTEXT` | `RELATED_CONTEXT` |
| PMID 38257588, Smart Agriculture | WEAK | humidity in abstract | `UNRESOLVED` | `REJECT` (hidden from Guided) |
| SARS-CoV-2 humidity fixture | no strong Plague concept | humidity | not eligible for promotion | `REJECT` |
| Plague vector/ecology fixture | STRONG | humidity | `RELATED_TO_TOPIC` | `DIRECT_TOPIC` |

Exact PMID behavior is independent of Guided relevance. The runtime regression proves exact lookup still returns both PMID 30017148 and the Guided-rejected PMID 38257588 with `EXACT_LOOKUP` identity intact.

## Files changed by this task

- `seasonal_disease_backend/app/services/disease_concept_matcher.py`
  - Retain all article-owned disease spans after an exact controlled heading establishes `STRONG`.
- `seasonal_disease_backend/tests/fixtures/pubmed_32517609_efetch.xml`
  - Bounded archive of the real article-owned EFetch fields used by normalization/relevance.
- `seasonal_disease_backend/tests/test_runtime_disease_factor_relation_parity_v1.py`
  - Exercises parsed PubMed records through the production provider normalizer and Reviewed service; locks Guided and exact behavior.
- `weather_disease_ai_v3/runtime_disease_factor_relation_parity_v1/`
  - Audit report and machine-readable validation.

## Boundaries preserved

- Provider hydration changed: **NO**. PubMed search already used one batched EFetch after ESearch; no N+1 pattern was added.
- PubMed Guided queries/fallbacks changed: **NO**.
- PubMed FREE search changed: **NO**.
- Exact PMID lookup changed: **NO**.
- WHO retrieval, paging, relevance contract, and exact GUID lookup changed: **NO**.
- Auto discovery, qualification, modes, queue/state, visibility, and regeneration changed: **NO**.
- Source Library persistence/dedup and Draft eligibility changed: **NO**.
- DB schema or migration changed: **NO**.
- SQL Server portability affected: **NO**; no persistence/query code changed.
- Frontend changed by this task: **NO**.
- Production data changed: **NO**.

## Validation

- Pre-fix runtime parity reproduction: 1 failed, 1 passed; failure was exactly `UNRESOLVED` versus expected `RELATED_TO_TOPIC`.
- Runtime parity + relation tests: **20 passed**.
- Remaining focused Reviewed/PubMed/provider/exact/WHO/Auto-discovery tests: **223 passed**.
- Focused total: **243 passed**.
- Full backend: **948 passed**, 2,834 warnings.
- Full frontend: **305 passed**.
- TypeScript typecheck: **PASS**.
- Production build: **PASS**, 2,310 modules transformed.
- `git diff --check`: **PASS**.

Warnings are existing dependency and naive-UTC deprecations; no test failed.

## Live calls and limitations

- PubMed live calls: **1**, an exact EFetch for PMID 32517609, with no retry and no search call.
- WHO live calls: **0**.
- Groq live calls: **0**.

The archived PubMed fixture intentionally retains only bounded article-owned fields needed to reproduce parser/normalizer semantics rather than the entire 34,907-byte provider payload. Classification remains limited by the semantic content a provider supplies; absent evidence is conservatively not promoted to `DIRECT_TOPIC`.
