from __future__ import annotations

import hashlib
import json
import socket
import urllib.request
from contextlib import contextmanager
from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.medical_knowledge_factors import load_factor_values
from app.medical_knowledge_models import (
    MedicalEvidenceContent as Content, MedicalEvidenceSource as Source,
    MedicalKnowledgeTopic as Topic, MedicalKnowledgeTopicSource as Membership,
)
from app.models import User
from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval as Approval, ParentTrustedReferenceApprovalEvent as AuditEvent,
)
from app.services.parent_trusted_reference_curation_service import (
    CURATION_POLICY_VERSION, CurationConflictError, CurationSelector, CurationValidationError,
    ParentTrustedReferenceCurationService,
)
from app.services.auto_medical_knowledge_service import AutoMedicalKnowledgeQueueService
from app.services.medical_evidence_provider_settings_service import MedicalEvidenceProviderSettingsService
from app.services.medical_knowledge_draft_generator import (
    OllamaMedicalKnowledgeDraftGenerator, OpenAIMedicalKnowledgeDraftGenerator,
)
from app.services.medical_knowledge_groq_generator import GroqMedicalKnowledgeDraftGenerator
from app.services.pubmed_evidence_provider import PubMedMedicalEvidenceProvider
from app.services.who_evidence_provider import WhoMedicalEvidenceProvider


NOW = datetime(2026, 1, 2, 3, 4, 5)
SELECTOR = CurationSelector("005", "WEATHER", "humidity")


@pytest.fixture(autouse=True)
def offline_and_no_generation(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Curation must not use network, providers, generators, Auto or settings reconciliation")

    original_connect = socket.socket.connect

    def loopback_only(connection, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)  # Windows asyncio socketpair only.
        forbidden()

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    for target, name in [
        (socket, "create_connection"), (socket.socket, "connect_ex"),
        (urllib.request, "urlopen"), (httpx.HTTPTransport, "handle_request"),
        (httpx.AsyncHTTPTransport, "handle_async_request"),
        (PubMedMedicalEvidenceProvider, "__init__"), (WhoMedicalEvidenceProvider, "__init__"),
        (OpenAIMedicalKnowledgeDraftGenerator, "generate"),
        (OllamaMedicalKnowledgeDraftGenerator, "generate"), (GroqMedicalKnowledgeDraftGenerator, "generate"),
        (AutoMedicalKnowledgeQueueService, "__init__"),
        (AutoMedicalKnowledgeQueueService, "enqueue_selectors"),
        (MedicalEvidenceProviderSettingsService, "reconcile"),
    ]:
        monkeypatch.setattr(target, name, forbidden)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'curation.db').as_posix()}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([
            User(id=1, username="staff", password_hash="fixture", role="staff", is_active=True),
            User(id=2, username="admin", password_hash="fixture", role="admin", is_active=True),
            User(id=3, username="parent", password_hash="fixture", role="parent", is_active=True),
            User(id=4, username="inactive", password_hash="fixture", role="staff", is_active=False),
            Topic(id=1, disease_group_id="005", factor_type="WEATHER", factor_key="humidity", weather_factor="humidity"),
            Source(id=1, source_type="WHO", provider_id="WHO", external_id="1", source_kind="GUIDELINE",
                   title="Hướng dẫn", journal="WHO", publication_year=2025,
                   url="https://www.who.int/publications/b/1", abstract_text="PRIVATE ABSTRACT",
                   raw_metadata_json={"credential": "PRIVATE SECRET"}),
            Source(id=2, source_type="OTHER", title="Other source"),
        ])
        session.flush()
        session.add_all([
            Membership(topic_id=1, source_id=1, added_by=2),
            Content(id=1, source_id=1, content_kind="OFFICIAL_SUMMARY_EXCERPT", content_origin="WHO_PUBLICATIONS_API",
                    external_identifier="1", evidence_text="PRIVATE BODY", retrieved_at=NOW, content_sha256="a" * 64,
                    provenance_json=dict(provider_id="WHO", external_id="1", canonical_url="https://www.who.int/publications/b/1",
                        retrieval_surface="WHO_BIBLIO_SEARCH", metadata_storage_allowed=True, full_text_stored=False,
                        api_key="PRIVATE SECRET", generated_prose="PRIVATE GENERATED")),
            Content(id=2, source_id=2, content_kind="ABSTRACT", content_origin="NCBI_PUBMED",
                    evidence_text="OTHER BODY", retrieved_at=NOW, content_sha256="b" * 64),
        ])
        session.commit()
        yield session
    engine.dispose()


def service(db):
    return ParentTrustedReferenceCurationService(db, clock=lambda: NOW)


def create(db, **overrides):
    values = dict(topic_id=1, source_id=1, selector=SELECTOR, actor_id=1)
    values.update(overrides)
    return service(db).create_draft(**values)


def approve(db, approval_id, version=1, **overrides):
    values = dict(expected_version=version, selector=SELECTOR, evidence_content_id=1, actor_id=1)
    values.update(overrides)
    return service(db).approve(approval_id, **values)


def approved(db):
    row = create(db)
    return approve(db, row.approval_id)


def state(db, approval_id=1):
    return service(db).repository.get_persisted_state(approval_id)


def events(db, approval_id=1):
    return list(db.scalars(select(AuditEvent).where(AuditEvent.approval_id == approval_id)
                           .order_by(AuditEvent.resulting_version)))


def change(db, model, values, row_id=1):
    db.execute(update(model).where(model.id == row_id).values(**values), execution_options={"synchronize_session": False})
    db.commit()


def remove_membership(db):
    db.execute(delete(Membership).where(Membership.topic_id == 1, Membership.source_id == 1))
    db.commit()


@contextmanager
def curation_sql_only(db):
    statements = []

    def audit_sql(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        upper = statement.upper()
        if upper.lstrip().startswith(("INSERT", "UPDATE", "DELETE")):
            assert "PARENT_TRUSTED_REFERENCE_" in upper
        else:
            assert upper.lstrip().startswith("SELECT")
            assert not any(name in upper for name in (
                "EVIDENCE_TEXT", "ABSTRACT_TEXT", "RAW_METADATA_JSON", "MEDICAL_KNOWLEDGE_REVISIONS",
                "AUTO_MEDICAL", "MEDICAL_EVIDENCE_PROVIDER_SETTINGS",
            ))

    event.listen(db.bind, "before_cursor_execute", audit_sql)
    try:
        yield statements
    finally:
        event.remove(db.bind, "before_cursor_execute", audit_sql)


def test_create_draft_is_reference_only_with_one_event(db):
    with curation_sql_only(db):
        result = create(db, review_note="Đang kiểm tra nguồn", sort_order=3)
    row = state(db)
    assert (result.status, result.version, result.changed) == ("DRAFT", 1, True)
    assert result.policy_decision == "UNCERTAIN"  # No proof bound yet; no implied approval.
    assert row["sort_order"] == 3 and row["created_by"] == 1
    assert row["created_at"] == row["updated_at"] == NOW
    assert row["identity_sha256"] is None and row["evidence_content_id"] is None
    audit = events(db)
    assert len(audit) == 1 and audit[0].action == "CREATE_DRAFT"
    assert audit[0].from_status is None and audit[0].to_status == "DRAFT"
    assert audit[0].review_note == "Đang kiểm tra nguồn"
    assert audit[0].actor_user_id == 1 and audit[0].created_at == NOW


def test_duplicate_identity_conflicts_without_new_event(db):
    create(db)
    with pytest.raises(CurationConflictError):
        create(db)
    assert len(events(db)) == 1


@pytest.mark.parametrize("overrides", [dict(topic_id=999), dict(source_id=999), dict(source_id=2)])
def test_create_requires_topic_source_and_membership(db, overrides):
    with pytest.raises(CurationValidationError):
        create(db, **overrides)
    assert state(db) is None and events(db) == []


@pytest.mark.parametrize("provider,url,kind,decision", [
    ("PUBMED", "https://pubmed.ncbi.nlm.nih.gov/1/", "RESEARCH_ARTICLE", "STAFF_ONLY"),
    ("PMC", "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/", "REVIEW", "STAFF_ONLY"),
    ("WHO", "https://spoof.example/1", "GUIDELINE", "REJECT_PARENT_REFERENCE"),
    ("UNKNOWN", "https://example.org/1", "GUIDELINE", "UNCERTAIN"),
    ("WHO", "https://www.who.int/publications/b/1", "OTHER", "UNCERTAIN"),
])
def test_draft_allowed_but_approval_blocked_for_non_allow_policy(db, provider, url, kind, decision):
    change(db, Source, dict(provider_id=provider, url=url, source_kind=kind))
    row = create(db)
    with pytest.raises(CurationValidationError, match=decision):
        approve(db, row.approval_id)
    assert state(db)["status"] == "DRAFT" and len(events(db)) == 1


def test_valid_proof_policy_allow_approves_with_snapshot_and_actor(db):
    row = create(db)
    with curation_sql_only(db):
        result = approve(db, row.approval_id, actor_id=2, review_note="Đã duyệt tham khảo")
    saved = state(db)
    assert (result.status, result.version, result.changed) == ("APPROVED", 2, True)
    assert saved["approved_by"] == 2 and saved["approved_at"] == NOW
    assert saved["created_by"] == 1  # Never infer from membership.added_by=2.
    assert saved["evidence_content_id"] == 1 and saved["policy_version"] == CURATION_POLICY_VERSION
    snapshot = saved["identity_snapshot_json"]
    assert snapshot["selector"]["disease_group_id"] == "005"
    assert snapshot["proof"]["evidence_content_id"] == 1
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert hashlib.sha256(encoded.encode()).hexdigest() == result.identity_sha256
    assert "PRIVATE" not in encoded and "api_key" not in encoded and "generated_prose" not in encoded
    audit = events(db)
    assert len(audit) == 2 and audit[1].action == "APPROVE"
    assert (audit[1].from_status, audit[1].to_status, audit[1].resulting_version) == ("DRAFT", "APPROVED", 2)
    assert audit[1].identity_snapshot_json == snapshot and audit[1].identity_sha256 == result.identity_sha256
    assert audit[1].actor_user_id == 2 and audit[1].created_at == NOW


@pytest.mark.parametrize("proof_id", [2, 999])
def test_missing_or_other_source_proof_cannot_approve(db, proof_id):
    row = create(db)
    with pytest.raises(CurationValidationError, match="Proof"):
        approve(db, row.approval_id, evidence_content_id=proof_id)
    assert state(db)["version"] == 1 and len(events(db)) == 1


@pytest.mark.parametrize("field,value", [
    ("external_identifier", "different"), ("content_origin", "NCBI_PUBMED"),
    ("provenance_json", None),
    ("provenance_json", dict(provider_id="WHO", external_id="2", canonical_url="https://www.who.int/publications/b/1")),
])
def test_proof_identity_and_provenance_required(db, field, value):
    change(db, Content, {field: value})
    row = create(db)
    with pytest.raises(CurationValidationError, match="Source Policy"):
        approve(db, row.approval_id)


@pytest.mark.parametrize("selector", [
    CurationSelector("5", "WEATHER", "humidity"),
    CurationSelector("005", "WEATHER", "temperature"),
    CurationSelector("005", "SEASONALITY", "time_of_year"),
    CurationSelector("005", "WEATHER", "humidity", ""),
    CurationSelector("005", "WEATHER", "humidity", " "),
    CurationSelector("005", "WEATHER", "humidity", "x"),
    CurationSelector("005", "weather", "humidity"),
    CurationSelector(5, "WEATHER", "humidity"),
])
def test_selector_mismatch_and_noncanonical_values_rejected(db, selector):
    with pytest.raises(CurationValidationError):
        create(db, selector=selector)


@pytest.mark.parametrize("factor_type,key", [("AGE", "age_group"), ("SEX", "gender")])
def test_age_sex_exact_values_and_wrong_value_on_approve(db, factor_type, key):
    values = load_factor_values()[factor_type]
    first, second = values[:2]
    change(db, Topic, dict(factor_type=factor_type, factor_key=key, factor_value=first, weather_factor=None))
    chosen = CurationSelector("005", factor_type, key, first)
    row = create(db, selector=chosen)
    with pytest.raises(CurationValidationError):
        approve(db, row.approval_id, selector=CurationSelector("005", factor_type, key, second))
    assert approve(db, row.approval_id, selector=chosen).status == "APPROVED"


@pytest.mark.parametrize("factor_type,key", [("WEATHER", "humidity"), ("SEASONALITY", "time_of_year")])
def test_null_is_exact_and_empty_persisted_topic_is_not_null(db, factor_type, key):
    chosen = CurationSelector("005", factor_type, key)
    if factor_type == "WEATHER":
        # Existing topic schema itself rejects an empty WEATHER value.
        with pytest.raises(IntegrityError):
            change(db, Topic, dict(factor_value=""))
        db.rollback()
    else:
        change(db, Topic, dict(factor_type=factor_type, factor_key=key, factor_value="", weather_factor=None))
        with pytest.raises(CurationValidationError, match="exact selector"):
            create(db, selector=chosen)
        change(db, Topic, dict(factor_value=None))
    row = create(db, selector=chosen)
    assert approve(db, row.approval_id, selector=chosen).status == "APPROVED"


def test_membership_removed_before_approval_fails(db):
    row = create(db)
    remove_membership(db)
    with pytest.raises(CurationValidationError, match="library"):
        approve(db, row.approval_id)
    assert len(events(db)) == 1


def test_membership_removed_after_approval_does_not_mutate_but_can_revoke(db):
    row = approved(db)
    remove_membership(db)
    assert state(db)["status"] == "APPROVED" and len(events(db)) == 2
    assert service(db).revoke(row.approval_id, expected_version=2, actor_id=1).status == "REVOKED"


def test_same_identity_is_noop_even_with_reordered_provenance_and_normalized_url(db):
    row = approved(db)
    original = state(db)["identity_snapshot_json"]
    provenance = db.scalar(select(Content.provenance_json).where(Content.id == 1))
    change(db, Content, dict(provenance_json=dict(reversed(list(provenance.items())))))
    change(db, Source, dict(url="https://WWW.WHO.INT:443/publications/b/1/#anchor"))
    result = approve(db, row.approval_id, version=2)
    assert not result.changed and result.identity_sha256 == row.identity_sha256
    assert state(db)["identity_snapshot_json"] == original and len(events(db)) == 2


@pytest.mark.parametrize("model,values", [
    (Source, dict(title="Changed title")), (Source, dict(journal="Changed publisher")),
    (Source, dict(publication_year=2026)), (Source, dict(source_kind="HEALTH_GUIDANCE")),
    (Content, dict(content_sha256="c" * 64)),
])
def test_approved_identity_drift_requires_revoke_and_reopen(db, model, values):
    row = approved(db)
    saved = state(db)
    change(db, model, values)
    with pytest.raises(CurationConflictError, match="identity drift"):
        approve(db, row.approval_id, version=2)
    assert state(db) == saved and len(events(db)) == 2


def test_alternative_valid_proof_cannot_replace_approved_in_place(db):
    row = approved(db)
    proof = dict(db.execute(select(*Content.__table__.c).where(Content.id == 1)).mappings().one())
    proof["id"] = 3
    proof["content_sha256"] = "c" * 64
    db.add(Content(**proof))
    db.commit()
    with pytest.raises(CurationConflictError, match="identity drift"):
        approve(db, row.approval_id, version=2, evidence_content_id=3)
    assert state(db)["evidence_content_id"] == 1 and len(events(db)) == 2


@pytest.mark.parametrize("action", ["approve", "revoke", "reopen"])
def test_stale_expected_version_conflicts_before_transition(db, action):
    row = approved(db)
    kwargs = dict(expected_version=1, actor_id=1)
    if action != "revoke":
        kwargs["selector"] = SELECTOR
    if action == "approve":
        kwargs["evidence_content_id"] = 1
    with pytest.raises(CurationConflictError, match="Stale"):
        getattr(service(db), action)(row.approval_id, **kwargs)
    assert state(db)["version"] == 2 and len(events(db)) == 2


@pytest.mark.parametrize("version", [0, -1, True, None, "1"])
def test_expected_version_must_be_positive_integer(db, version):
    row = create(db)
    with pytest.raises(CurationValidationError, match="expected_version"):
        approve(db, row.approval_id, version=version)


def test_cas_losing_actual_second_session_mutation_has_no_orphan_event(db, monkeypatch):
    row = approved(db)
    first = service(db)
    original = first.repository.compare_and_swap

    def raced(approval_id, expected_version, values):
        with Session(db.bind) as other:
            service(other).revoke(approval_id, expected_version=2, actor_id=2, review_note="Other transaction")
        return original(approval_id, expected_version, values)

    monkeypatch.setattr(first.repository, "compare_and_swap", raced)
    with pytest.raises(CurationConflictError, match="Concurrent"):
        first.revoke(row.approval_id, expected_version=2, actor_id=1)
    assert state(db)["version"] == 3 and state(db)["revoked_by"] == 2
    assert len(events(db)) == 3


@pytest.mark.parametrize("action", ["create", "approve", "revoke", "reopen"])
def test_event_failure_rolls_back_entire_mutation(db, monkeypatch, action):
    row = None
    if action == "approve":
        row = create(db)
    elif action in {"revoke", "reopen"}:
        row = approved(db)
        if action == "reopen":
            row = service(db).revoke(row.approval_id, expected_version=2, actor_id=1)
    before = state(db)
    count = len(events(db))
    current = service(db)
    append = current.repository.append_event

    def append_then_fail(**kwargs):
        append(**kwargs)
        raise RuntimeError("event insertion failed after flush")

    monkeypatch.setattr(current.repository, "append_event", append_then_fail)
    with pytest.raises(RuntimeError, match="event insertion"):
        if action == "create":
            current.create_draft(topic_id=1, source_id=1, selector=SELECTOR, actor_id=1)
        elif action == "approve":
            current.approve(row.approval_id, expected_version=1, evidence_content_id=1, selector=SELECTOR, actor_id=1)
        elif action == "revoke":
            current.revoke(row.approval_id, expected_version=2, actor_id=1)
        else:
            current.reopen(row.approval_id, expected_version=3, selector=SELECTOR, actor_id=1)
    assert state(db) == before and len(events(db)) == count


def test_row_mutation_failure_rolls_back_and_does_not_append_event(db, monkeypatch):
    row = create(db)
    current = service(db)
    original = current.repository.compare_and_swap

    def mutation_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("row mutation failed")

    monkeypatch.setattr(current.repository, "compare_and_swap", mutation_then_fail)
    with pytest.raises(RuntimeError, match="row mutation"):
        current.approve(row.approval_id, expected_version=1, selector=SELECTOR, evidence_content_id=1, actor_id=1)
    assert state(db)["status"] == "DRAFT" and len(events(db)) == 1


def test_commit_failure_rolls_back_row_and_event(db, monkeypatch):
    row = create(db)

    def fail():
        raise RuntimeError("commit failed")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError, match="commit failed"):
            approve(db, row.approval_id)
    assert state(db)["status"] == "DRAFT" and len(events(db)) == 1


@pytest.mark.parametrize("provider", ["UNKNOWN", "PUBMED", "WHO"])
def test_revoke_does_not_require_allow_and_preserves_identity_history(db, provider):
    row = approved(db)
    snapshot = state(db)["identity_snapshot_json"]
    change(db, Source, dict(provider_id=provider, url="https://spoof.example/1"))
    result = service(db).revoke(row.approval_id, expected_version=2, actor_id=2, review_note="Thu hồi: nguồn thay đổi")
    saved = state(db)
    assert (result.status, result.version) == ("REVOKED", 3)
    assert saved["evidence_content_id"] == 1 and saved["identity_snapshot_json"] == snapshot
    assert saved["approved_by"] == 1 and saved["revoked_by"] == 2 and saved["revoked_at"] == NOW
    assert events(db)[-1].review_note == "Thu hồi: nguồn thay đổi"
    assert events(db)[-1].identity_snapshot_json == snapshot


def test_reopen_clears_current_approval_and_preserves_append_only_history(db):
    row = approved(db)
    old_hash = row.identity_sha256
    service(db).revoke(row.approval_id, expected_version=2, actor_id=2)
    with curation_sql_only(db):
        reopened = service(db).reopen(row.approval_id, expected_version=3, selector=SELECTOR, actor_id=1)
    saved = state(db)
    assert (reopened.status, reopened.version) == ("DRAFT", 4)
    for name in ("evidence_content_id", "identity_snapshot_json", "identity_sha256", "policy_version",
                 "approved_by", "approved_at", "revoked_by", "revoked_at"):
        assert saved[name] is None
    assert saved["created_by"] == 1 and len(events(db)) == 4
    assert events(db)[1].identity_sha256 == events(db)[2].identity_sha256 == old_hash
    change(db, Source, dict(title="New review title"))
    again = approve(db, row.approval_id, version=4)
    assert (again.status, again.version) == ("APPROVED", 5) and again.identity_sha256 != old_hash
    assert [item.action for item in events(db)] == ["CREATE_DRAFT", "APPROVE", "REVOKE", "REOPEN_DRAFT", "APPROVE"]


@pytest.mark.parametrize("change_kind", ["policy", "proof", "membership"])
def test_reapproval_after_reopen_revalidates_current_context(db, change_kind):
    row = approved(db)
    service(db).revoke(row.approval_id, expected_version=2, actor_id=1)
    service(db).reopen(row.approval_id, expected_version=3, selector=SELECTOR, actor_id=1)
    if change_kind == "policy":
        change(db, Source, dict(provider_id="UNKNOWN"))
    elif change_kind == "proof":
        change(db, Content, dict(external_identifier="different"))
    else:
        remove_membership(db)
    with pytest.raises(CurationValidationError):
        approve(db, row.approval_id, version=4)
    assert state(db)["status"] == "DRAFT" and len(events(db)) == 4


@pytest.mark.parametrize("action,initial", [("revoke", "DRAFT"), ("reopen", "APPROVED"), ("approve", "REVOKED")])
def test_invalid_transitions_rejected(db, action, initial):
    row = create(db) if initial == "DRAFT" else approved(db)
    if initial == "REVOKED":
        row = service(db).revoke(row.approval_id, expected_version=2, actor_id=1)
    kwargs = dict(expected_version=row.version, actor_id=1)
    if action != "revoke":
        kwargs["selector"] = SELECTOR
    if action == "approve":
        kwargs["evidence_content_id"] = 1
    with pytest.raises(CurationValidationError, match="Only"):
        getattr(service(db), action)(row.approval_id, **kwargs)
    assert state(db)["status"] == initial and len(events(db)) == row.version


def test_current_version_noops_do_not_write_or_append_events(db):
    row = create(db)
    assert not service(db).reopen(row.approval_id, expected_version=1, selector=SELECTOR, actor_id=1).changed
    approve(db, row.approval_id)
    assert not approve(db, row.approval_id, version=2).changed
    service(db).revoke(row.approval_id, expected_version=2, actor_id=1)
    with curation_sql_only(db) as statements:
        assert not service(db).revoke(row.approval_id, expected_version=3, actor_id=2).changed
    assert all(item.lstrip().upper().startswith("SELECT") for item in statements)
    assert len(events(db)) == 3


@pytest.mark.parametrize("actor_id", [3, 4, 999, None, True, "1"])
def test_actor_must_be_authenticated_active_staff_or_admin(db, actor_id):
    with pytest.raises(CurationValidationError, match="actor|Actor"):
        create(db, actor_id=actor_id)
    assert state(db) is None


def test_cached_actor_and_source_do_not_override_persisted_current_metadata(db):
    row = create(db)
    user = db.get(User, 1)
    source = db.get(Source, 1)
    change(db, User, dict(is_active=False))
    assert user.is_active  # Deliberately stale ORM identity map.
    with pytest.raises(CurationValidationError, match="Actor"):
        approve(db, row.approval_id)
    change(db, User, dict(is_active=True))
    assert source.provider_id == "WHO"  # Warm the instance expired by failed-call rollback.
    change(db, Source, dict(provider_id="UNKNOWN"))
    assert source.provider_id == "WHO"
    with pytest.raises(CurationValidationError, match="UNCERTAIN"):
        approve(db, row.approval_id)


@pytest.mark.parametrize("note", ["x" * 1001, 42])
def test_bounded_review_note_rejects_invalid_input(db, note):
    with pytest.raises(CurationValidationError, match="Review note"):
        create(db, review_note=note)


def test_pending_caller_work_is_not_flushed_or_committed(db):
    user = db.get(User, 1)
    user.full_name = "Caller pending write"
    with pytest.raises(CurationValidationError, match="pending caller"):
        create(db)
    assert user in db.dirty
    with Session(db.bind) as other:
        assert other.get(User, 1).full_name is None
        assert other.scalar(select(Approval.id)) is None
    db.rollback()


def test_body_and_unrelated_provenance_changes_do_not_change_fingerprint(db):
    row = approved(db)
    proof = db.scalar(select(Content.provenance_json).where(Content.id == 1))
    change(db, Content, dict(evidence_text="No prose dependency", provenance_json={**proof, "secret": "do not copy"}))
    with curation_sql_only(db):
        result = approve(db, row.approval_id, version=2)
    assert not result.changed and result.identity_sha256 == row.identity_sha256
