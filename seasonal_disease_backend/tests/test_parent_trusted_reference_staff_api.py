from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, update

from app.database import get_db
from app.medical_knowledge_factors import load_factor_values
from app.medical_knowledge_models import (
    MedicalEvidenceContent as Content, MedicalEvidenceSource as Source,
    MedicalKnowledgeTopic as Topic, MedicalKnowledgeTopicSource as Membership,
)
from app.models import LoginSession
from app.parent_trusted_reference_models import (
    ParentTrustedReferenceApproval as Approval, ParentTrustedReferenceApprovalEvent as AuditEvent,
)
from app.routers import parent_trusted_references as routes
from app.security import create_access_token, require_staff_or_admin
from app.services.parent_trusted_reference_curation_service import ParentTrustedReferenceCurationService
from app.services.published_medical_knowledge_read_service import PublishedMedicalKnowledgeReadService

from test_parent_trusted_reference_curation_service import (
    db, offline_and_no_generation,  # noqa: F401 - shared isolated DB / autouse guards
)


BASE = "/api/medical-knowledge/parent-references"
SELECTOR = dict(disease_group_id="005", factor_type="WEATHER", factor_key="humidity", factor_value=None)
ENDPOINTS = [
    ("POST", BASE), ("GET", BASE), ("GET", BASE + "/1"), ("GET", BASE + "/1/history"),
    ("POST", BASE + "/1/approve"), ("POST", BASE + "/1/revoke"), ("POST", BASE + "/1/reopen"),
]


@pytest.fixture(autouse=True)
def no_legacy_read_or_prose(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Staff curation API must not enter legacy published/prose paths")

    monkeypatch.setattr(PublishedMedicalKnowledgeReadService, "__init__", forbidden)


@pytest.fixture
def client(db):
    app = FastAPI()  # No actual app startup or Graduation local DB access.
    app.include_router(routes.router)

    def isolated_db():
        yield db

    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as test_client:
        yield test_client


def auth(username="staff", **claims):
    return {"Authorization": f"Bearer {create_access_token({'sub': username, **claims})}"}


def create(client, username="staff", **overrides):
    payload = {**SELECTOR, "source_id": 1, **overrides}
    return client.post(BASE, json=payload, headers=auth(username))


def approve(client, approval_id=1, version=1, username="staff", **overrides):
    return client.post(f"{BASE}/{approval_id}/approve", headers=auth(username),
                       json={**SELECTOR, "expected_version": version, "evidence_content_id": 1, **overrides})


def action(client, name, version, approval_id=1, username="staff", **overrides):
    return client.post(f"{BASE}/{approval_id}/{name}", headers=auth(username),
                       json={"expected_version": version, **overrides})


def get(client, path="/1", **kwargs):
    return client.get(BASE + path, headers=auth(), **kwargs)


def current(db):
    return ParentTrustedReferenceCurationService(db).repository.get_persisted_state(1)


def history(db):
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.resulting_version)))


def change(db, model, **values):
    db.execute(update(model).where(model.id == 1).values(**values))
    db.commit()


def valid_approved(client):
    assert create(client).status_code == 201
    response = approve(client)
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def select_only(db):
    statements = []

    def guard(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)
        assert sql.lstrip().upper().startswith("SELECT"), sql
        assert not any(key in sql.upper() for key in (
            "EVIDENCE_TEXT", "ABSTRACT_TEXT", "RAW_METADATA_JSON", "IDENTITY_SNAPSHOT_JSON",
            "MEDICAL_KNOWLEDGE_REVISIONS", "AUTO_MEDICAL", "PROVIDER_SETTINGS",
        )), sql

    event.listen(db.bind, "before_cursor_execute", guard)
    try:
        yield statements
    finally:
        event.remove(db.bind, "before_cursor_execute", guard)


@pytest.mark.parametrize("method,path", ENDPOINTS)
@pytest.mark.parametrize("user,status", [(None, 401), ("parent", 403), ("inactive", 401), ("missing", 401)])
def test_all_endpoints_enforce_actual_auth_and_role(client, db, method, path, user, status):
    headers = auth(user) if user else {}
    # Valid schema payload avoids confusing authorization with body validation.
    payload = {**SELECTOR, "source_id": 1} if path == BASE else {"expected_version": 1}
    if path.endswith("approve"):
        payload = {**SELECTOR, "expected_version": 1, "evidence_content_id": 1}
    response = client.request(method, path, headers=headers,
                              params={key: value for key, value in SELECTOR.items() if value is not None}
                              if method == "GET" and path == BASE else None,
                              json=payload if method == "POST" else None)
    assert response.status_code == status
    assert current(db) is None and history(db) == []


@pytest.mark.parametrize("user,actor_id", [("staff", 1), ("admin", 2)])
def test_staff_and_admin_full_lifecycle_actor_from_auth(client, db, user, actor_id):
    created = create(client, username=user, review_note="Đang kiểm tra tài liệu")
    assert created.status_code == 201 and created.json()["status"] == "DRAFT"
    assert created.json()["version"] == 1
    allowed = approve(client, username=user, review_note="Đã duyệt nguồn tham khảo")
    assert allowed.status_code == 200 and allowed.json()["version"] == 2
    assert action(client, "revoke", 2, username=user, review_note="Thu hồi nguồn").status_code == 200
    reopened = action(client, "reopen", 3, username=user, review_note="Mở lại để duyệt")
    assert reopened.status_code == 200 and reopened.json()["status"] == "DRAFT"
    assert reopened.json()["identity_sha256"] is None and reopened.json()["evidence_content_id"] is None
    assert approve(client, version=4, username=user).status_code == 200
    assert all(row.actor_user_id == actor_id for row in history(db))
    assert current(db)["created_by"] == current(db)["approved_by"] == actor_id
    with select_only(db):
        response = get(client, "/1/history")
    entries = response.json()["events"]
    assert [item["action"] for item in entries] == ["CREATE_DRAFT", "APPROVE", "REVOKE", "REOPEN_DRAFT", "APPROVE"]
    assert [item["resulting_version"] for item in entries] == [1, 2, 3, 4, 5]
    assert all(item["actor_user_id"] == actor_id and item["created_at"] for item in entries)
    assert entries[1]["review_note"] == "Đã duyệt nguồn tham khảo"


@pytest.mark.parametrize("field,value", [
    ("created_by", 2), ("approved_by", 2), ("revoked_by", 2), ("actor_user_id", 2),
    ("status", "APPROVED"), ("identity_sha256", "f" * 64), ("identity_snapshot_json", {"fake": True}),
    ("policy_decision", "ALLOW_PARENT_REFERENCE"), ("provenance", {"provider_id": "WHO"}),
    ("approved_at", "2026-01-01T00:00:00"), ("version", 99),
])
def test_create_rejects_client_controlled_authority(client, db, field, value):
    assert create(client, **{field: value}).status_code == 422
    assert current(db) is None


@pytest.mark.parametrize("name,field", [("approve", "approved_by"), ("approve", "identity_sha256"),
    ("approve", "policy_decision"), ("revoke", "revoked_by"), ("reopen", "actor_user_id")])
def test_mutation_dtos_reject_actor_hash_and_policy_spoof(client, db, name, field):
    assert create(client).status_code == 201
    response = approve(client, **{field: "fake"}) if name == "approve" else action(client, name, 1, **{field: "fake"})
    assert response.status_code == 422 and len(history(db)) == 1


def test_duplicate_create_conflict_and_wrong_membership_fail(client, db):
    assert create(client).status_code == 201
    assert create(client).status_code == 409
    assert create(client, source_id=2).status_code == 422
    assert len(history(db)) == 1


@pytest.mark.parametrize("overrides", [
    dict(disease_group_id=5), dict(disease_group_id=" 005"), dict(factor_type="weather"),
    dict(factor_key="wrong"), dict(factor_value=""), dict(factor_value=" "),
    dict(factor_value="x"), dict(factor_type="AGE", factor_key="age_group", factor_value=None),
    dict(source_id=True), dict(sort_order=-1), dict(review_note="x" * 1001),
])
def test_malformed_selector_and_request_rejected(client, db, overrides):
    assert create(client, **overrides).status_code == 422
    assert current(db) is None


def test_leading_zero_disease_identity_is_preserved_and_exact_read(client, db):
    assert create(client, disease_group_id="5").status_code == 404
    assert create(client).status_code == 201
    selected = {key: value for key, value in SELECTOR.items() if value is not None}
    with select_only(db):
        response = get(client, "", params=selected)
    assert response.status_code == 200
    assert response.json()["selector"]["disease_group_id"] == "005"
    assert len(response.json()["items"]) == 1
    assert get(client, "", params={**selected, "disease_group_id": "5"}).status_code == 404
    assert get(client, "", params={**selected, "factor_value": ""}).status_code == 422


@pytest.mark.parametrize("factor_type,key", [("AGE", "age_group"), ("SEX", "gender"), ("SEASONALITY", "time_of_year")])
def test_generic_selector_values_and_null_semantics(client, db, factor_type, key):
    value = load_factor_values()[factor_type][0] if factor_type in {"AGE", "SEX"} else None
    change(db, Topic, factor_type=factor_type, factor_key=key, factor_value=value, weather_factor=None)
    chosen = dict(factor_type=factor_type, factor_key=key, factor_value=value)
    assert create(client, **chosen).status_code == 201
    assert approve(client, **chosen).status_code == 200
    selected = get(client).json()["selector"]
    assert selected["factor_value"] == value and selected["factor_type"] == factor_type
    wrong = load_factor_values()[factor_type][1] if factor_type in {"AGE", "SEX"} else ""
    assert approve(client, version=2, **{**chosen, "factor_value": wrong}).status_code in {422, 409}


@pytest.mark.parametrize("proof_id,status", [(999, 404), (2, 422), (None, 422), (True, 422)])
def test_proof_existence_ownership_and_required_identifier(client, db, proof_id, status):
    assert create(client).status_code == 201
    assert approve(client, evidence_content_id=proof_id).status_code == status
    assert current(db)["status"] == "DRAFT" and len(history(db)) == 1


@pytest.mark.parametrize("provider,url,decision", [
    ("PUBMED", "https://pubmed.ncbi.nlm.nih.gov/1/", "STAFF_ONLY"),
    ("WHO", "https://spoof.example/1", "REJECT_PARENT_REFERENCE"),
    ("UNKNOWN", "https://example.org/1", "UNCERTAIN"),
])
def test_policy_fail_closed_for_staff_and_admin(client, db, provider, url, decision):
    change(db, Source, provider_id=provider, url=url)
    assert create(client).status_code == 201
    for user in ("staff", "admin"):
        response = approve(client, username=user)
        assert response.status_code == 422 and decision in response.json()["detail"]["message"]
    assert len(history(db)) == 1


def test_approved_snapshot_hash_server_generated_and_one_approve_event(client, db):
    result = valid_approved(client)
    assert len(result["identity_sha256"]) == 64
    row = current(db)
    assert row["identity_sha256"] == result["identity_sha256"]
    assert row["identity_snapshot_json"]["selector"] == SELECTOR
    assert sum(item.action == "APPROVE" for item in history(db)) == 1


def test_two_clients_stale_retry_409_no_duplicate_event_and_refresh_version(client, db):
    assert create(client).status_code == 201
    assert approve(client).status_code == 200
    stale = approve(client)  # Second simulated client still holds version 1.
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "CURATION_CONFLICT"
    assert get(client).json()["version"] == 2
    assert len(history(db)) == 2
    same = approve(client, version=2)
    assert same.status_code == 200 and same.json()["changed"] is False
    assert len(history(db)) == 2


@pytest.mark.parametrize("provider,url", [("PUBMED", "https://pubmed.ncbi.nlm.nih.gov/1/"),
    ("WHO", "https://spoof.example/1"), ("UNKNOWN", "https://example.org/1")])
def test_revoke_when_policy_changes_reopen_and_reapprove_fail_closed(client, db, provider, url):
    valid_approved(client)
    change(db, Source, provider_id=provider, url=url)
    revoked = action(client, "revoke", 2, review_note="Nguồn không còn đủ điều kiện")
    assert revoked.status_code == 200 and revoked.json()["version"] == 3
    assert sum(item.action == "REVOKE" for item in history(db)) == 1
    assert action(client, "revoke", 3).json()["changed"] is False
    assert action(client, "reopen", 3).json()["status"] == "DRAFT"
    assert current(db)["identity_sha256"] is None
    assert approve(client, version=4).status_code == 422 and len(history(db)) == 4


@pytest.mark.parametrize("name,version", [("revoke", 1), ("reopen", 2), ("approve", 3)])
def test_invalid_state_transition_maps_to_409(client, db, name, version):
    assert create(client).status_code == 201
    if version >= 2:
        assert approve(client).status_code == 200
    if version == 3:
        assert action(client, "revoke", 2).status_code == 200
    response = approve(client, version=version) if name == "approve" else action(client, name, version)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CURATION_STATE_CONFLICT"
    assert len(history(db)) == version


def test_identity_drift_and_membership_loss_cannot_be_overridden(client, db):
    valid_approved(client)
    change(db, Source, title="Changed title")
    assert approve(client, version=2).status_code == 409
    db.execute(delete(Membership))
    db.commit()
    assert approve(client, version=2).status_code == 422
    assert get(client).json()["source_in_library"] is False
    assert action(client, "revoke", 2).status_code == 200


def test_current_policy_recomputed_and_safe_current_history_reads_are_zero_write(client, db):
    valid_approved(client)
    with select_only(db):
        response = get(client)
        audit = get(client, "/1/history")
        listed = get(client, "", params={key: value for key, value in SELECTOR.items() if value is not None})
    assert response.status_code == audit.status_code == listed.status_code == 200
    assert response.json()["policy_decision"] == "ALLOW_PARENT_REFERENCE"
    assert response.json()["policy_reason_code"] == "WHO_OFFICIAL_GUIDANCE"
    assert response.json()["approved_by"] == 1
    for payload in (response.text, audit.text, listed.text):
        assert not any(value in payload for value in (
            "PRIVATE", "evidence_text", "abstract_text", "provenance_json", "raw_metadata_json",
            "identity_snapshot_json", "password_hash", "short_explanation_vi", "detailed_explanation_vi",
        ))
    change(db, Source, url="https://user:password@www.who.int/publications/b/1")
    response = get(client)
    assert response.json()["source"]["original_url"] is None
    assert response.json()["policy_decision"] == "REJECT_PARENT_REFERENCE"
    assert "password" not in response.text


def test_exact_selector_list_deterministic_order_and_empty_topic(client, db):
    selected = {key: value for key, value in SELECTOR.items() if value is not None}
    assert get(client, "", params=selected).json()["items"] == []
    db.add(Membership(topic_id=1, source_id=2, added_by=2))
    db.commit()
    assert create(client, source_id=1, sort_order=5).status_code == 201
    assert create(client, source_id=2, sort_order=1).status_code == 201
    assert [item["source_id"] for item in get(client, "", params=selected).json()["items"]] == [2, 1]


def test_read_does_not_expose_query_credentials(client, db):
    assert create(client).status_code == 201
    change(db, Source, url="https://www.who.int/publications/b/1?api_key=PRIVATE_QUERY_SECRET")
    selected = {key: value for key, value in SELECTOR.items() if value is not None}
    with select_only(db):
        response = get(client)
        listed = get(client, "", params=selected)
    assert response.json()["source"]["original_url"] is None
    assert listed.json()["items"][0]["source"]["original_url"] is None
    assert "PRIVATE_QUERY_SECRET" not in response.text + listed.text


@pytest.mark.parametrize("method,path", ENDPOINTS[2:])
def test_missing_approval_is_404(client, method, path):
    payload = {"expected_version": 1}
    if path.endswith("approve"):
        payload.update(**SELECTOR, evidence_content_id=1)
    response = client.request(method, path, headers=auth(), json=payload if method == "POST" else None)
    assert response.status_code == 404


def test_missing_source_is_404_and_invalid_versions_are_422(client, db):
    assert create(client, source_id=999).status_code == 404
    assert create(client).status_code == 201
    for version in (0, -1, None, True, "1"):
        assert approve(client, version=version).status_code == 422
    assert len(history(db)) == 1


def test_real_jwt_expiration_revoked_and_wrong_owner_login_session_denied(client, db):
    expired = create_access_token({"sub": "staff"}, expires_delta=timedelta(seconds=-1))
    assert client.get(BASE + "/1", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    db.add_all([
        LoginSession(id=1, user_id=1, revoked_at=datetime(2026, 1, 1)),
        LoginSession(id=2, user_id=2),
    ])
    db.commit()
    for sid in (1, 2, 999):
        assert client.get(BASE + "/1", headers=auth("staff", sid=sid)).status_code == 401


def test_unknown_exception_returns_safe_500_without_dependency_details(client, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("PRIVATE DATABASE PASSWORD / provider payload")

    monkeypatch.setattr(routes.ParentTrustedReferenceStaffService, "create", fail)
    response = create(client)
    assert response.status_code == 500 and "PRIVATE" not in response.text
    assert response.json()["detail"]["code"] == "CURATION_OPERATION_FAILED"


def test_actual_registration_once_no_collision_and_no_public_exposure():
    from app.main import app

    # Inspect actual registration without running lifespan, Auto, models or local DB.
    from collections import Counter

    # FastAPI 0.141 keeps included routers lazy; inspect their effective routes.
    effective = [child for route in app.routes for child in (
        list(route.effective_route_contexts()) if hasattr(route, "effective_route_contexts") else [route]
    )]
    signatures = [(route.path, method) for route in effective if hasattr(route, "methods")
                  for method in route.methods]
    expected = {(path.replace("/1", "/{approval_id}"), method) for method, path in ENDPOINTS}
    counts = Counter(signatures)
    assert all(counts[item] == 1 for item in expected)
    assert len([item for item in signatures if item[0].startswith(BASE)]) == 7
    for route in routes.router.routes:
        assert not route.path.startswith("/api/public")
        assert any(dependency.call is require_staff_or_admin for dependency in route.dependant.dependencies)
        assert all("generator" not in str(dependency.call) and "provider" not in str(dependency.call)
                   for dependency in route.dependant.dependencies)
