from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.analytics import (
    compute_cgm_coverage,
    compute_glucose_drift,
    compute_glucose_summary,
    evaluate_single_meal_response,
)
from app.analytics.baselines import GlucosePoint, prepare_glucose_points
from app.core.database import get_engine
from app.core.rate_limit import reset_rate_limiter
from app.ingestion import ingest_shanghai_t2dm, seed_synthetic_demo_patient
from app.main import app
from app.models import AuditLog, DatasetImport, GlucoseReading, Patient, User

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


# ===========================================================================
# GROUP A TESTS — Provenance must default to 'unknown', CBG excluded from CGM
# ===========================================================================
def test_group_a_missing_or_none_provenance_defaults_to_unknown():
    ts = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)

    # 1. Dict with missing key and Dict with None
    pts = prepare_glucose_points(
        [
            {"id": "p-missing", "recorded_at": ts, "glucose_mg_dl": 120.0, "source_dataset": "shanghai_t2dm"},
            {"id": "p-none", "recorded_at": ts + timedelta(minutes=15), "glucose_mg_dl": 125.0, "source_dataset": "shanghai_t2dm", "observation_provenance": None},
        ]
    )
    assert pts[0].observation_provenance == "unknown"
    assert pts[1].observation_provenance == "unknown"

    # 2. GlucosePoint dataclass default
    gp = GlucosePoint(record_id="gp-1", recorded_at=ts, glucose_mg_dl=110.0, source_dataset="shanghai_t2dm")
    assert gp.observation_provenance == "unknown"

    # 3. ORM model & DB column default
    col_default = GlucoseReading.__table__.c.observation_provenance.server_default
    assert col_default is not None and "unknown" in str(col_default.arg)


def test_group_a_shanghai_default_unknown_and_requires_evidence_reference():
    engine = get_engine()
    conn = engine.connect()
    outer_tx = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        rows = [
            {"Date": "2023-01-01 08:00:00", "CGM (mg / dl)": 118.0, "CBG (mg / dl)": 120.0},
            {"Date": "2023-01-01 08:15:00", "CGM (mg / dl)": 124.0},
        ]
        # 1. Default Shanghai import yields 'unknown' (not 'native')
        rep_default = ingest_shanghai_t2dm(
            db,
            participant_sources={"9101_0_20230101": rows},
        )
        assert rep_default.observation_provenance_counts["native"] == 0
        assert rep_default.observation_provenance_counts["unknown"] == 3

        # 2. Passing source_verified_native_export=True without native_evidence_reference raises ValueError
        with pytest.raises(ValueError, match="native_evidence_reference"):
            ingest_shanghai_t2dm(
                db,
                participant_sources={"9102_0_20230101": rows},
                source_verified_native_export=True,
            )

        # 3. With non-empty native_evidence_reference: CGM rows become 'native', CBG row stays 'unknown' (never native CGM!)
        citation = "Zhao et al., Scientific Data 10:35 (2023), Table 2: FreeStyle Libre H 15-min sensor recordings"
        rep_verified = ingest_shanghai_t2dm(
            db,
            participant_sources={"9103_0_20230101": rows},
            source_verified_native_export=True,
            native_evidence_reference=citation,
        )
        assert rep_verified.observation_provenance_counts["native"] == 2  # Only the 2 CGM rows
        assert rep_verified.observation_provenance_counts["unknown"] == 1  # The 1 CBG row is never native CGM

        imp = db.get(DatasetImport, uuid.UUID(rep_verified.dataset_import_id))
        assert imp is not None
        assert imp.quality_report_summary["native_evidence_reference"] == citation

        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.resource_type == "dataset_import",
                AuditLog.resource_id == rep_verified.dataset_import_id,
            )
        )
        assert audit is not None
        assert audit.context_metadata.get("native_evidence_reference") == citation
    finally:
        db.close()
        outer_tx.rollback()
        conn.close()


def test_group_a_cbg_excluded_from_cgm_analytics_and_endpoint_native_only_params():
    base_ts = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    mixed_type_readings = [
        {
            "id": "cgm-native-1",
            "recorded_at": base_ts,
            "glucose_mg_dl": 100.0,
            "reading_type": "cgm",
            "observation_provenance": "native",
            "source_dataset": "shanghai_t2dm",
        },
        {
            "id": "cgm-unknown-1",
            "recorded_at": base_ts + timedelta(minutes=15),
            "glucose_mg_dl": 200.0,
            "reading_type": "cgm",
            "observation_provenance": "unknown",
            "source_dataset": "shanghai_t2dm",
        },
        {
            "id": "cbg-1",
            "recorded_at": base_ts + timedelta(minutes=30),
            "glucose_mg_dl": 400.0,
            "reading_type": "cbg",
            "observation_provenance": "native",
            "source_dataset": "shanghai_t2dm",
        },
        {
            "id": "fasting-1",
            "recorded_at": base_ts + timedelta(minutes=45),
            "glucose_mg_dl": 350.0,
            "reading_type": "fasting",
            "observation_provenance": "native",
            "source_dataset": "app_user",
        },
    ]

    # 1. Native-only CGM summary: excludes the 2 non-CGM rows AND excludes the 1 unknown CGM row
    s_native = compute_glucose_summary(mixed_type_readings, native_only=True)
    assert s_native.observation_count == 1
    assert s_native.mean_glucose_mg_dl == 100.0
    assert s_native.excluded_non_cgm_count == 2
    assert s_native.excluded_non_native_count == 1
    assert s_native.provenance_filter_mode == "native_only"
    assert any("non-CGM" in n for n in s_native.coverage.uncertainty_notes)

    # 2. Include non-native CGM summary: includes the unknown CGM row (mean of 100 and 200 = 150), still excludes CBG/fasting!
    s_all_cgm = compute_glucose_summary(mixed_type_readings, native_only=False)
    assert s_all_cgm.observation_count == 2
    assert s_all_cgm.mean_glucose_mg_dl == 150.0
    assert s_all_cgm.excluded_non_cgm_count == 2
    assert s_all_cgm.excluded_non_native_count == 0
    assert s_all_cgm.provenance_filter_mode == "include_non_native"

    # 3. Endpoint test: native_only=true vs include_non_native=true returns different counts
    email = f"groupa-{uuid.uuid4().hex[:8]}@example.com"
    engine = get_engine()
    try:
        client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
        login = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        create_p = client.post(
            "/api/v1/patients",
            json={"display_name": "Group A User", "consent_granted": True, "consent_version": "v1.0"},
            headers=headers,
        )
        assert create_p.status_code == 201
        pid = create_p.json()["id"]

        # Log 1 manual fasting reading via tracking API -> provenance must NOT be 'native' CGM
        post_fast = client.post(
            f"/api/v1/patients/{pid}/glucose",
            json={
                "recorded_at": base_ts.isoformat(),
                "raw_value": 115.0,
                "raw_unit": "mg/dL",
                "reading_type": "fasting",
            },
            headers=headers,
        )
        assert post_fast.status_code == 201
        assert post_fast.json()["observation_provenance"] == "unknown"

        # Insert 1 native CGM and 1 unknown CGM for this patient
        with Session(engine) as db:
            db.add_all(
                [
                    GlucoseReading(
                        patient_id=uuid.UUID(pid),
                        cohort_type="app_user",
                        recorded_at=base_ts + timedelta(minutes=15),
                        glucose_mg_dl=120.0,
                        raw_value=120.0,
                        raw_unit="mg/dL",
                        reading_type="cgm",
                        device_id="User_CGM",
                        sampling_interval_min=15,
                        observation_provenance="native",
                        source_dataset="app_user",
                    ),
                    GlucoseReading(
                        patient_id=uuid.UUID(pid),
                        cohort_type="app_user",
                        recorded_at=base_ts + timedelta(minutes=30),
                        glucose_mg_dl=180.0,
                        raw_value=180.0,
                        raw_unit="mg/dL",
                        reading_type="cgm",
                        device_id="User_CGM",
                        sampling_interval_min=15,
                        observation_provenance="unknown",
                        source_dataset="app_user",
                    ),
                ]
            )
            db.commit()

        r_native = client.get(f"/api/v1/patients/{pid}/analytics/summary?native_only=true", headers=headers)
        assert r_native.status_code == 200
        d_native = r_native.json()
        assert d_native["observation_count"] == 1
        assert d_native["excluded_non_cgm_count"] == 1
        assert d_native["excluded_non_native_count"] == 1
        assert d_native["provenance_filter_mode"] == "native_only"

        r_non_native = client.get(
            f"/api/v1/patients/{pid}/analytics/summary?include_non_native=true", headers=headers
        )
        assert r_non_native.status_code == 200
        d_non_native = r_non_native.json()
        assert d_non_native["observation_count"] == 2
        assert d_non_native["excluded_non_cgm_count"] == 1
        assert d_non_native["excluded_non_native_count"] == 0
        assert d_non_native["provenance_filter_mode"] == "include_non_native"
    finally:
        with Session(engine) as db:
            u = db.scalar(select(User).where(User.email == email))
            if u is not None:
                for p in db.scalars(select(Patient).where(Patient.user_id == u.id)).all():
                    p.retention_expires_at = None
                    db.flush()
                    db.delete(p)
                db.flush()
                db.delete(u)
                db.commit()
