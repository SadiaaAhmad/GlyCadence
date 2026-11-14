from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_engine
from app.core.rate_limit import reset_rate_limiter
from app.core.security import hash_password, hash_token
from app.main import app
from app.models import AuditLog, GlucoseReading, Patient, User, UserSession

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def _cleanup_test_entities(emails: list[str], patient_ids: list[uuid.UUID]) -> None:
    engine = get_engine()
    with Session(engine) as db:
        for pid in patient_ids:
            patient = db.get(Patient, pid)
            if patient is not None and patient.cohort_type != "research_participant":
                patient.retention_expires_at = None
                patient.retention_policy = "365_days"
                db.flush()
                db.delete(patient)
        for email in emails:
            user = db.scalar(select(User).where(User.email == email))
            if user is not None:
                db.delete(user)
        db.commit()


def _register_and_login(email: str, password: str = "StrongPass123!") -> dict:
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg.status_code == 201, reg.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()


# ---------------------------------------------------------------------------
# A. Refresh-token security (hashed at rest, rotation, replay, logout)
# ---------------------------------------------------------------------------
def test_refresh_token_hashed_rotation_replay_and_logout():
    email = f"sec-rt-{uuid.uuid4().hex[:10]}@example.com"
    try:
        tokens = _register_and_login(email)
        access_1 = tokens["access_token"]
        refresh_1 = tokens["refresh_token"]

        engine = get_engine()
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None
            session = db.scalar(select(UserSession).where(UserSession.user_id == user.id))
            assert session is not None
            # Refresh token must never be stored in plaintext
            assert session.refresh_token_hash != refresh_1
            assert session.refresh_token_hash == hash_token(refresh_1)
            assert session.previous_refresh_token_hash is None

        # Rotate refresh token
        rot = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
        assert rot.status_code == 200, rot.text
        rot_data = rot.json()
        access_2 = rot_data["access_token"]
        refresh_2 = rot_data["refresh_token"]
        assert refresh_2 != refresh_1

        # Old access token (jti_1) is now invalid
        me_old = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_1}"})
        assert me_old.status_code == 401

        # New access token works
        me_new = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_2}"})
        assert me_new.status_code == 200

        # Replaying already-rotated refresh_1 must trigger session revocation
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "refresh_token_replayed"

        # Active session and refresh_2 must now be revoked
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            session = db.scalar(select(UserSession).where(UserSession.user_id == user.id))
            assert session is not None
            assert session.revoked_at is not None

        after_replay_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_2})
        assert after_replay_refresh.status_code == 401

        after_replay_access = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_2}"})
        assert after_replay_access.status_code == 401

        # Fresh login + logout invalidates both session and access token
        login_2 = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        assert login_2.status_code == 200
        tokens_2 = login_2.json()
        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens_2['access_token']}"},
        )
        assert logout.status_code in (200, 204)
        assert client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens_2['access_token']}"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens_2["refresh_token"]},
        ).status_code == 401
    finally:
        _cleanup_test_entities([email], [])


# ---------------------------------------------------------------------------
# B. Password & authentication security (bcrypt, generic errors, rate limit, JWT env)
# ---------------------------------------------------------------------------
def test_password_bcrypt_generic_login_errors_and_jwt_env_validation():
    email = f"sec-pw-{uuid.uuid4().hex[:10]}@example.com"
    try:
        client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
        engine = get_engine()
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None
            assert user.password_hash.startswith("$2b$")
            assert "StrongPass123!" not in user.password_hash

        unknown_resp = client.post(
            "/api/v1/auth/login",
            json={"email": f"missing-{uuid.uuid4().hex[:8]}@example.com", "password": "WrongPassword1!"},
        )
        wrong_pw_resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword1!"},
        )
        assert unknown_resp.status_code == 401
        assert wrong_pw_resp.status_code == 401
        assert unknown_resp.json()["detail"] == wrong_pw_resp.json()["detail"]

        # Non-development environment must reject default insecure JWT secret
        with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
            Settings(app_env="production", jwt_secret_key="dev-only-insecure-fallback-change-in-env")
    finally:
        _cleanup_test_entities([email], [])


def test_auth_rate_limiting_returns_429():
    # 10 requests allowed per 60s window; 11th returns 429
    for i in range(10):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": f"ratelimit-{i}@example.com", "password": "WrongPassword1!"},
        )
        assert resp.status_code == 401

    limited = client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit-11@example.com", "password": "WrongPassword1!"},
    )
    assert limited.status_code == 429


# ---------------------------------------------------------------------------
# C. Audit log immutability (PostgreSQL trigger blocks UPDATE / DELETE)
# ---------------------------------------------------------------------------
def test_audit_log_immutability_and_event_recording():
    email = f"sec-audit-{uuid.uuid4().hex[:10]}@example.com"
    try:
        tokens = _register_and_login(email)
        engine = get_engine()
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None
            audit = db.scalar(
                select(AuditLog)
                .where(AuditLog.actor_user_id == user.id)
                .order_by(AuditLog.created_at.desc())
            )
            assert audit is not None
            audit_id = audit.id

            with pytest.raises(DBAPIError, match="append-only"):
                db.execute(
                    text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
                    {"id": audit_id},
                )
            db.rollback()

            with pytest.raises(DBAPIError, match="append-only"):
                db.execute(
                    text("DELETE FROM audit_logs WHERE id = :id"),
                    {"id": audit_id},
                )
            db.rollback()

        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            actions = set(
                db.scalars(select(AuditLog.action).where(AuditLog.actor_user_id == user.id)).all()
            )
            assert {"login", "revoke_token"}.issubset(actions)
    finally:
        _cleanup_test_entities([email], [])


# ---------------------------------------------------------------------------
# D. Research and synthetic cohort isolation
# ---------------------------------------------------------------------------
def test_research_and_synthetic_cohort_isolation():
    email = f"sec-cohort-{uuid.uuid4().hex[:10]}@example.com"
    created_patient_ids: list[uuid.UUID] = []
    try:
        tokens = _register_and_login(email)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        engine = get_engine()
        with Session(engine) as db:
            # Reuse a single deterministic research_participant row (protected from hard delete)
            research_patient = db.scalar(
                select(Patient).where(
                    Patient.cohort_type == "research_participant",
                    Patient.external_id == "test-sec-research-001",
                )
            )
            if research_patient is None:
                research_patient = Patient(
                    cohort_type="research_participant",
                    external_id="test-sec-research-001",
                    display_name="Research Isolation Test",
                    retention_policy="research_archive",
                )
                db.add(research_patient)
                db.flush()

            synthetic_patient = Patient(
                cohort_type="synthetic_demo",
                external_id=f"test-sec-synth-{uuid.uuid4().hex[:8]}",
                display_name="Synthetic Isolation Test",
                retention_policy="365_days",
            )
            db.add(synthetic_patient)
            db.commit()
            research_id = research_patient.id
            synthetic_id = synthetic_patient.id
            created_patient_ids.append(synthetic_id)

        # app_user cannot read research_participant (profile, glucose, timeline)
        assert client.get(f"/api/v1/patients/{research_id}", headers=headers).status_code == 403
        assert client.get(f"/api/v1/patients/{research_id}/glucose", headers=headers).status_code == 403
        assert client.get(f"/api/v1/patients/{research_id}/timeline", headers=headers).status_code == 403

        # app_user can read synthetic_demo, but cannot modify it
        assert client.get(f"/api/v1/patients/{synthetic_id}", headers=headers).status_code == 200
        assert (
            client.patch(
                f"/api/v1/patients/{synthetic_id}",
                headers=headers,
                json={"display_name": "Tampered"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/patients/{synthetic_id}/glucose",
                headers=headers,
                json={
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "raw_value": 115,
                    "raw_unit": "mg/dL",
                    "reading_type": "cbg",
                },
            ).status_code
            == 403
        )
    finally:
        _cleanup_test_entities([email], created_patient_ids)


# ---------------------------------------------------------------------------
# E. Data deletion & retention enforcement preserves audit_logs and research data
# ---------------------------------------------------------------------------
def test_retention_trigger_and_audit_log_preservation_on_patient_delete():
    email = f"sec-ret-{uuid.uuid4().hex[:10]}@example.com"
    patient_id: uuid.UUID | None = None
    try:
        tokens = _register_and_login(email)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        onboard = client.post(
            "/api/v1/patients",
            headers=headers,
            json={
                "display_name": "Retention Patient",
                "consent_granted": True,
                "consent_version": "v1.0",
                "retention_days": 365,
            },
        )
        assert onboard.status_code == 201, onboard.text
        patient_id = uuid.UUID(onboard.json()["id"])
        original_patient_id = patient_id

        engine = get_engine()
        with Session(engine) as db:
            # Unexpired app_user patient cannot be hard-deleted while retention_expires_at > NOW()
            with pytest.raises(DBAPIError, match="retention"):
                db.execute(text("DELETE FROM patients WHERE id = :id"), {"id": patient_id})
            db.rollback()

            # research_participant cannot be hard-deleted either
            research_patient = db.scalar(
                select(Patient).where(
                    Patient.cohort_type == "research_participant",
                    Patient.external_id == "test-sec-research-001",
                )
            )
            if research_patient is not None:
                with pytest.raises(DBAPIError, match="retention"):
                    db.execute(text("DELETE FROM patients WHERE id = :id"), {"id": research_patient.id})
                db.rollback()

            # Verify audit logs exist for this patient, then expire retention and delete patient
            audit_ids = list(
                db.scalars(select(AuditLog.id).where(AuditLog.patient_id == patient_id)).all()
            )
            assert len(audit_ids) >= 1

            patient = db.get(Patient, patient_id)
            assert patient is not None
            patient.retention_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()

            db.delete(patient)
            db.commit()
            patient_id = None

            # Audit log rows must still exist untouched with original patient_id
            for aid in audit_ids:
                kept = db.get(AuditLog, aid)
                assert kept is not None
                assert kept.patient_id == original_patient_id
    finally:
        _cleanup_test_entities([email], [patient_id] if patient_id else [])
