# MEDICAL KNOWLEDGE MULTI-SOURCE LIBRARY IMPORT FIX V1

## STATUS

**PASS**

WHO metadata-only records can now be added to the Topic Source Library as reference-only items, trusted WHO evidence remains subject to backend trust/license validation, and mixed PubMed + WHO batches no longer fail as one unit when a single item cannot be resolved.

## Git safety

- Branch: `feature/medical-knowledge-v1-20260820`
- Starting and final HEAD: `dca4c7d1d79ab3863601fb24691acafaec965085`
- `git_commit_created=false`
- `git_push_performed=false`
- The pre-existing uncommitted WHO Provider V1 and Source Settings V1 work was preserved.
- No reset, checkout overwrite, discard, merge, rebase, tag, commit, or push was performed.

## Exact root cause

The real flow was traced from the multi-provider result card through selection, request serialization, `/api/medical-knowledge/providers/import`, `MedicalEvidenceReviewedService.import_sources`, provider lookup/enrichment, repository persistence, and the Topic Source Library response.

The failure had four connected causes:

1. The frontend import DTO contained only `provider_id` and `external_id`. All normalized metadata returned by the successful search was dropped.
2. The backend then required every item to be resolved again with `provider.lookup(external_id)`. PubMed has a stable PMID detail lookup. Real WHO Biblio search commonly returns a numeric Biblio identity such as `73164`, while the formally supported WHO REST detail route uses a UUID. Searching again by the numeric identity is not a deterministic detail lookup and can return no exact record.
3. Every source was resolved before persistence. A missing/error WHO lookup raised out of the loop, so one WHO item aborted the entire mixed PubMed + WHO request.
4. The response had no per-item outcome. The frontend could not distinguish added, reference-only, already-existing, invalid, or provider-error items; its generic failure mapping also used PubMed-specific wording.

No PMID requirement existed in the database model itself. The blocking assumption was the mandatory provider detail re-resolution plus all-or-nothing control flow at the generic import service boundary.

## Frontend request before and after

Before:

```json
{
  "provider_id": "WHO",
  "external_id": "73164"
}
```

After, the frontend constructs an explicit allowlisted DTO rather than spreading the search result:

```json
{
  "provider_id": "WHO",
  "external_id": "73164",
  "canonical_url": "https://www.who.int/publications/b/73164",
  "source_kind": "OTHER",
  "title": "...",
  "authors": null,
  "publisher_or_journal": "World Health Organization",
  "publication_date": "...",
  "publication_year": 2025,
  "doi": null
}
```

The strict backend DTO forbids extra fields. It has no `abstract_text`, `evidence_text`, `trust_class`, `license_allowlisted`, `license_name`, `license_url`, `content_hash`, or Draft-eligibility input. Tests explicitly prove that forged trust/license/evidence fields are rejected.

## Backend import path

The generic route remains additive and unchanged:

`POST /api/medical-knowledge/providers/import`

The service performs these steps for each item in request order:

1. Validate the selected provider against enabled `REVIEWED` settings.
2. Validate provider-neutral identity and bounded metadata.
3. For WHO, require HTTPS and an allowlisted official host.
4. Recognize a WHO Biblio reference only when its numeric external ID exactly matches `/publications/b/{external_id}` on `who.int` or `www.who.int` with no query component.
5. Store that validated Biblio item as metadata-only without arbitrary URL fetching and without accepting frontend medical content, license, or trust.
6. For directly resolvable provider identities, perform backend provider lookup/enrichment and require returned provider ID, external ID, and canonical URL to match the request.
7. Deduplicate through provider + external ID, PMID, DOI, and canonical URL using SQLAlchemy repository lookups.
8. Persist/link each valid item and return an outcome for every requested item.

No arbitrary URL is fetched. Provider lookup receives only a stable external ID; frontend title or other metadata is never sent as a provider search query, preventing client-supplied patient text from becoming an external query.

## WHO metadata-only semantics

A valid WHO Biblio identity and official canonical URL can be persisted with:

- `provider_id=WHO`;
- stable `external_id`;
- official canonical URL;
- normalized reference metadata;
- `pmid=NULL`;
- no evidence content row;
- `usable_for_draft=false`;
- outcome `ADDED_REFERENCE_ONLY`.

Frontend medical content, DOI used for trusted dedup, license, and trust are not accepted for this fallback. The Source Library displays **Đã lưu để tham khảo · không thể chọn cho AI Draft** and disables its Draft checkbox.

## WHO usable-evidence semantics

For a directly resolvable WHO identity, the backend provider remains authoritative. An immutable `OFFICIAL_SUMMARY_EXCERPT` snapshot is created only when the existing exact policy passes:

- `content_origin=WHO_PUBLICATIONS_API`;
- non-empty backend evidence text;
- allowlisted CC BY-NC-SA 3.0 IGO license URL;
- `license_allowlisted=true` in backend provenance;
- `full_text_stored=false`.

Only then can the result be `ADDED` with `usable_for_draft=true`. Existing disease, factor, pediatric, ownership, provenance, Reviewed setting, and Draft validation still apply. There is no WHO safety bypass.

## Mixed batch semantics

Batch validation/resolution is item-isolated. The response preserves request order and uses:

- `ADDED` — linked with usable backend evidence;
- `ADDED_REFERENCE_ONLY` — linked without Draft-eligible evidence;
- `ALREADY_EXISTS` — the exact topic link already exists;
- `REJECTED_INVALID` — malformed, mismatched, forged, or non-official identity;
- `PROVIDER_ERROR` — provider lookup is temporarily unavailable.

It also returns `requested_count`, `added_count`, `reference_only_count`, `already_exists_count`, `failed_count`, and total valid `count`. Malformed/provider-failed items do not prevent other valid items from being persisted. Unexpected database failures still roll back the transaction rather than reporting false partial durability.

## Duplicate and idempotency behavior

Repeated PubMed and WHO adds reuse the existing source and topic link. Same provider + external ID is checked first; PMID, DOI, and canonical URL provide provider-neutral fallback dedup. A duplicate item returns `ALREADY_EXISTS`, and no duplicate source or topic-link row is created. Canonical topic ownership remains exact: a global source can be linked deliberately to another topic, but it never leaks into an unrelated topic library.

## Frontend behavior and error feedback

After import, the page:

- immediately refreshes the Topic Source Library without a page reload;
- marks successful and already-existing result cards as saved;
- shows **Đã lưu để tham khảo** for WHO metadata-only results;
- removes successful items from the selected set while retaining failed items for retry;
- keeps Draft counts limited to backend-marked usable sources;
- shows `Đã thêm X/Y tài liệu. N tài liệu không thể thêm.` for partial success;
- shows a safe generic provider-import error for request-level failure and never exposes raw provider details.

## Files changed by this fix

- `seasonal_disease_backend/app/medical_evidence_reviewed_schemas.py`
- `seasonal_disease_backend/app/services/medical_evidence_reviewed_service.py`
- `seasonal_disease_backend/app/services/medical_knowledge_topic_source_service.py`
- `seasonal_disease_backend/app/repositories/medical_knowledge_repository.py`
- `seasonal_disease_backend/tests/test_medical_knowledge_multisource_import_fix_v1.py`
- `Frontend/src/lib/medicalKnowledgeApi.ts`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalKnowledgeResearchPage.test.tsx`
- `Frontend/src/app/components/medical-knowledge/MedicalTopicSourceLibrary.tsx`
- This report and validation JSON.

The worktree also contains earlier uncommitted WHO Provider V1 and Source Settings V1 files; they are intentionally not attributed to this fix and were not discarded.

## Validation

| Check | Result |
|---|---|
| New backend import-fix scenarios | 20 passed |
| Focused Reviewed page tests | 108 passed |
| Full backend suite | 799 passed |
| Full frontend suite | 278 passed |
| Python compile check | PASS |
| TypeScript `tsc --noEmit` | PASS |
| Vite production build | PASS |
| `git diff --check` | PASS (line-ending notices only) |

The backend suite covers provider architecture, WHO, Source Settings, Reviewed, Topic Source Library, Draft creation, PubMed import, Auto, visibility, Parent, migrations, and startup. The frontend suite covers settings, multi-provider search/import, Topic Source Library, Draft selection, Auto, and Parent rendering.

## External calls and production integrity

- Live Groq calls: 0
- Live PubMed calls: 0
- Live PMC calls: 0
- Live WHO calls: 0
- Live CDC calls: 0
- Production database writes: 0
- Production jobs started/retried: 0
- Schema changes: none
- Migration added: none

All provider behavior was validated with deterministic fakes and temporary in-memory databases.

## Database portability

No SQLite-specific business SQL was introduced. New duplicate lookups use SQLAlchemy expressions, portable equality/`IN` predicates, and `lower()` for normalized DOI comparison. The existing generic source/topic/content models are reused, so no schema or migration is required and the path remains suitable for SQL Server.

## Unchanged behavior

Provider Settings, PubMed provider behavior, WHO trust/license policy, Auto orchestration, Evidence Qualification, Strict, Basic, Safe Template, Reviewed approval/publication, Parent resolution, visibility, and regeneration semantics are unchanged. Maximum Draft source count is unchanged.

## Manual test required

`manual_test_required=true` for one final real-environment smoke test: enable WHO for Reviewed, search a real numeric WHO Biblio result, add it alone, then add a mixed PubMed + WHO selection and confirm the library badges. Automated validation deliberately made zero live provider calls and did not write the production database.

## Final declaration

```text
git_commit_created=false
git_push_performed=false
production_data_changed=false
```
