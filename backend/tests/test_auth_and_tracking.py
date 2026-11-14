import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.main import app
from app.models import Patient, User

client = TestClient(app)


def _cleanup_users_and_patients(emails: list[str], patient_ids: list[str]) -> None:
    engine = get_engine()
    assert engine is not None
    with Session(bind=engine) as db:
        for pid in patient_ids:
            p = db.get(Patient, uuid.UUID(pid))
            if p:
                db.delete(p)
        for email in emails:
            u = db.query(User).filter(User.email == email).one_or_none()
            if u:
                db.delete(u)
        db.commit()


def test_auth_lifecycle_rbac_and_tracking_crud() -> None:
    email_a = f"a-{uuid.uuid4()}@example.com"
    email_b = f"b-{uuid.uuid4()}@example.com"
    created_patients: list[str] = []

    try:
        # 1. Register & Login User A and User B
        assert client.post("/api/v1/auth/register", json={"email": email_a, "password": "Password123!"}).status_code == 201
        assert client.post("/api/v1/auth/register", json={"email": email_b, "password": "Password123!"}).status_code == 201

        login_a = client.post("/api/v1/auth/login", json={"email": email_a, "password": "Password123!"})
        assert login_a.status_code == 200
        tokens_a = login_a.json()
        headers_a = {"Authorization": f"Bearer {tokens_a['access_token']}"}

        login_b = client.post("/api/v1/auth/login", json={"email": email_b, "password": "Password123!"})
        assert login_b.status_code == 200
        headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

        # 2. Refresh rotates token & invalidates old jti
        ref_res = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens_a["refresh_token"]})
        assert ref_res.status_code == 200
        new_tokens_a = ref_res.json()
        assert client.get("/api/v1/auth/me", headers=headers_a).status_code == 401
        headers_a = {"Authorization": f"Bearer {new_tokens_a['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers_a).status_code == 200

        # 3. Consent validation on onboarding
        bad_onboard = client.post(
            "/api/v1/patients",
            headers=headers_a,
            json={
                "display_name": "Patient A",
                "consent_granted": False,
                "consent_version": "v1.0",
            },
        )
        assert bad_onboard.status_code == 422

        onboard = client.post(
            "/api/v1/patients",
            headers=headers_a,
            json={
                "display_name": "Patient A",
                "diabetes_type": "T2D",
                "dietary_restrictions": ["halal"],
                "cultural_cuisine_pref": "South Asian",
                "consent_granted": True,
                "consent_version": "v1.0",
                "retention_policy": "365_days",
            },
        )
        assert onboard.status_code == 201
        pid_a = onboard.json()["id"]
        created_patients.append(pid_a)

        # 4. Patient-level RBAC: User B cannot read or write Patient A
        assert client.get(f"/api/v1/patients/{pid_a}", headers=headers_b).status_code == 403
        assert (
            client.post(
                f"/api/v1/patients/{pid_a}/glucose",
                headers=headers_b,
                json={
                    "recorded_at": "2026-11-14T08:00:00Z",
                    "raw_value": 115,
                    "raw_unit": "mg/dL",
                    "reading_type": "fasting",
                },
            ).status_code
            == 403
        )

        # 5. Glucose CRUD + mmol/L conversion + naive timestamp rejection + Idempotency-Key
        naive_g = client.post(
            f"/api/v1/patients/{pid_a}/glucose",
            headers=headers_a,
            json={
                "recorded_at": "2026-11-14T08:00:00",
                "raw_value": 110,
                "raw_unit": "mg/dL",
                "reading_type": "fasting",
            },
        )
        assert naive_g.status_code == 422

        idem = f"idem-{uuid.uuid4()}"
        g1 = client.post(
            f"/api/v1/patients/{pid_a}/glucose",
            headers={**headers_a, "Idempotency-Key": idem},
            json={
                "recorded_at": "2026-11-14T08:00:00Z",
                "raw_value": 6.5,
                "raw_unit": "mmol/L",
                "reading_type": "fasting",
            },
        )
        assert g1.status_code == 201
        assert round(g1.json()["glucose_mg_dl"], 1) == 117.1

        g1_dup = client.post(
            f"/api/v1/patients/{pid_a}/glucose",
            headers={**headers_a, "Idempotency-Key": idem},
            json={
                "recorded_at": "2026-11-14T08:00:00Z",
                "raw_value": 6.5,
                "raw_unit": "mmol/L",
                "reading_type": "fasting",
            },
        )
        assert g1_dup.json()["id"] == g1.json()["id"]

        # Date range validation
        assert (
            client.get(
                f"/api/v1/patients/{pid_a}/glucose",
                headers=headers_a,
                params={"start": "2026-11-15T00:00:00Z", "end": "2026-11-14T00:00:00Z"},
            ).status_code
            == 400
        )

        # 6. Meals, Medications + Events, Wellbeing (null illness_flag), Activity & Timeline
        m = client.post(
            f"/api/v1/patients/{pid_a}/meals",
            headers=headers_a,
            json={
                "logged_at": "2026-11-14T13:00:00Z",
                "meal_type": "lunch",
                "description": "Daal with whole-wheat roti",
                "carbs_g": 45,
                "protein_g": 16,
                "fiber_g": 9,
                "cultural_tag": "south_asian",
            },
        )
        assert m.status_code == 201

        med = client.post(
            f"/api/v1/patients/{pid_a}/medications",
            headers=headers_a,
            json={"medication_name": "Metformin", "recorded_dose": "500mg", "prescribed_schedule": "BID"},
        )
        assert med.status_code == 201
        med_id = med.json()["id"]

        me = client.post(
            f"/api/v1/patients/{pid_a}/medications/events",
            headers=headers_a,
            json={
                "medication_id": med_id,
                "event_time": "2026-11-14T08:15:00Z",
                "status": "taken",
            },
        )
        assert me.status_code == 201

        wb = client.post(
            f"/api/v1/patients/{pid_a}/wellbeing",
            headers=headers_a,
            json={
                "logged_at": "2026-11-14T21:00:00Z",
                "stress_score": 4,
                "fatigue_score": 3,
                "sleep_hours": 6.5,
                "illness_flag": None,
            },
        )
        assert wb.status_code == 201
        assert wb.json()["illness_flag"] is None

        act = client.post(
            f"/api/v1/patients/{pid_a}/activity",
            headers=headers_a,
            json={
                "recorded_at": "2026-11-14T17:30:00Z",
                "steps": 6200,
                "active_minutes": 35,
                "activity_type": "walking",
                "intensity": "moderate",
            },
        )
        assert act.status_code == 201

        timeline = client.get(f"/api/v1/patients/{pid_a}/timeline", headers=headers_a)
        assert timeline.status_code == 200
        assert timeline.json()["total"] == 5

        # 7. Logout revokes jti immediately
        assert client.post("/api/v1/auth/logout", headers=headers_a).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers_a).status_code == 401
    finally:
        _cleanup_users_and_patients([email_a, email_b], created_patients)
