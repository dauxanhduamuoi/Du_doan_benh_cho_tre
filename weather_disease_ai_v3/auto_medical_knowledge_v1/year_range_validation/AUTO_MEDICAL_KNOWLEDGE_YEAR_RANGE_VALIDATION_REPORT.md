# Auto Medical Knowledge V1 — Year Range Validation

## Status

**PASS_WITH_NOTES**

The reported `2004-2009` rejection was a confirmed formatting false positive. A bounded temporal year-range representation was added to the existing numeric helper without changing any other Auto, Groq, discovery, Parent, or Reviewed behavior.

## Exact attempt audit

- Topic: `169 · wind`
- Job ID: `11`
- Reported attempt key: `11:1:2026-08-30T06:51:12.787258`
- Failure detail ID: `1378`
- Failure: `AUTO_OUTPUT_UNSUPPORTED_NUMBER`
- Field: `detailed_explanation_vi`
- Stored value: `2004-2009`
- Pipeline version: `auto_medical_knowledge_v1_compat`

The described attempt was found exactly. By audit time, the same durable job had a later attempt (`11:1:2026-08-30T06:55:27.513019`) with a different unsupported value, `3`. That later issue is outside this task and was not modified or retried.

## Exact selected evidence

The reported attempt selected exactly one source:

- Source ID: `60`
- PMID: `21672424`
- Evidence content ID: `55`
- Content kind/origin: `ABSTRACT` / `NCBI_PUBMED`
- Content SHA-256: `0d641fc8b1c547e6466b80df7b07de67067d54c43b379ad4b90896aa32eaa7d2`
- Retrieved at: `2026-08-29 06:30:08.075950`

The exact persisted evidence states that children were enrolled **between January 2004 and December 2009**. Therefore:

`YEAR_RANGE_SAMPLE = FALSE_POSITIVE`

No web search, model knowledge, PubMed request, or PMC request was used for this conclusion.

## Root cause and fix

The numeric helper already recognized dash and `to` ranges. Generated `2004-2009` became one range occurrence, but evidence text `between January 2004 and December 2009` was parsed as two standalone years because the existing range expression did not span month-qualified `between … and …` wording. Two standalone numbers cannot support a generated range, so the validator correctly failed under its old representation but incorrectly rejected semantically equivalent persisted evidence.

The fix remains inside `auto_medical_numeric_validation.py`:

- Calendar-like endpoints are conservatively bounded to four-digit research years (`1800` through `2100`).
- Equivalent temporal forms receive a dedicated key: `temporal-year-range:<start>:<end>`.
- Supported connectors include `-`, `–`, `—`, `to`, `đến`, and context-qualified `and`.
- `from … to …`, `between … and …`, and nearby Vietnamese/English study-period phrases are deterministic temporal signals.
- English month names/abbreviations are supported before or after each year, including `January 2004 to December 2009` and `2004 Jan – 2009 Dec`.
- Month precision is intentionally reduced only to the year interval; generated prose is never changed.
- A bare year-looking output may match only evidence that explicitly encodes a temporal interval. Bare or unrelated evidence years do not create support.

## Safety preserved

- Evidence `2010–2012` does not support output `2004–2009`.
- Evidence `2004–2009` does not support output `2004–2010`.
- Publication year `2004` plus unrelated `2009` does not form a range.
- Age range `4–18 years` does not support a calendar interval.
- Medical/percentage range `2–4%` does not support a calendar interval.
- A year-shaped range followed by `%` or a medical unit remains a numeric range, not a temporal range.
- Evidence with no period still rejects output `2004–2009` as `AUTO_OUTPUT_UNSUPPORTED_NUMBER`.
- The safe population-count rule `5087 ↔ 5.087` still passes only with count context.
- Standalone ambiguous `5.087` and genuinely unsupported medical numbers still fail.
- Causal, mechanism, pediatric, personalized-language, source-set, and provenance guards were untouched.

## Focused deterministic validation

- Focused numeric/Auto safety selection: **23 passed, 0 failed** (`53` unrelated tests deselected).
- Python helper/test compilation: **PASS**.
- Direct service/helper import: **PASS**.
- Frontend tests: **NOT_REQUIRED**; no frontend code changed.
- Whole backend regression: **NOT_RUN by scope policy**.
- Frontend build: **NOT_REQUIRED**.

E2E results:

- `AUTO_YEAR_RANGE_NORMALIZATION_E2E=PASS`: evidence contains `between January 2004 and December 2009`; provider output uses `giai đoạn 2004-2009`; job becomes `READY`, revision is persisted, and prose is byte-for-byte unchanged.
- `AUTO_YEAR_RANGE_HALLUCINATION_GUARD_E2E=PASS`: evidence period is `2010 to 2012`; provider output uses `2004-2009`; job becomes `FAILED` with `AUTO_OUTPUT_UNSUPPORTED_NUMBER`, and no revision is persisted.

## Files changed

- `seasonal_disease_backend/app/services/auto_medical_numeric_validation.py`
- `seasonal_disease_backend/tests/test_auto_medical_knowledge.py`
- the two requested artifacts in this directory.

No generation service, worker, cooldown, provider adapter, discovery code, frontend code, or Reviewed code changed.

## External calls and production integrity

- Groq calls: `0`
- PubMed calls: `0`
- PMC calls: `0`

Production database access was read-only. Initial and final logical hashes/counts were identical for Reviewed revisions/publications/source links, Auto topic states/revisions/source links/jobs/discoveries, and `PRAGMA foreign_key_check` returned no violations. No job was retried, no history was deleted, and no visibility/current pointer was changed.

## Remaining notes

- Month-level differences are not compared; only the year interval is validated, as intentionally bounded by this task.
- A bare evidence range such as `2004-2009` without temporal wording, month metadata, or a temporal connector remains unsupported. This is a deliberate fail-closed rule.
- The later stored failure value `3` on the same job was not investigated because it is outside the requested year-range edge case.

No manual test is required for this focused fix.
