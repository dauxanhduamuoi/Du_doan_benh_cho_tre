from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.medical_knowledge_factors import load_factor_values
from app.medical_knowledge_models import (
    MedicalEvidenceContent as Content, MedicalEvidenceSource as Source,
    MedicalKnowledgeTopic as Topic, MedicalKnowledgeTopicSource as Membership,
)
from app.models import LoginSession
from app.security import create_access_token
from app.parent_trusted_reference_schemas import StaffReferenceProofQuery
from app.services.parent_trusted_reference_staff_service import ParentTrustedReferenceStaffService

from test_parent_trusted_reference_curation_service import db, offline_and_no_generation, NOW  # noqa: F401
from test_parent_trusted_reference_staff_api import (
    client, no_legacy_read_or_prose, auth, SELECTOR, BASE, create, approve, action,
    select_only, current, history, change,
)  # noqa: F401 - isolated fixtures and offline/legacy guards


PATH = BASE + "/proof-candidates"
CANDIDATE_KEYS = {
    "evidence_content_id", "source_id", "content_kind", "content_origin", "external_identifier",
    "retrieved_at", "content_sha256", "policy_decision", "policy_reason_code",
}


def preview(client, username="staff", **overrides):
    params = {**SELECTOR, "source_id": 1, **overrides}
    params = {key: value for key, value in params.items() if value is not None}
    return client.get(PATH, params=params, headers=auth(username) if username else {})


def add_content(db, content_id, *, source_id=1, provenance=None, **overrides):
    proof = dict(provider_id="WHO", external_id="1", canonical_url="https://www.who.int/publications/b/1",
                 retrieval_surface="WHO_BIBLIO_SEARCH", metadata_storage_allowed=True, full_text_stored=False)
    values = dict(id=content_id, source_id=source_id, content_kind="OFFICIAL_SUMMARY_EXCERPT",
                  content_origin="WHO_PUBLICATIONS_API", external_identifier="1", evidence_text="PRIVATE BODY",
                  retrieved_at=NOW - timedelta(days=content_id), content_sha256=f"{content_id:064x}",
                  provenance_json=proof if provenance is None else provenance)
    values.update(overrides)
    db.add(Content(**values))
    db.commit()


def set_topic(db, factor_type, factor_key, factor_value=None):
    change(db, Topic, factor_type=factor_type, factor_key=factor_key, factor_value=factor_value,
           weather_factor=factor_key if factor_type == "WEATHER" else None)


@pytest.mark.parametrize("user,status", [
    (None, 401), ("parent", 403), ("inactive", 401), ("missing", 401), ("staff", 200), ("admin", 200),
])
def test_actual_auth_and_roles(client, db, user, status):
    with select_only(db):
        response = preview(client, username=user)
    assert response.status_code == status
    assert current(db) is None and history(db) == []


@pytest.mark.parametrize("overrides", [
    {"source_id": 0}, {"source_id": -1}, {"source_id": "abc"}, {"source_id": "1.5"},
    {"source_id": ""}, {"factor_type": "weather"}, {"factor_type": "UNKNOWN"},
    {"factor_key": " humidity"}, {"factor_key": "bad"}, {"factor_value": ""},
    {"factor_value": "unexpected"}, {"factor_type": "AGE", "factor_key": "age_group"},
    {"factor_type": "SEX", "factor_key": "gender"}, {"disease_group_id": " 005"},
    {"disease_group_id": "bad"}, {"disease_group_id": "1234567"},
    {"offset": -1}, {"limit": 0}, {"limit": 101},
])
def test_invalid_query_rejected_without_writes(client, db, overrides):
    with select_only(db):
        response = preview(client, **overrides)
    assert response.status_code == 422, response.text
    assert current(db) is None and history(db) == []


@pytest.mark.parametrize("field", ["source_id", "disease_group_id", "factor_type", "factor_key"])
def test_required_query_fields(client, field):
    params = {key: value for key, value in {**SELECTOR, "source_id": 1}.items()
              if value is not None and key != field}
    assert client.get(PATH, params=params, headers=auth()).status_code == 422


@pytest.mark.parametrize("field,value", [
    ("policy_decision", "ALLOW_PARENT_REFERENCE"), ("provenance", "spoof"),
    ("source_type", "WHO"), ("evidence_content_id", "2"), ("actor_user_id", "2"),
])
def test_client_cannot_supply_identity_policy_or_proof(client, field, value):
    assert preview(client, **{field: value}).status_code == 422


@pytest.mark.parametrize("overrides,status", [
    ({"disease_group_id": "5"}, 404), ({"disease_group_id": "006"}, 404),
    ({"factor_key": "temperature"}, 404),
    ({"factor_type": "SEASONALITY", "factor_key": "time_of_year"}, 404),
    ({"source_id": 999}, 404), ({"source_id": 2}, 422),
])
def test_missing_topic_source_or_membership_is_domain_error(client, db, overrides, status):
    with select_only(db):
        response = preview(client, **overrides)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == ("CURATION_NOT_FOUND" if status == 404 else "CURATION_VALIDATION")
    assert current(db) is None and history(db) == []


@pytest.mark.parametrize("factor_type,factor_key", [("AGE", "age_group"), ("SEX", "gender")])
def test_age_sex_exact_value_and_no_other_topic_membership(client, db, factor_type, factor_key):
    first, second = load_factor_values()[factor_type][:2]
    set_topic(db, factor_type, factor_key, first)
    db.add(Topic(id=2, disease_group_id="005", factor_type=factor_type, factor_key=factor_key, factor_value=second))
    db.commit()
    response = preview(client, factor_type=factor_type, factor_key=factor_key, factor_value=first)
    assert response.status_code == 200
    assert response.json()["selector"]["factor_value"] == first
    assert preview(client, factor_type=factor_type, factor_key=factor_key, factor_value=second).status_code == 422
    assert preview(client, factor_type=factor_type, factor_key=factor_key, factor_value=" " + first).status_code == 422


@pytest.mark.parametrize("factor_type,factor_key", [("WEATHER", "humidity"), ("SEASONALITY", "time_of_year")])
def test_null_exact_semantics(client, db, factor_type, factor_key):
    set_topic(db, factor_type, factor_key)
    with select_only(db) as statements:
        response = preview(client, factor_type=factor_type, factor_key=factor_key)
    assert response.status_code == 200 and response.json()["selector"]["factor_value"] is None
    assert any("factor_value IS NULL" in sql for sql in statements)
    assert preview(client, factor_type=factor_type, factor_key=factor_key, factor_value="null").status_code == 422
    if factor_type == "SEASONALITY":  # WEATHER's DB constraint already prohibits non-null values.
        change(db, Topic, factor_value="noncanonical persisted value")
        assert preview(client, factor_type=factor_type, factor_key=factor_key).status_code == 404


def test_zero_proofs_is_valid_empty_without_creating_approval(client, db):
    db.execute(delete(Content).where(Content.source_id == 1))
    db.commit()
    with select_only(db):
        response = preview(client)
    assert response.status_code == 200
    assert response.json()["candidates"] == [] and response.json()["next_offset"] is None
    assert current(db) is None and history(db) == []


def test_single_candidate_exact_metadata_policy_and_route_not_captured(client, db):
    with select_only(db):
        response = preview(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["selector"] == SELECTOR
    assert payload["topic_id"] == payload["source_id"] == 1
    assert payload["next_offset"] is None
    assert payload["candidates"] == [dict(
        evidence_content_id=1, source_id=1, content_kind="OFFICIAL_SUMMARY_EXCERPT",
        content_origin="WHO_PUBLICATIONS_API", external_identifier="1",
        retrieved_at=NOW.isoformat(), content_sha256="a" * 64,
        policy_decision="ALLOW_PARENT_REFERENCE", policy_reason_code="WHO_OFFICIAL_GUIDANCE",
    )]
    # Existing dynamic route still behaves independently.
    assert client.get(BASE + "/999", headers=auth()).status_code == 404


def test_multiple_candidates_id_order_repeatable_without_preferred_selection(client, db):
    add_content(db, 9)
    add_content(db, 3, content_kind="ABSTRACT", content_origin="NCBI_PUBMED")
    first = preview(client).json()
    assert [item["evidence_content_id"] for item in first["candidates"]] == [1, 3, 9]
    assert all(item["source_id"] == 1 for item in first["candidates"])
    assert first == preview(client).json()
    assert current(db) is None and history(db) == []


def test_bounded_pagination_exposes_all_candidates_no_silent_truncation(client, db):
    for content_id in (3, 4, 5):
        add_content(db, content_id)
    first = preview(client, limit=2).json()
    assert [item["evidence_content_id"] for item in first["candidates"]] == [1, 3]
    assert first["next_offset"] == 2
    second = preview(client, limit=2, offset=first["next_offset"]).json()
    assert [item["evidence_content_id"] for item in second["candidates"]] == [4, 5]
    assert second["next_offset"] is None
    assert preview(client, offset=100).json()["candidates"] == []


@pytest.mark.parametrize("source_values,proof_values,decision,reason", [
    ({}, {}, "ALLOW_PARENT_REFERENCE", "WHO_OFFICIAL_GUIDANCE"),
    ({"provider_id": "PUBMED", "source_type": "PUBMED"}, {}, "STAFF_ONLY", "PUBMED_RESEARCH_STAFF_ONLY"),
    ({"url": "http://www.who.int/publications/b/1"}, {}, "REJECT_PARENT_REFERENCE", "UNSAFE_URL"),
    ({"provider_id": "OTHER", "source_type": "OTHER"}, {}, "UNCERTAIN", "UNSUPPORTED_PROVIDER"),
    ({"url": "https://who.int.evil.example/publications/b/1"}, {}, "REJECT_PARENT_REFERENCE", "PROVIDER_HOST_MISMATCH"),
    ({}, {"external_identifier": "99"}, "REJECT_PARENT_REFERENCE", "SOURCE_IDENTITY_MISMATCH"),
    ({}, {"provenance_json": {"provider_id": "WHO"}}, "UNCERTAIN", "MISSING_TRUST_METADATA"),
    ({}, {"provenance_json": []}, "UNCERTAIN", "MISSING_TRUST_METADATA"),
])
def test_current_policy_preview_exact_decision_reason(client, db, source_values, proof_values, decision, reason):
    if source_values:
        change(db, Source, **source_values)
    if proof_values:
        change(db, Content, **proof_values)
    with select_only(db):
        payload = preview(client).json()
    item = payload["candidates"][0]
    assert (item["policy_decision"], item["policy_reason_code"]) == (decision, reason)


def test_each_candidate_evaluated_independently_without_allow_filter(client, db):
    add_content(db, 3, external_identifier="spoof")
    add_content(db, 4, provenance={})
    items = preview(client).json()["candidates"]
    assert [item["policy_decision"] for item in items] == [
        "ALLOW_PARENT_REFERENCE", "REJECT_PARENT_REFERENCE", "UNCERTAIN",
    ]


@pytest.mark.parametrize("url", [
    "https://user:PRIVATE_PASSWORD@www.who.int/publications/b/1",
    "https://www.who.int/publications/b/1?api_key=PRIVATE_QUERY_SECRET",
    "https://www.who.int/publications/b/1?token=PRIVATE_QUERY_SECRET#fragment",
])
def test_source_url_credentials_are_not_returned(client, db, url):
    change(db, Source, url=url)
    with select_only(db):
        response = preview(client)
    assert response.status_code == 200
    assert response.json()["source"]["original_url"] is None
    assert "PRIVATE" not in response.text


def test_response_whitelist_redacts_body_provenance_secrets_and_bounds_metadata(client, db):
    change(db, Source, title="X" * 2000, journal="Y" * 2000)
    change(db, Content, license_url="https://secret.example/?api_key=PRIVATE",
           provenance_json={"credential": "PRIVATE SECRET", "raw_payload": "PRIVATE PROVIDER",
                            "short_explanation_vi": "PRIVATE PROSE"})
    with select_only(db):
        response = preview(client)
    assert response.status_code == 200
    data = response.json()
    assert len(data["source"]["title"]) == len(data["source"]["journal"]) == 1000
    assert set(data) == {"selector", "topic_id", "source_id", "source", "candidates", "next_offset"}
    assert set(data["candidates"][0]) == CANDIDATE_KEYS
    assert not any(term in response.text for term in (
        "PRIVATE", "OTHER BODY", "evidence_text", "abstract_text", "provenance_json", "raw_payload",
        "raw_metadata_json", "identity_snapshot_json", "credential", "api_key", "password_hash",
        "short_explanation_vi", "detailed_explanation_vi", "limitations_vi", "license_url",
    ))


def test_four_service_selects_independent_of_candidate_count_no_autoflush_commit(db, monkeypatch):
    for content_id in range(3, 103):
        add_content(db, content_id)
    # Pending unrelated ORM changes must not be flushed or become proof metadata.
    db.get(Source, 1).title = "PENDING TITLE"
    db.add(Source(source_type="OTHER", title="PENDING SOURCE"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Proof preview must not flush/commit")

    monkeypatch.setattr(db, "flush", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    with select_only(db) as statements:
        result = ParentTrustedReferenceStaffService(db).proof_candidates(StaffReferenceProofQuery(**SELECTOR, source_id=1))
    assert len(statements) == 4
    assert len(result.candidates) == 100 and result.next_offset == 100
    assert result.source.title != "PENDING TITLE"
    assert len(db.new) == 1 and len(db.dirty) == 1


def test_preview_does_not_bind_or_modify_draft_approved_revoked_reopened(client, db):
    assert create(client).status_code == 201
    for name, version in [(None, 1), ("approve", 1), ("revoke", 2), ("reopen", 3)]:
        if name == "approve":
            assert approve(client).status_code == 200
        elif name:
            assert action(client, name, version).status_code == 200
        before = current(db)
        event_count = len(history(db))
        with select_only(db):
            assert preview(client).status_code == 200
        assert current(db) == before and len(history(db)) == event_count


@pytest.mark.parametrize("mutation", ["stale", "policy", "ownership", "fake", "membership", "selector", "fingerprint"])
def test_preview_cannot_authorize_or_bypass_existing_approve_checks(client, db, mutation):
    assert create(client).status_code == 201
    assert preview(client).json()["candidates"][0]["policy_decision"] == "ALLOW_PARENT_REFERENCE"
    proof_id, version, overrides = 1, 1, {}
    if mutation == "stale":
        assert approve(client).status_code == 200
    elif mutation == "policy":
        change(db, Source, provider_id="OTHER")
    elif mutation == "ownership":
        change(db, Content, source_id=2)
    elif mutation == "fake":
        proof_id = 999
    elif mutation == "membership":
        db.execute(delete(Membership).where(Membership.topic_id == 1))
        db.commit()
    elif mutation == "selector":
        overrides["disease_group_id"] = "5"
    elif mutation == "fingerprint":
        assert approve(client).status_code == 200
        version = 2
        change(db, Source, title="Changed identity")
    before, count = current(db), len(history(db))
    response = approve(client, version=version, evidence_content_id=proof_id, **overrides)
    expected = 409 if mutation in {"stale", "fingerprint"} else 404 if mutation == "fake" else 422
    assert response.status_code == expected, response.text
    assert current(db) == before and len(history(db)) == count


def test_preview_for_source_a_cannot_approve_source_b(client, db):
    assert preview(client).status_code == 200
    db.add(Membership(topic_id=1, source_id=2))
    db.commit()
    assert create(client, source_id=2).status_code == 201
    assert approve(client, evidence_content_id=1).status_code == 422
    assert current(db)["evidence_content_id"] is None


@pytest.mark.parametrize("username,user_id", [("staff", 1), ("admin", 2)])
def test_session_tracked_jwt_preview_is_read_only_including_auth(client, db, monkeypatch, username, user_id):
    tracked_session = LoginSession(id=1, user_id=user_id, created_at=NOW, last_seen_at=NOW)
    db.add(tracked_session)
    db.commit()
    calls = dict(flush=0, commit=0)

    def forbid(name):
        def forbidden(*_args, **_kwargs):
            calls[name] += 1
            raise AssertionError("GET proof-candidates including authentication must not commit/flush")
        return forbidden

    monkeypatch.setattr(db, "commit", forbid("commit"))
    monkeypatch.setattr(db, "flush", forbid("flush"))
    with select_only(db):
        response = client.get(PATH, params={key: value for key, value in {**SELECTOR, "source_id": 1}.items()
                                           if value is not None}, headers=auth(username, sid=1))
    assert response.status_code == 200
    assert response.json()["candidates"][0]["evidence_content_id"] == 1
    assert calls == dict(flush=0, commit=0)
    assert tracked_session.last_seen_at == NOW and not db.dirty
    with db.no_autoflush:
        assert db.scalar(select(LoginSession.last_seen_at).where(LoginSession.id == 1)) == NOW


@pytest.mark.parametrize("case,status", [
    ("valid_staff", 200), ("valid_admin", 200), ("no_sid", 200),
    ("anonymous", 401), ("nonstaff", 403), ("inactive", 401), ("revoked", 401),
    ("missing_session", 401), ("wrong_owner", 401), ("expired", 401), ("malformed", 401),
    ("signature", 401), ("role_spoof", 403), ("missing_subject", 401),
])
def test_read_only_auth_keeps_actual_token_user_session_role_checks(client, db, monkeypatch, case, status):
    user_id = 2 if case == "valid_admin" else 1
    tracked = LoginSession(id=1, user_id=user_id, created_at=NOW, last_seen_at=NOW,
                           revoked_at=NOW if case == "revoked" else None)
    db.add(tracked)
    db.commit()
    username = {"valid_admin": "admin", "nonstaff": "parent", "role_spoof": "parent",
                "inactive": "inactive"}.get(case, "staff")
    sid = 999 if case == "missing_session" else 1
    claims = dict(sub=username, sid=sid)
    if case == "role_spoof":
        claims["role"] = "admin"
        claims.pop("sid")  # Exercise the role check, not a session-owner denial.
    if case in {"no_sid", "nonstaff"}:
        claims.pop("sid")
    if case == "wrong_owner":
        tracked.user_id = 2
        db.commit()
    if case == "missing_subject":
        claims.pop("sub")
    token = create_access_token(claims, expires_delta=-timedelta(seconds=10) if case == "expired" else None)
    if case == "malformed":
        token = "not-a-jwt"
    if case == "signature":
        head, payload, signature = token.split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        token = f"{head}.{payload}.{signature}"
    headers = {} if case == "anonymous" else {"Authorization": f"Bearer {token}"}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Auth checks must not flush/commit, including denied requests")

    monkeypatch.setattr(db, "flush", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    with select_only(db):
        response = client.get(PATH, params={key: value for key, value in {**SELECTOR, "source_id": 1}.items()
                                           if value is not None}, headers=headers)
    assert response.status_code == status, response.text
    assert tracked.last_seen_at == NOW and not db.dirty
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


def test_pending_orm_state_survives_entire_read_only_request_without_autoflush(client, db, monkeypatch):
    tracked = LoginSession(id=1, user_id=1, created_at=NOW, last_seen_at=NOW)
    db.add(tracked)
    db.commit()
    stored_source = db.get(Source, 1)
    stored_source.title = "PENDING TITLE"
    pending = Source(source_type="OTHER", title="UNFLUSHED SOURCE")
    db.add(pending)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Pending state must not be flushed/committed by GET")

    monkeypatch.setattr(db, "flush", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    with select_only(db):
        response = client.get(PATH, params={key: value for key, value in {**SELECTOR, "source_id": 1}.items()
                                           if value is not None}, headers=auth(sid=1))
    assert response.status_code == 200
    assert response.json()["source"]["title"] != stored_source.title
    assert pending.id is None and pending in db.new and stored_source in db.dirty
    assert tracked.last_seen_at == NOW and tracked not in db.dirty


@pytest.mark.parametrize("username,user_id", [("staff", 1), ("admin", 2)])
def test_existing_route_still_touches_session_after_read_only_preview(client, db, username, user_id):
    tracked = LoginSession(id=1, user_id=user_id, created_at=NOW, last_seen_at=NOW)
    db.add(tracked)
    db.commit()
    params = {key: value for key, value in {**SELECTOR, "source_id": 1}.items() if value is not None}
    assert client.get(PATH, params=params, headers=auth(username, sid=1)).status_code == 200
    assert tracked.last_seen_at == NOW
    # The old list route still uses get_current_user, including session touch/commit.
    params.pop("source_id")
    assert client.get(BASE, params=params, headers=auth(username, sid=1)).status_code == 200
    persisted = db.scalar(select(LoginSession.last_seen_at).where(LoginSession.id == 1))
    assert persisted > NOW and tracked.last_seen_at == persisted
