from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import (
    compute_cgm_coverage,
    compute_glucose_drift,
    compute_glucose_summary,
    compute_medication_pattern_summary,
    evaluate_single_meal_response,
)
from app.core.database import get_engine
from app.core.rate_limit import reset_rate_limiter
from app.ingestion import (
    classify_cgmacros_glycemic_status,
    compute_sha256,
    ingest_cgmacros,
    ingest_shanghai_t2dm,
    normalize_glucose_reading,
    parse_utc_timestamp,
    query_cgmacros_t2d_cohort,
    seed_synthetic_demo_patient,
)
from app.main import app
from app.models import (
    DatasetImport,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
    User,
    WellbeingRecord,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


# ---------------------------------------------------------------------------
# 1. Manually Calculated Reference Values (Mean, SD, CV%, TIR/TBR/TAR)
# ---------------------------------------------------------------------------
def test_glucose_summary_matches_manual_reference_calculations():
    base_ts = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    # Reference values: [60, 100, 140, 200, 260] mg/dL (N = 5)
    # Mean = 760 / 5 = 152.0 mg/dL
    # Sample Variance = ((60-152)^2 + (100-152)^2 + (140-152)^2 + (200-152)^2 + (260-152)^2) / 4
    #                 = (8464 + 2704 + 144 + 2304 + 11664) / 4 = 25280 / 4 = 6320.0
    # Sample SD = sqrt(6320.0) = 79.4984... -> 79.50 mg/dL
    # CV% = (79.4984276 / 152.0) * 100 = 52.30159... -> 52.30%
    # TBR (<70): 1/5 = 20.0%, TBR Level 2 (<54): 0.0%
    # TIR (70-180): 2/5 = 40.0% (100, 140)
    # TAR (>180): 2/5 = 40.0% (200, 260), TAR Level 2 (>250): 1/5 = 20.0% (260)
    raw_values = [60.0, 100.0, 140.0, 200.0, 260.0]
    readings = [
        {
            "id": f"ref-{i}",
            "recorded_at": base_ts + timedelta(minutes=15 * i),
            "glucose_mg_dl": val,
            "source_dataset": "shanghai_t2dm",
            "sampling_interval_min": 15,
        }
        for i, val in enumerate(raw_values)
    ]

    summary = compute_glucose_summary(readings)
    assert summary.observation_count == 5
    assert summary.mean_glucose_mg_dl == 152.0
    assert summary.sd_glucose_mg_dl == 79.5
    assert summary.cv_pct == 52.3
    assert summary.min_glucose_mg_dl == 60.0
    assert summary.max_glucose_mg_dl == 260.0
    assert summary.median_glucose_mg_dl == 140.0
    assert summary.tbr_pct == 20.0
    assert summary.tbr_level2_pct == 0.0
    assert summary.tir_pct == 40.0
    assert summary.tar_pct == 40.0
    assert summary.tar_level2_pct == 20.0
    assert round(summary.tbr_pct + summary.tir_pct + summary.tar_pct, 2) == 100.0
    assert len(summary.evidence_items) == 3


# ---------------------------------------------------------------------------
# 2. Manually Calculated Meal-Response Trapezoidal iAUC & Strict Boundary Tests
# ---------------------------------------------------------------------------
def test_meal_response_iauc_manual_reference_and_boundary_rejections():
    meal_ts = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    # Pre-meal anchor at -10 min: G0 = 100.0 mg/dL (anchored at t = 0)
    # Post-meal vertices:
    # t=+30m: 140 (+40) -> area [0,30]   = 0.5 * (0 + 40) * 30  = 600.0
    # t=+60m: 160 (+60) -> area [30,60]  = 0.5 * (40 + 60) * 30 = 1500.0
    # t=+90m: 120 (+20) -> area [60,90]  = 0.5 * (60 + 20) * 30 = 1200.0
    # t=+120m: 90 (clipped to 0) -> [90,120] = 0.5 * (20 + 0) * 30 = 300.0
    # t=+150m: 110 (+10) -> [120,150] = 0.5 * (0 + 10) * 30 = 150.0
    # Total manual iAUC = 600 + 1500 + 1200 + 300 + 150 = 3750.0 mg/dL*min
    valid_readings = [
        {"id": "g-pre-early", "recorded_at": meal_ts - timedelta(minutes=25), "glucose_mg_dl": 108.0, "source_dataset": "cgmacros"},
        {"id": "g-anchor", "recorded_at": meal_ts - timedelta(minutes=10), "glucose_mg_dl": 100.0, "source_dataset": "cgmacros"},
        {"id": "g-1", "recorded_at": meal_ts + timedelta(minutes=30), "glucose_mg_dl": 140.0, "source_dataset": "cgmacros"},
        {"id": "g-2", "recorded_at": meal_ts + timedelta(minutes=60), "glucose_mg_dl": 160.0, "source_dataset": "cgmacros"},
        {"id": "g-3", "recorded_at": meal_ts + timedelta(minutes=90), "glucose_mg_dl": 120.0, "source_dataset": "cgmacros"},
        {"id": "g-4", "recorded_at": meal_ts + timedelta(minutes=120), "glucose_mg_dl": 90.0, "source_dataset": "cgmacros"},
        {"id": "g-5", "recorded_at": meal_ts + timedelta(minutes=150), "glucose_mg_dl": 110.0, "source_dataset": "cgmacros"},
    ]

    res = evaluate_single_meal_response(
        meal_id="meal-valid-1",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Test Reference Lunch",
        carbs_g=55.0,
        meal_source_dataset="cgmacros",
        glucose_readings=valid_readings,
    )
    assert res.iauc_valid is True
    assert res.pre_meal_glucose_mg_dl == 100.0
    assert res.peak_post_meal_glucose_mg_dl == 160.0
    assert res.excursion_delta_mg_dl == 60.0
    assert res.iauc_mg_dl_min == 3750.0
    assert res.evidence is not None
    assert res.evidence.current_value == 3750.0

    # Boundary Failure 1: Missing pre-meal anchor in [-30m, 0m] (only at -35m)
    no_anchor_readings = [
        {"id": "g-too-early", "recorded_at": meal_ts - timedelta(minutes=35), "glucose_mg_dl": 100.0, "source_dataset": "cgmacros"},
        *valid_readings[2:],
    ]
    res_no_anchor = evaluate_single_meal_response(
        meal_id="meal-no-anchor",
        logged_at=meal_ts,
        meal_type="lunch",
        description="No Anchor",
        carbs_g=50.0,
        meal_source_dataset="cgmacros",
        glucose_readings=no_anchor_readings,
    )
    assert res_no_anchor.iauc_valid is False
    assert res_no_anchor.iauc_mg_dl_min is None
    assert "missing_pre_meal_baseline_anchor_within_30m" in res_no_anchor.rejection_reasons

    # Boundary Failure 2: Fewer than 5 post-meal readings (only 4 readings)
    few_post_readings = [valid_readings[1], *valid_readings[2:6]]
    res_few = evaluate_single_meal_response(
        meal_id="meal-few",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Few Post Readings",
        carbs_g=50.0,
        meal_source_dataset="cgmacros",
        glucose_readings=few_post_readings,
    )
    assert res_few.iauc_valid is False
    assert res_few.iauc_mg_dl_min is None
    assert "insufficient_post_meal_readings_lt_5" in res_few.rejection_reasons

    # Boundary Failure 3: Post-meal window span < 120 min (5 readings at +15, +30, +45, +60, +90)
    short_span_readings = [
        valid_readings[1],
        *[
            {"id": f"s-{m}", "recorded_at": meal_ts + timedelta(minutes=m), "glucose_mg_dl": 135.0, "source_dataset": "cgmacros"}
            for m in (15, 30, 45, 60, 90)
        ],
    ]
    res_short = evaluate_single_meal_response(
        meal_id="meal-short-span",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Short Span",
        carbs_g=50.0,
        meal_source_dataset="cgmacros",
        glucose_readings=short_span_readings,
    )
    assert res_short.iauc_valid is False
    assert res_short.iauc_mg_dl_min is None
    assert "insufficient_post_meal_window_span_lt_120m" in res_short.rejection_reasons

    # Boundary Failure 4: Consecutive sampling gap > 30 min (first post-meal at +35m from t=0)
    gap_readings = [
        valid_readings[1],
        *[
            {"id": f"gap-{m}", "recorded_at": meal_ts + timedelta(minutes=m), "glucose_mg_dl": 140.0, "source_dataset": "cgmacros"}
            for m in (35, 60, 85, 110, 130)
        ],
    ]
    res_gap = evaluate_single_meal_response(
        meal_id="meal-gap",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Gap > 30m",
        carbs_g=50.0,
        meal_source_dataset="cgmacros",
        glucose_readings=gap_readings,
    )
    assert res_gap.iauc_valid is False
    assert res_gap.iauc_mg_dl_min is None
    assert "consecutive_sampling_gap_gt_30m" in res_gap.rejection_reasons


# ---------------------------------------------------------------------------
# 3. Missingness, Irregular Sampling, Duplicate & Out-of-Order Timestamps
# ---------------------------------------------------------------------------
def test_missingness_daily_vs_period_coverage_and_duplicate_out_of_order_handling():
    day1 = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)

    # Day 1: 80 readings at 15-min intervals -> 80/96 = 83.33% (>=70% full day)
    # Day 2: 48 readings at 15-min intervals with a 3-hour gap -> 48/96 = 50.0% (<70% partial_day)
    day1_ts = [day1 + timedelta(minutes=15 * i) for i in range(80)]
    day2_ts = [
        *(day2 + timedelta(minutes=15 * i) for i in range(24)),
        *(day2 + timedelta(minutes=15 * i) for i in range(36, 60)),
    ]

    # Shuffle order and inject duplicate timestamps to verify deduplication & sorting
    combined_readings = [
        {"id": f"d2-{i}", "recorded_at": ts, "glucose_mg_dl": 130.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15}
        for i, ts in enumerate(reversed(day2_ts))
    ] + [
        {"id": f"d1-{i}", "recorded_at": ts, "glucose_mg_dl": 110.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15}
        for i, ts in enumerate(day1_ts)
    ] + [
        # Duplicate of day1_ts[0] with a different value (must be ignored in favor of first-seen or deduplicated)
        {"id": "dup-0", "recorded_at": day1_ts[0], "glucose_mg_dl": 999.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15}
    ]

    summary = compute_glucose_summary(combined_readings)
    assert summary.observation_count == 128  # 80 + 48 unique timestamps
    cov = summary.coverage
    assert cov.native_sampling_interval_min == 15
    assert len(cov.daily_coverage) == 2
    assert cov.daily_coverage[0].observed_readings == 80
    assert cov.daily_coverage[0].coverage_pct == 83.33
    assert cov.daily_coverage[0].is_partial_day is False
    assert cov.daily_coverage[1].observed_readings == 48
    assert cov.daily_coverage[1].coverage_pct == 50.0
    assert cov.daily_coverage[1].is_partial_day is True
    assert cov.partial_days_count == 1
    assert cov.full_days_count == 1
    assert cov.large_gaps_count >= 1
    assert cov.meets_14d_clinical_guidance is False


# ---------------------------------------------------------------------------
# 4. Unit Conversion, Checksum & Timestamp Validation Tests
# ---------------------------------------------------------------------------
def test_unit_conversion_invalid_units_and_sha256_checksum():
    # 5.5 mmol/L * 18.0182 = 99.10 mg/dL
    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(5.5, "mmol/L")
    assert g_mg_dl == 99.1
    assert g_raw == 5.5
    assert g_unit == "mmol/L"

    g2_mg_dl, g2_raw, g2_unit = normalize_glucose_reading("126", "mg/dl")
    assert g2_mg_dl == 126.0
    assert g2_raw == 126.0
    assert g2_unit == "mg/dL"

    with pytest.raises(ValueError, match="invalid_unit"):
        normalize_glucose_reading(100.0, "g/dL")

    with pytest.raises(ValueError, match="out_of_physiological_range"):
        normalize_glucose_reading(5.0, "mg/dL")

    with pytest.raises(ValueError, match="out_of_physiological_range"):
        normalize_glucose_reading(1800.0, "mg/dL")

    with pytest.raises(ValueError, match="missing_glucose_value"):
        normalize_glucose_reading("data not available", "mg/dL")

    # SHA-256 deterministic file checksum
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(b"Date,CGM (mg / dl)\n2023-01-01 08:00:00,120\n")
        tmp_path = Path(tmp.name)
    try:
        c1 = compute_sha256(tmp_path)
        c2 = compute_sha256(b"Date,CGM (mg / dl)\n2023-01-01 08:00:00,120\n")
        assert len(c1) == 64
        assert c1 == c2
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5. ShanghaiT2DM & CGMacros Ingestion, Provenance, T2D Separation & Native Cadence
# ---------------------------------------------------------------------------
def test_shanghai_t2dm_and_cgmacros_ingestion_provenance_and_cohort_separation():
    engine = get_engine()
    conn = engine.connect()
    outer_tx = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        # A. ShanghaiT2DM Ingestion:
        # Includes out-of-order rows, duplicate timestamp, invalid glucose, mmol/L row,
        # and clinical medication note (must be stored as status='unknown', never 'taken')
        shanghai_summary = [
            {
                "Patient Number": "9001_0_20230101",
                "Gender": "Female",
                "Age (years)": 61,
                "Height (m)": 1.60,
                "Weight (kg)": 66.0,
                "HbA1c (%)": 7.8,
                "BMI (kg/m2)": 25.8,
                "Fasting Plasma Glucose (mg/dl)": 138.0,
            },
            {
                # Accidental T1D row must be rejected to prevent T1D/T2D mixing
                "Patient Number": "9002_0_20230101",
                "diabetes_type": "T1D",
            },
        ]
        shanghai_rows_9001 = [
            # Out-of-order second reading first
            {
                "Date": "2023-01-01 08:15:00",
                "CGM (mg / dl)": 142.0,
                "Dietary intake": "Steamed bun and soy milk",
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
            },
            {
                "Date": "2023-01-01 08:00:00",
                "CGM (mg / dl)": 118.0,
                "CBG (mg / dl)": 120.0,
                "Dietary intake": "data not available",
            },
            # Duplicate timestamp at 08:00:00 -> must be rejected, original 118.0 preserved
            {
                "Date": "2023-01-01 08:00:00",
                "CGM (mg / dl)": 250.0,
            },
            # Invalid physiological value -> must be rejected
            {
                "Date": "2023-01-01 08:30:00",
                "CGM (mg / dl)": -15.0,
            },
            # Unparseable timestamp -> must be rejected
            {
                "Date": "not-a-timestamp",
                "CGM (mg / dl)": 130.0,
            },
        ]

        st_report = ingest_shanghai_t2dm(
            db,
            participant_sources={
                "9001_0_20230101": shanghai_rows_9001,
                "9002_0_20230101": [{"Date": "2023-01-01 08:00:00", "CGM (mg / dl)": 120.0}],
            },
            summary_source=shanghai_summary,
            source_checksum_target=b"shanghai-test-fixture-v1",
        )

        assert st_report.participants_ingested == 1
        assert st_report.rejection_reasons.get("t1d_cohort_mixing_forbidden") == 1
        assert st_report.rejection_reasons.get("duplicate_timestamp") == 1
        assert st_report.rejection_reasons.get("out_of_physiological_range") == 1
        assert st_report.rejection_reasons.get("invalid_timestamp") == 1

        st_patient = db.scalar(
            select(Patient).where(
                Patient.source_dataset == "shanghai_t2dm",
                Patient.external_id == "9001",
            )
        )
        assert st_patient is not None
        assert st_patient.cohort_type == "research_participant"
        assert st_patient.diabetes_type == "T2D"
        assert st_patient.height_cm == 160.0

        # Verify duplicate did not overwrite 118.0 and native 15-min sampling is preserved
        st_cgm = list(
            db.scalars(
                select(GlucoseReading)
                .where(
                    GlucoseReading.patient_id == st_patient.id,
                    GlucoseReading.reading_type == "cgm",
                )
                .order_by(GlucoseReading.recorded_at.asc())
            ).all()
        )
        assert len(st_cgm) == 2
        assert st_cgm[0].glucose_mg_dl == 118.0
        assert st_cgm[0].device_id == "FreeStyle_Libre_H"
        assert st_cgm[0].sampling_interval_min == 15

        # Verify medication event is stored as status='unknown', never fabricated as 'taken'
        st_meds = list(db.scalars(select(Medication).where(Medication.patient_id == st_patient.id)).all())
        st_med_events = list(
            db.scalars(select(MedicationEvent).where(MedicationEvent.patient_id == st_patient.id)).all()
        )
        assert len(st_meds) == 1
        assert len(st_med_events) == 1
        assert st_med_events[0].status == "unknown"
        assert st_med_events[0].event_source == "clinical_record"
        med_pattern = compute_medication_pattern_summary(st_meds, st_med_events)
        assert med_pattern.adherence_computable is False
        assert med_pattern.observed_taken_pct is None

        # Verify no wellbeing records were fabricated
        st_wellbeing = list(
            db.scalars(select(WellbeingRecord).where(WellbeingRecord.patient_id == st_patient.id)).all()
        )
        assert len(st_wellbeing) == 0

        # B. CGMacros Ingestion:
        # Verify strict T2D separation (HbA1c > 6.4% included; prediabetes 6.0% and healthy 5.3% excluded)
        # and native cadence down-sampling from 1-min interpolated rows (Libre=15m, Dexcom=5m)
        cg_bio = [
            {"subject": 1, "Age": 58, "Gender": "M", "A1c PDL (Lab)": 7.2, "BMI": 29.1, "Fasting GLU - PDL (Lab)": 145.0},
            {"subject": 2, "Age": 45, "Gender": "F", "A1c PDL (Lab)": 6.0, "BMI": 26.0},  # prediabetes
            {"subject": 3, "Age": 31, "Gender": "F", "A1c PDL (Lab)": 5.3, "BMI": 22.4},  # healthy
        ]
        base_cg_ts = datetime(2023, 5, 10, 12, 0, tzinfo=timezone.utc)
        # 16 consecutive 1-minute rows (minutes 0..15):
        # Native Libre (15m) should keep only t=0m and t=15m (2 readings)
        # Native Dexcom (5m) should keep only t=0m, 5m, 10m, 15m (4 readings)
        cg_rows_sub1 = [
            {
                "Timestamp": (base_cg_ts + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S"),
                "Libre GL": 130.0 + m,
                "Dexcom GL": 128.0 + m,
                "Meal Type": "Lunch" if m == 0 else None,
                "Calories": 520.0 if m == 0 else None,
                "Carbs": 62.0 if m == 0 else None,
                "Protein": 24.0 if m == 0 else None,
                "Fat": 18.0 if m == 0 else None,
                "Fiber": 7.0 if m == 0 else None,
            }
            for m in range(16)
        ]

        cg_report = ingest_cgmacros(
            db,
            bio_source=cg_bio,
            participant_sources={
                "1": cg_rows_sub1,
                "2": cg_rows_sub1,
                "3": cg_rows_sub1,
            },
            t2d_only=True,
            preserve_native_cadence=True,
            source_checksum_target=b"cgmacros-test-fixture-v1",
        )

        assert cg_report.participants_ingested == 1
        assert set(cg_report.excluded_non_t2d_participants) == {"CGMacros-002", "CGMacros-003"}

        t2d_patients = query_cgmacros_t2d_cohort(db)
        t2d_ext_ids = {p.external_id for p in t2d_patients}
        assert "CGMacros-001" in t2d_ext_ids
        assert "CGMacros-002" not in t2d_ext_ids
        assert "CGMacros-003" not in t2d_ext_ids

        cg_p1 = next(p for p in t2d_patients if p.external_id == "CGMacros-001")
        libre_readings = list(
            db.scalars(
                select(GlucoseReading).where(
                    GlucoseReading.patient_id == cg_p1.id,
                    GlucoseReading.device_id == "FreeStyle_Libre_Pro",
                )
            ).all()
        )
        dexcom_readings = list(
            db.scalars(
                select(GlucoseReading).where(
                    GlucoseReading.patient_id == cg_p1.id,
                    GlucoseReading.device_id == "Dexcom_G6_Pro",
                )
            ).all()
        )
        assert len(libre_readings) == 2
        assert all(r.sampling_interval_min == 15 for r in libre_readings)
        assert len(dexcom_readings) == 4
        assert all(r.sampling_interval_min == 5 for r in dexcom_readings)
    finally:
        db.close()
        outer_tx.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# 6. Synthetic Demo Seeding, Analytics API Endpoints & Cohort Isolation
# ---------------------------------------------------------------------------
def test_synthetic_demo_analytics_endpoints_and_cohort_isolation():
    email = f"day3-api-{uuid.uuid4().hex[:8]}@example.com"
    engine = get_engine()
    try:
        with Session(engine) as db:
            demo_summary = seed_synthetic_demo_patient(db, days=6, seed=42)
            assert demo_summary.records_accepted > 500
            demo_patient = db.scalar(
                select(Patient).where(
                    Patient.cohort_type == "synthetic_demo",
                    Patient.external_id == "SYNTH-DEMO-001",
                )
            )
            assert demo_patient is not None
            demo_id = demo_patient.id

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
                    source_dataset="shanghai_t2dm",
                )
                db.add(research_patient)
                db.commit()
            research_id = research_patient.id

        # Register & login as ordinary app_user
        client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
        login = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # 1. Ordinary app_user can read analytics on synthetic_demo
        sum_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/summary", headers=headers)
        assert sum_resp.status_code == 200, sum_resp.text
        sum_data = sum_resp.json()
        assert sum_data["observation_count"] == 6 * 96
        assert sum_data["coverage"]["period_coverage_pct"] == 100.0

        drift_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/drift", headers=headers)
        assert drift_resp.status_code == 200
        assert drift_resp.json()["status"] == "upward_drift"

        meals_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/meal-responses", headers=headers)
        assert meals_resp.status_code == 200
        meal_items = meals_resp.json()
        assert len(meal_items) == 6 * 3
        assert any(m["iauc_valid"] is True and m["iauc_mg_dl_min"] > 0 for m in meal_items)

        meds_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/medication-patterns", headers=headers)
        assert meds_resp.status_code == 200
        assert meds_resp.json()["adherence_computable"] is True

        # 2. Ordinary app_user is strictly blocked (403) from research_participant analytics
        for sub_route in ("summary", "drift", "meal-responses", "medication-patterns"):
            resp = client.get(f"/api/v1/patients/{research_id}/analytics/{sub_route}", headers=headers)
            assert resp.status_code == 403
    finally:
        with Session(engine) as db:
            u = db.scalar(select(User).where(User.email == email))
            if u is not None:
                db.delete(u)
                db.commit()
