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


# ===========================================================================
# GROUP B TESTS — Dual-CGM handling and evidence integrity
# ===========================================================================
def test_group_b_dual_device_order_invariance_and_multi_device_422():
    ts = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    libre = {
        "id": "libre-1",
        "recorded_at": ts,
        "glucose_mg_dl": 150.0,
        "reading_type": "cgm",
        "device_id": "FreeStyle_Libre_Pro",
        "sampling_interval_min": 15,
        "observation_provenance": "native",
        "source_dataset": "cgmacros",
    }
    dexcom = {
        "id": "dexcom-1",
        "recorded_at": ts,
        "glucose_mg_dl": 160.0,
        "reading_type": "cgm",
        "device_id": "Dexcom_G6_Pro",
        "sampling_interval_min": 5,
        "observation_provenance": "native",
        "source_dataset": "cgmacros",
    }

    # 1. prepare_glucose_points default deduplicate_across_devices=False preserves both and is order-invariant
    pts_a = prepare_glucose_points([libre, dexcom])
    pts_b = prepare_glucose_points([dexcom, libre])
    assert len(pts_a) == 2
    assert pts_a == pts_b

    # 2. Multi-device without device_id raises ValueError('multiple_devices_specify_device_id')
    with pytest.raises(ValueError, match="multiple_devices_specify_device_id"):
        compute_glucose_summary([libre, dexcom], native_only=True)

    # 3. Specifying device_id selects only that device
    sum_libre = compute_glucose_summary([libre, dexcom], device_id="FreeStyle_Libre_Pro", native_only=True)
    assert sum_libre.observation_count == 1
    assert sum_libre.mean_glucose_mg_dl == 150.0
    assert sum_libre.device_id == "FreeStyle_Libre_Pro"

    sum_dexcom = compute_glucose_summary([dexcom, libre], device_id="Dexcom_G6_Pro", native_only=True)
    assert sum_dexcom.observation_count == 1
    assert sum_dexcom.mean_glucose_mg_dl == 160.0
    assert sum_dexcom.device_id == "Dexcom_G6_Pro"

    # 4. API endpoint returns 422 multiple_devices_specify_device_id with devices_present when >1 device exists
    email = f"groupb-{uuid.uuid4().hex[:8]}@example.com"
    engine = get_engine()
    try:
        client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
        login = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        create_p = client.post(
            "/api/v1/patients",
            json={"display_name": "Group B User", "consent_granted": True, "consent_version": "v1.0"},
            headers=headers,
        )
        pid = create_p.json()["id"]

        with Session(engine) as db:
            db.add_all(
                [
                    GlucoseReading(
                        patient_id=uuid.UUID(pid),
                        cohort_type="app_user",
                        recorded_at=ts,
                        glucose_mg_dl=150.0,
                        raw_value=150.0,
                        raw_unit="mg/dL",
                        reading_type="cgm",
                        device_id="FreeStyle_Libre_Pro",
                        sampling_interval_min=15,
                        observation_provenance="native",
                        source_dataset="app_user",
                    ),
                    GlucoseReading(
                        patient_id=uuid.UUID(pid),
                        cohort_type="app_user",
                        recorded_at=ts,
                        glucose_mg_dl=160.0,
                        raw_value=160.0,
                        raw_unit="mg/dL",
                        reading_type="cgm",
                        device_id="Dexcom_G6_Pro",
                        sampling_interval_min=5,
                        observation_provenance="native",
                        source_dataset="app_user",
                    ),
                ]
            )
            db.commit()

        r_multi = client.get(f"/api/v1/patients/{pid}/analytics/summary", headers=headers)
        assert r_multi.status_code == 422
        detail = r_multi.json()["detail"]
        assert detail["code"] == "multiple_devices_specify_device_id"
        assert set(detail["devices_present"]) == {"Dexcom_G6_Pro", "FreeStyle_Libre_Pro"}

        r_single = client.get(
            f"/api/v1/patients/{pid}/analytics/summary?device_id=FreeStyle_Libre_Pro",
            headers=headers,
        )
        assert r_single.status_code == 200
        assert r_single.json()["mean_glucose_mg_dl"] == 150.0
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


def test_group_b_evidence_truncation_checksum_iauc_units_tbr_tar_and_single_reading_cv_none():
    base_ts = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)

    # 1. Single reading -> sd_glucose_mg_dl is None and cv_pct is None (not 0.0)
    one_reading = [
        {
            "id": "single-1",
            "recorded_at": base_ts,
            "glucose_mg_dl": 125.0,
            "reading_type": "cgm",
            "observation_provenance": "native",
            "source_dataset": "shanghai_t2dm",
        }
    ]
    s_one = compute_glucose_summary(one_reading, native_only=True)
    assert s_one.observation_count == 1
    assert s_one.sd_glucose_mg_dl is None
    assert s_one.cv_pct is None

    # 2. 500 readings -> source_records_total == 500, source_records_truncated is True, checksum present,
    #    and TBR / TBR2 / TAR / TAR2 EvidenceItems emitted
    readings_500 = [
        {
            "id": f"rec-{i:04d}",
            "recorded_at": base_ts + timedelta(minutes=15 * i),
            "glucose_mg_dl": 50.0 if i == 0 else (65.0 if i == 1 else (195.0 if i == 2 else (260.0 if i == 3 else 120.0))),
            "reading_type": "cgm",
            "observation_provenance": "native",
            "source_dataset": "shanghai_t2dm",
        }
        for i in range(500)
    ]
    s_500 = compute_glucose_summary(readings_500, native_only=True)
    assert s_500.observation_count == 500
    ev_by_name = {e.metric_name: e for e in s_500.evidence_items}
    assert {
        "mean_glucose_mg_dl",
        "glucose_cv_pct",
        "time_in_range_70_180_pct",
        "time_below_range_lt_70_pct",
        "time_below_range_level2_lt_54_pct",
        "time_above_range_gt_180_pct",
        "time_above_range_level2_gt_250_pct",
    }.issubset(set(ev_by_name.keys()))
    mean_ev = ev_by_name["mean_glucose_mg_dl"]
    assert len(mean_ev.source_records) == 200
    assert mean_ev.source_records_total == 500
    assert mean_ev.source_records_truncated is True
    assert len(mean_ev.source_record_set_checksum) == 64

    # 3. iAUC evidence items have separate metrics with unmixed units
    meal_ts = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    meal_readings = [
        {"id": "m-anchor", "recorded_at": meal_ts - timedelta(minutes=10), "glucose_mg_dl": 100.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
        {"id": "m-1", "recorded_at": meal_ts + timedelta(minutes=15), "glucose_mg_dl": 120.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
        {"id": "m-2", "recorded_at": meal_ts + timedelta(minutes=30), "glucose_mg_dl": 140.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
        {"id": "m-3", "recorded_at": meal_ts + timedelta(minutes=60), "glucose_mg_dl": 160.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
        {"id": "m-4", "recorded_at": meal_ts + timedelta(minutes=90), "glucose_mg_dl": 120.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
        {"id": "m-5", "recorded_at": meal_ts + timedelta(minutes=120), "glucose_mg_dl": 90.0, "reading_type": "cgm", "observation_provenance": "native", "source_dataset": "cgmacros"},
    ]
    m_res = evaluate_single_meal_response(
        meal_id="meal-b-1",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Group B Meal",
        carbs_g=50.0,
        meal_source_dataset="cgmacros",
        glucose_readings=meal_readings,
    )
    assert m_res.iauc_valid is True
    assert m_res.evidence is not None
    assert m_res.evidence.metric_name == "postprandial_iauc_mg_dl_min"
    assert m_res.evidence.unit == "mg/dL*min"
    assert m_res.evidence.baseline_value is None
    assert m_res.evidence.delta is None

    meal_ev_map = {e.metric_name: e for e in m_res.evidence_items}
    assert set(meal_ev_map.keys()) == {
        "postprandial_iauc_mg_dl_min",
        "pre_meal_baseline_glucose_mg_dl",
        "postprandial_peak_excursion_mg_dl",
    }
    assert meal_ev_map["pre_meal_baseline_glucose_mg_dl"].unit == "mg/dL"
    assert meal_ev_map["pre_meal_baseline_glucose_mg_dl"].current_value == 100.0
    assert meal_ev_map["postprandial_peak_excursion_mg_dl"].unit == "mg/dL"
    assert meal_ev_map["postprandial_peak_excursion_mg_dl"].baseline_value == 100.0
    assert meal_ev_map["postprandial_peak_excursion_mg_dl"].current_value == 160.0
    assert meal_ev_map["postprandial_peak_excursion_mg_dl"].delta == 60.0


# ---------------------------------------------------------------------------
# Group C — iAUC must match the approved spec (anchor gap chain & boundaries)
# ---------------------------------------------------------------------------
def test_group_c_iauc_anchor_gap_chain_and_boundary_cases():
    meal_ts = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)

    def _mk_pts(anchor_offset_min: float, post_offsets_min: list[float]) -> list[dict]:
        pts = [
            {
                "id": "anchor",
                "recorded_at": meal_ts + timedelta(minutes=anchor_offset_min),
                "glucose_mg_dl": 100.0,
                "reading_type": "cgm",
                "observation_provenance": "native",
                "source_dataset": "cgmacros",
            }
        ]
        for idx, off in enumerate(post_offsets_min):
            pts.append(
                {
                    "id": f"post-{idx}",
                    "recorded_at": meal_ts + timedelta(minutes=off),
                    "glucose_mg_dl": 140.0,
                    "reading_type": "cgm",
                    "observation_provenance": "native",
                    "source_dataset": "cgmacros",
                }
            )
        return pts

    # 1. Reproduced defect: anchor at -25 min, first post at +10 min (35 min gap from anchor > 30 min),
    #    7 post readings spanning 130 min -> MUST be rejected!
    reproduced_pts = _mk_pts(-25.0, [10.0, 30.0, 50.0, 70.0, 90.0, 110.0, 130.0])
    res_repro = evaluate_single_meal_response(
        meal_id="meal-c-repro",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Anchor -25m, first post +10m (35m gap)",
        carbs_g=60.0,
        meal_source_dataset="cgmacros",
        glucose_readings=reproduced_pts,
    )
    assert res_repro.iauc_valid is False
    assert res_repro.iauc_mg_dl_min is None
    assert "first_post_meal_reading_gt_30m_after_anchor" in res_repro.rejection_reasons
    assert "consecutive_sampling_gap_gt_30m" in res_repro.rejection_reasons
    assert res_repro.max_consecutive_gap_minutes == 35.0

    # 2. Anchor at -10 min, first post at +20 min (exact 30.0 min gap from anchor) -> ACCEPTED
    accepted_30m_pts = _mk_pts(-10.0, [20.0, 45.0, 70.0, 95.0, 120.0])
    res_30m = evaluate_single_meal_response(
        meal_id="meal-c-30m",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Anchor -10m, first post +20m (30.0m gap)",
        carbs_g=60.0,
        meal_source_dataset="cgmacros",
        glucose_readings=accepted_30m_pts,
    )
    assert res_30m.iauc_valid is True
    assert res_30m.max_consecutive_gap_minutes == 30.0
    assert res_30m.evidence is not None
    assert (
        res_30m.evidence.calculation_method
        == "timestamp_positive_trapezoidal_iauc_from_meal_t0_with_anchor_gap_chain"
    )
    # Hand-computed reference from t=0 (meal timestamp with zero excursion):
    # [0, 20]: 0.5*(0+40)*20 = 400
    # [20, 120]: 40 * 100 = 4000 -> total = 4400.0 mg/dL*min
    assert res_30m.iauc_mg_dl_min == 4400.0

    # 3. Boundary: 30.01 min gap from anchor (-10.0 min to +20.01 min) -> REJECTED
    rejected_3001_pts = _mk_pts(-10.0, [20.01, 45.0, 70.0, 95.0, 120.0])
    res_3001 = evaluate_single_meal_response(
        meal_id="meal-c-3001",
        logged_at=meal_ts,
        meal_type="lunch",
        description="30.01m gap",
        carbs_g=60.0,
        meal_source_dataset="cgmacros",
        glucose_readings=rejected_3001_pts,
    )
    assert res_3001.iauc_valid is False
    assert "first_post_meal_reading_gt_30m_after_anchor" in res_3001.rejection_reasons
    assert "consecutive_sampling_gap_gt_30m" in res_3001.rejection_reasons

    # 4. Boundary: 4 vs 5 post-meal readings, and duplicate timestamps do NOT count as distinct readings
    four_distinct_with_dup = _mk_pts(-5.0, [20.0, 50.0, 80.0, 120.0])
    four_distinct_with_dup.append(
        {
            "id": "post-dup-at-120",
            "recorded_at": meal_ts + timedelta(minutes=120.0),
            "glucose_mg_dl": 145.0,
            "reading_type": "cgm",
            "observation_provenance": "native",
            "source_dataset": "cgmacros",
        }
    )
    res_4dup = evaluate_single_meal_response(
        meal_id="meal-c-4dup",
        logged_at=meal_ts,
        meal_type="lunch",
        description="4 distinct + 1 duplicate",
        carbs_g=60.0,
        meal_source_dataset="cgmacros",
        glucose_readings=four_distinct_with_dup,
    )
    assert res_4dup.post_meal_reading_count == 4
    assert res_4dup.deduplicated_removed_count == 1
    assert res_4dup.iauc_valid is False
    assert "insufficient_post_meal_readings_lt_5" in res_4dup.rejection_reasons

    # 5. Boundary: span 119.0 min vs 120.0 min
    span_119_pts = _mk_pts(-5.0, [20.0, 45.0, 70.0, 95.0, 119.0])
    res_119 = evaluate_single_meal_response(
        meal_id="meal-c-119",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Span 119m",
        carbs_g=60.0,
        meal_source_dataset="cgmacros",
        glucose_readings=span_119_pts,
    )
    assert res_119.iauc_valid is False
    assert "insufficient_post_meal_window_span_lt_120m" in res_119.rejection_reasons


# ---------------------------------------------------------------------------
# Group D — Archive ingestion, no fabricated sheet/cell refs, multi-sheet,
#           zip-slip protection, and compute_sha256 nonexistent path check
# ---------------------------------------------------------------------------
def test_group_d_sha256_nonexistent_dict_null_refs_multisheet_and_zip_slip(tmp_path):
    from pathlib import Path
    import zipfile
    import pandas as pd
    from app.ingestion.common import compute_sha256
    from app.models import MedicationEvent

    # 1. compute_sha256(Path("nonexistent")) MUST raise ValueError (not hash the path string)
    with pytest.raises(ValueError, match="does not exist"):
        compute_sha256(Path(tmp_path / "nonexistent_file_xyz.csv"))

    # 2. Dict input without source_sheet / source_cell_ref stores None (never fabricated _Sheet1 or G2/H2),
    #    and adjacent identical medication rows are preserved (no synthetic is_fill_down heuristic)
    engine = get_engine()
    conn = engine.connect()
    outer_tx = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        rows_dict = [
            {
                "Date": "2023-06-01 08:00:00",
                "CGM (mg / dl)": 130.0,
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
            },
            {
                "Date": "2023-06-01 08:15:00",
                "CGM (mg / dl)": 135.0,
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
            },
        ]
        ingest_shanghai_t2dm(
            db,
            participant_sources={"9201": rows_dict},
        )
        p_dict = db.scalar(
            select(Patient).where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == "shanghai_t2dm",
                Patient.external_id == "9201",
            )
        )
        assert p_dict is not None
        med_events_dict = list(
            db.scalars(
                select(MedicationEvent)
                .where(MedicationEvent.patient_id == p_dict.id)
                .order_by(MedicationEvent.event_time.asc())
            ).all()
        )
        assert len(med_events_dict) == 2
        assert med_events_dict[0].source_sheet is None
        assert med_events_dict[0].source_cell_ref is None
        assert med_events_dict[1].source_sheet is None
        assert med_events_dict[1].source_cell_ref is None

        # 3. Multi-sheet Excel workbook ingests ALL sheets and records real sheet names
        #    and real 1-based Excel cell references (column C here, NOT hardcoded G!)
        wb_path = tmp_path / "9202_multisheet.xlsx"
        df_sheet_a = pd.DataFrame(
            [
                {
                    "Date": "2023-06-02 08:00:00",
                    "CGM (mg / dl)": 120.0,
                    "Non-insulin hypoglycemic agents": "Acarbose 50mg",
                }
            ]
        )
        df_sheet_b = pd.DataFrame(
            [
                {
                    "Date": "2023-06-03 09:00:00",
                    "CGM (mg / dl)": 142.0,
                    "Non-insulin hypoglycemic agents": "Acarbose 50mg",
                }
            ]
        )
        with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
            df_sheet_a.to_excel(writer, sheet_name="Admission_Part1", index=False)
            df_sheet_b.to_excel(writer, sheet_name="Admission_Part2", index=False)

        ingest_shanghai_t2dm(
            db,
            participant_sources={"9202": wb_path},
        )
        p_wb = db.scalar(
            select(Patient).where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == "shanghai_t2dm",
                Patient.external_id == "9202",
            )
        )
        assert p_wb is not None
        wb_readings = list(
            db.scalars(
                select(GlucoseReading)
                .where(GlucoseReading.patient_id == p_wb.id)
                .order_by(GlucoseReading.recorded_at.asc())
            ).all()
        )
        assert len(wb_readings) == 2
        wb_med_events = list(
            db.scalars(
                select(MedicationEvent)
                .where(MedicationEvent.patient_id == p_wb.id)
                .order_by(MedicationEvent.event_time.asc())
            ).all()
        )
        assert len(wb_med_events) == 2
        assert wb_med_events[0].source_sheet == "Admission_Part1"
        assert wb_med_events[0].source_cell_ref == "C2"
        assert wb_med_events[1].source_sheet == "Admission_Part2"
        assert wb_med_events[1].source_cell_ref == "C2"

        # 4. Zip-slip entry (../../evil.xlsx) is rejected before extraction
        from app.ingestion.common import extract_zip_safely

        evil_zip = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../evil.xlsx", b"malicious-bytes")

        extract_dest = tmp_path / "extracted"
        with pytest.raises(ValueError, match="zip_slip"):
            extract_zip_safely(evil_zip, extract_dest)
    finally:
        db.close()
        outer_tx.rollback()
        conn.close()



