from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import mssql

from app.database import get_db
from app.medical_knowledge_models import MedicalEvidenceContent as Content, MedicalEvidenceSource as Source, MedicalKnowledgeTopicSource as Membership
from app.parent_trusted_reference_models import ParentTrustedReferenceApproval as Approval
from app.repositories.parent_trusted_reference_repository import ParentTrustedReferenceRepository
from app.routers.public import router as public_router
from app.routers.parent_trusted_references import router as staff_router
from app.security import create_access_token
from app.services.parent_trusted_reference_curation_service import CurationSelector, ParentTrustedReferenceCurationService
from app.services.parent_trusted_reference_identity import CURATION_POLICY_VERSION, build_parent_reference_identity
from app.services.trusted_reference_read_service import TrustedReferenceReadService
from app.trusted_reference_schemas import TrustedReferenceBatchRequest

from test_trusted_references_public import (
    db, client, isolate_external_and_legacy_paths,  # noqa: F401 - isolated fixtures / offline guards
    source, topic, revision, curate, read, read_guard, selector, forbidden,
)


def setup_approval(db, *, disease="005", approved=True, legacy=False):
    stored = source(db)
    selected_topic = topic(db, selector(disease))
    if legacy:
        revision(db, selected_topic, [(stored, 0)])
    row = curate(db, selected_topic, [(stored, 0)], approved=approved)[0]
    return stored, selected_topic, row


def visible(db, *selected):
    return [item.source_id for item in read(db, *(selected or [selector("005")])).items[0].references]


def approval_state(db, approval_id):
    return ParentTrustedReferenceRepository(db).get_persisted_state(approval_id)


def mutate(db, model, row_id, **values):
    db.execute(update(model).where(model.id == row_id).values(**values), execution_options={"synchronize_session": False})
    db.commit()


def bound_identity(db, stored, selected_topic, row):
    state = approval_state(db, row.approval_id)
    selected = dict(disease_group_id=selected_topic.disease_group_id, factor_type=selected_topic.factor_type,
                    factor_key=selected_topic.factor_key, factor_value=selected_topic.factor_value)
    src = dict(db.execute(select(*Source.__table__.c).where(Source.id == stored.id)).mappings().one())
    proof = dict(db.execute(select(*Content.__table__.c).where(Content.id == state["evidence_content_id"])).mappings().one())
    return build_parent_reference_identity(selected, src, proof)


def test_shared_builder_preserves_pre_extraction_phase_b_hash():
    selected = selector("005")
    src = dict(id=1, provider_id="WHO", source_type="WHO", external_id="1", source_kind="GUIDELINE",
               url="https://www.who.int/publications/b/1", title="WHO guidance", journal="WHO", publication_year=2025)
    proof = dict(id=1, source_id=1, content_kind="OFFICIAL_SUMMARY_EXCERPT", content_origin="WHO_PUBLICATIONS_API",
                 external_identifier="1", content_sha256="a" * 64, provenance_json=dict(
                     provider_id="WHO", external_id="1", canonical_url=src["url"], retrieval_surface="WHO_BIBLIO_SEARCH",
                     metadata_storage_allowed=True, full_text_stored=False))
    snapshot, digest = build_parent_reference_identity(selected, src, proof)
    # Recorded using actual Phase B _identity before extracting its implementation.
    assert digest == "8e3c6fbfbc8d4aeda4f709af28242d4a870ae420d5db634295908c39e4627f5e"
    reordered = dict(reversed(list(proof["provenance_json"].items())))
    assert build_parent_reference_identity(dict(reversed(list(selected.items()))), src,
                                          {**proof, "provenance_json": reordered}) == (snapshot, digest)


def test_valid_approved_without_any_reviewed_revision_is_visible(db):
    _stored, _topic, row = setup_approval(db)
    assert visible(db) == [10]
    assert approval_state(db, row.approval_id)["version"] == 2


@pytest.mark.parametrize("status", ["DRAFT", "REVOKED"])
def test_draft_and_revoked_are_hidden_even_with_legacy_publication(db, status):
    _stored, _topic, row = setup_approval(db, approved=status == "REVOKED", legacy=True)
    if status == "REVOKED":
        ParentTrustedReferenceCurationService(db).revoke(row.approval_id, expected_version=2, actor_id=9990)
    assert visible(db) == []


def test_no_curation_no_fallback_or_union_with_published_reviewed(db):
    selected_topic = topic(db, selector("005"))
    legacy_only = source(db, 20)
    revision(db, selected_topic, [(legacy_only, 0)])
    assert visible(db) == []  # Guard forbids even invoking the legacy projection.
    stored = source(db, 10)
    curate(db, selected_topic, [(stored, 2)])
    assert visible(db) == [10]  # No UNION with legacy source 20.


def test_membership_loss_hides_without_repair_or_curation_mutation(db):
    _stored, selected_topic, row = setup_approval(db)
    before = approval_state(db, row.approval_id)
    db.execute(delete(Membership).where(Membership.topic_id == selected_topic.id))
    db.commit()
    assert visible(db) == []
    assert approval_state(db, row.approval_id) == before
    assert db.scalar(select(Membership.source_id).where(Membership.topic_id == selected_topic.id)) is None


@pytest.mark.parametrize("fault", ["unbound", "deleted_proof", "other_source"])
def test_only_existing_exact_owned_proof_is_used(db, fault):
    _stored, _topic, row = setup_approval(db)
    current = approval_state(db, row.approval_id)
    if fault == "other_source":
        other = source(db, 20)
        other_proof = db.scalar(select(Content.id).where(Content.source_id == other.id))
        mutate(db, Approval, row.approval_id, evidence_content_id=other_proof)
    else:
        mutate(db, Approval, row.approval_id, evidence_content_id=None)
        if fault == "deleted_proof":
            db.execute(delete(Content).where(Content.id == current["evidence_content_id"]))
            db.commit()
    before = approval_state(db, row.approval_id)
    assert visible(db) == []
    assert approval_state(db, row.approval_id) == before


@pytest.mark.parametrize("wrong", [selector("5"), selector("6"), selector("005", key="temperature"),
    selector("005", factor_type="SEASONALITY", key="time_of_year"),
    selector("005", factor_type="AGE", key="age_group", value="1-5 tuổi")])
def test_full_selector_identity_including_leading_zero_is_required(db, wrong):
    setup_approval(db)
    assert visible(db, wrong) == []
    assert visible(db) == [10]


def test_weather_nonnull_cannot_match_null_projection(db):
    setup_approval(db)
    with read_guard(db):
        assert ParentTrustedReferenceRepository(db).get_approved_reference_metadata([
            ("005", "WEATHER", "humidity", "not-null"),
        ]) == []


@pytest.mark.parametrize("values", [dict(title="Changed"), dict(journal="Changed"), dict(publication_year=2026),
    dict(url="https://www.who.int/publications/b/20"), dict(source_kind="HEALTH_GUIDANCE"), dict(external_id="20")])
def test_source_identity_drift_hides_and_never_repairs_hash(db, values):
    stored, _topic, row = setup_approval(db)
    before = approval_state(db, row.approval_id)
    mutate(db, Source, stored.id, **values)
    assert visible(db) == []
    assert approval_state(db, row.approval_id) == before


@pytest.mark.parametrize("values", [dict(content_sha256="c" * 64), dict(external_identifier="different"),
    dict(content_origin="NCBI_PUBMED"), dict(content_kind="ABSTRACT"), dict(provenance_json=None),
    dict(provenance_json=[]), dict(provenance_json={"provider_id": "WHO"})])
def test_proof_identity_drift_or_malformed_provenance_fail_closed(db, values):
    _stored, _topic, row = setup_approval(db)
    before = approval_state(db, row.approval_id)
    mutate(db, Content, before["evidence_content_id"], **values)
    assert visible(db) == [] and approval_state(db, row.approval_id) == before


@pytest.mark.parametrize("values", [dict(identity_sha256=None), dict(identity_sha256="0" * 64),
    dict(identity_snapshot_json=None), dict(identity_snapshot_json={"corrupt": True}),
    dict(policy_version="old-policy"), dict(revoked_by=9990)])
def test_inconsistent_approval_identity_or_revocation_is_hidden(db, values):
    _stored, _topic, row = setup_approval(db)
    mutate(db, Approval, row.approval_id, **values)
    before = approval_state(db, row.approval_id)
    assert visible(db) == [] and approval_state(db, row.approval_id) == before


@pytest.mark.parametrize("source_changes,proof_changes,decision", [
    (dict(provider_id="PUBMED", source_type="PUBMED"), {}, "STAFF_ONLY"),
    (dict(url="https://spoof.example/source"), {}, "REJECT_PARENT_REFERENCE"),
    (dict(provider_id="UNKNOWN"), {}, "UNCERTAIN"),
    ({}, dict(retrieval_surface="UNVERIFIED"), "UNCERTAIN"),
    ({}, dict(full_text_stored=True), "UNCERTAIN"),
])
def test_current_policy_required_even_if_persisted_fingerprint_matches(db, source_changes, proof_changes, decision):
    stored, selected_topic, row = setup_approval(db)
    if source_changes:
        mutate(db, Source, stored.id, **source_changes)
    if proof_changes:
        proof_id = approval_state(db, row.approval_id)["evidence_content_id"]
        provenance = db.scalar(select(Content.provenance_json).where(Content.id == proof_id))
        mutate(db, Content, proof_id, provenance_json={**provenance, **proof_changes})
    snapshot, digest = bound_identity(db, stored, selected_topic, row)
    # Isolated fault injection: an imported/forged APPROVED hash cannot override policy.
    mutate(db, Approval, row.approval_id, identity_snapshot_json=snapshot, identity_sha256=digest)
    rows = ParentTrustedReferenceRepository(db).get_approved_reference_metadata([("005", "WEATHER", "humidity", None)])
    assert len(rows) == 1  # Candidate with matching identity, denied by current policy.
    from app.services.trusted_reference_source_policy import TrustedReferenceSourceMetadata, evaluate_trusted_reference_source
    policy = evaluate_trusted_reference_source(TrustedReferenceSourceMetadata(**{
        key: rows[0][key] for key in TrustedReferenceSourceMetadata.__dataclass_fields__
    }))
    assert policy.decision.value == decision
    before = approval_state(db, row.approval_id)
    assert visible(db) == [] and approval_state(db, row.approval_id) == before


def test_body_license_and_unrelated_provider_payload_do_not_affect_eligibility(db):
    stored, _topic, row = setup_approval(db)
    proof_id = approval_state(db, row.approval_id)["evidence_content_id"]
    provenance = db.scalar(select(Content.provenance_json).where(Content.id == proof_id))
    mutate(db, Source, stored.id, abstract_text="PRIVATE BODY", raw_metadata_json={"secret": "PRIVATE RAW"})
    mutate(db, Content, proof_id, evidence_text="", license_name=None, license_url=None,
           provenance_json={**provenance, "api_key": "PRIVATE KEY", "generated_prose": "PRIVATE PROSE"})
    assert visible(db) == [10]


def test_normalized_url_and_reordered_proof_identity_remain_compatible(db):
    stored, _topic, row = setup_approval(db)
    proof_id = approval_state(db, row.approval_id)["evidence_content_id"]
    proof = db.scalar(select(Content.provenance_json).where(Content.id == proof_id))
    mutate(db, Source, stored.id, url="https://WWW.WHO.INT:443/publications/b/10/#fragment")
    mutate(db, Content, proof_id, provenance_json=dict(reversed(list(proof.items()))))
    assert visible(db) == [10]


def test_same_source_keeps_isolation_between_selectors_without_cross_dedup(db):
    stored = source(db)
    first, second = topic(db, selector("005")), topic(db, selector("5"))
    curate(db, first, [(stored, 1)])
    curate(db, second, [(stored, 0)])
    response = read(db, selector("005"), selector("5"))
    assert [[ref.source_id for ref in item.references] for item in response.items] == [[10], [10]]


def test_curation_order_ignores_legacy_revision_sort_order(db):
    selected_topic = topic(db, selector("005"))
    a, b, c = source(db, 30), source(db, 10), source(db, 20)
    revision(db, selected_topic, [(a, 0), (c, 1), (b, 2)])
    curate(db, selected_topic, [(a, 2), (b, 1), (c, 1)])
    assert visible(db) == [10, 20, 30]


def test_batch_100_selectors_is_one_select_and_does_not_call_db_identity_loader(db, monkeypatch):
    stored = source(db)
    selected = [selector(str(value)) for value in range(100)]
    for item in selected:
        curate(db, topic(db, item), [(stored, 0)])
    monkeypatch.setattr(ParentTrustedReferenceCurationService, "_identity", forbidden)
    monkeypatch.setattr(ParentTrustedReferenceCurationService, "__init__", forbidden)
    with read_guard(db) as statements:
        response = TrustedReferenceReadService(db).read_batch(TrustedReferenceBatchRequest(items=selected))
    assert len(response.items) == 100 and all(len(item.references) == 1 for item in response.items)
    assert len(statements) == 1
    statement = statements[0].lower()
    assert "from parent_trusted_reference_approvals" in statement
    assert "medical_knowledge_revisions" not in statement and "medical_revision_sources" not in statement
    assert "evidence_text" not in statement and "abstract_text" not in statement


def test_projection_compiles_for_mssql_without_changing_schema(db, monkeypatch):
    statements = []

    class Result:
        def mappings(self):
            return []

    def capture(statement):
        statements.append(statement)
        return Result()

    monkeypatch.setattr(db, "execute", capture)
    ParentTrustedReferenceRepository(db).get_approved_reference_metadata([("005", "WEATHER", "humidity", None)])
    sql = str(statements[0].compile(dialect=mssql.dialect())).lower()
    assert "from parent_trusted_reference_approvals" in sql and "factor_value is null" in sql
    assert "medical_knowledge_revisions" not in sql


def test_public_contract_does_not_leak_curation_internals(db, client):
    _stored, _topic, row = setup_approval(db)
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector("005")]})
    assert response.status_code == 200
    assert set(response.json()) == {"items"}
    reference = response.json()["items"][0]["references"][0]
    assert set(reference) == {"source_id", "provider_id", "external_id", "source_type", "source_kind", "title",
                             "journal", "publication_year", "original_url"}
    for value in (row.identity_sha256, "identity_snapshot", "approved_by", "review_note", "policy_version", "PRIVATE"):
        assert value not in response.text


@pytest.mark.parametrize("query", [False, True])
def test_parent_links_do_not_leak_fragment_or_query_credentials(db, client, query):
    url = ("https://www.who.int/publications/i/item/guidance?api_key=PRIVATE_QUERY" if query
           else "https://www.who.int/publications/b/10#token=PRIVATE_FRAGMENT")
    stored = source(db, external_id="guidance" if query else "10", url=url)
    selected_topic = topic(db, selector("005"))
    curate(db, selected_topic, [(stored, 0)])
    with read_guard(db):
        response = client.post("/api/public/trusted-references", json={"items": [selector("005")]})
    assert response.status_code == 200 and "PRIVATE" not in response.text
    refs = response.json()["items"][0]["references"]
    if query:
        assert refs == []
    else:
        assert refs[0]["original_url"] == "https://www.who.int/publications/b/10"


def test_staff_api_revoke_reopen_reapprove_affects_fresh_anonymous_parent_reads(db):
    _stored, _topic, row = setup_approval(db, approved=False, legacy=True)
    app = FastAPI()
    app.include_router(public_router)
    app.include_router(staff_router)
    app.dependency_overrides[get_db] = lambda: db
    auth = {"Authorization": "Bearer " + create_access_token({"sub": "reference-curator"})}
    base = f"/api/medical-knowledge/parent-references/{row.approval_id}"
    selected = selector("005")

    def parent(client):
        with read_guard(db):
            response = client.post("/api/public/trusted-references", json={"items": [selected]})
        assert response.status_code == 200
        return [item["source_id"] for item in response.json()["items"][0]["references"]]

    proof_id = db.scalar(select(Content.id).where(Content.source_id == 10))
    with TestClient(app) as client:
        assert parent(client) == []
        assert client.post(base + "/approve", headers=auth,
            json={**selected, "expected_version": 1, "evidence_content_id": proof_id}).status_code == 200
        assert parent(client) == [10]
        assert client.post(base + "/revoke", headers=auth,
            json={"expected_version": 2, "review_note": "Thu hồi tham khảo"}).status_code == 200
        assert parent(client) == []
        assert client.post(base + "/reopen", headers=auth, json={"expected_version": 3}).status_code == 200
        assert parent(client) == []
        assert client.post(base + "/approve", headers=auth,
            json={**selected, "expected_version": 4, "evidence_content_id": proof_id}).status_code == 200
        assert parent(client) == [10]
    assert approval_state(db, row.approval_id)["version"] == 5
