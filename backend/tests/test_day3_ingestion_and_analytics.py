from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import tempfile
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
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
    compute_directory_manifest_checksum,
    compute_input_payload_checksum,
    compute_sha256,
    compute_source_file_checksum,
    ingest_cgmacros,
    ingest_shanghai_t2dm,
    normalize_glucose_reading,
    parse_timestamp_with_semantics,
    query_cgmacros_t2d_cohort,
    seed_synthetic_demo_patient,
    validate_calendar_date_comparability,
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
    raw_values = [60.0, 100.0, 140.0, 200.0, 260.0]
    readings = [
        {
            "id": f"ref-{i}",
            "recorded_at": base_ts + timedelta(minutes=15 * i),
            "glucose_mg_dl": val,
            "source_dataset": "shanghai_t2dm",
            "sampling_interval_min": 15,
            "observation_provenance": "native",
            "timestamp_semantics": "real_world_local",
            "timezone_basis": "assumed_study_location",
        }
        for i, val in enumerate(raw_values)
    ]

    summary = compute_glucose_summary(readings)
    assert summary.observation_count == 5
    assert summary.native_observation_count == 5
    assert summary.excluded_non_native_count == 0
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
    assert summary.timezone_basis == ["assumed_study_location"]
    assert any("assumed_study_location" in n for n in summary.coverage.uncertainty_notes)
    assert len(summary.evidence_items) == 7
    assert any("assumed_study_location" in n for n in summary.evidence_items[0].uncertainty_notes)


# ---------------------------------------------------------------------------
# 2. Manually Calculated Meal-Response Trapezoidal iAUC & Strict Boundary Tests
# ---------------------------------------------------------------------------
def test_meal_response_iauc_manual_reference_and_boundary_rejections():
    meal_ts = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    valid_readings = [
        {"id": "g-pre-early", "recorded_at": meal_ts - timedelta(minutes=25), "glucose_mg_dl": 108.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-anchor", "recorded_at": meal_ts - timedelta(minutes=10), "glucose_mg_dl": 100.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-0", "recorded_at": meal_ts + timedelta(minutes=15), "glucose_mg_dl": 120.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-1", "recorded_at": meal_ts + timedelta(minutes=30), "glucose_mg_dl": 140.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-2", "recorded_at": meal_ts + timedelta(minutes=60), "glucose_mg_dl": 160.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-3", "recorded_at": meal_ts + timedelta(minutes=90), "glucose_mg_dl": 120.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-4", "recorded_at": meal_ts + timedelta(minutes=120), "glucose_mg_dl": 90.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "g-5", "recorded_at": meal_ts + timedelta(minutes=150), "glucose_mg_dl": 110.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
    ]

    res = evaluate_single_meal_response(
        meal_id="meal-valid-1",
        logged_at=meal_ts,
        meal_type="lunch",
        description="Test Reference Lunch",
        carbs_g=55.0,
        meal_source_dataset="cgmacros",
        meal_timestamp_semantics="date_shifted_relative",
        glucose_readings=valid_readings,
    )
    assert res.iauc_valid is True
    assert res.pre_meal_glucose_mg_dl == 100.0
    assert res.peak_post_meal_glucose_mg_dl == 160.0
    assert res.excursion_delta_mg_dl == 60.0
    assert res.iauc_mg_dl_min == 3750.0
    assert res.timestamp_semantics == "date_shifted_relative"
    assert res.calendar_date_comparable is False
    assert any("date_shifted_relative" in note for note in res.uncertainty_notes)
    assert res.evidence is not None
    assert res.evidence.current_value == 3750.0
    assert any("date_shifted_relative" in note for note in res.evidence.uncertainty_notes)

    # Boundary Failure 1: Missing pre-meal anchor in [-30m, 0m]
    no_anchor_readings = [
        {"id": "g-too-early", "recorded_at": meal_ts - timedelta(minutes=35), "glucose_mg_dl": 100.0, "source_dataset": "cgmacros", "observation_provenance": "native"},
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

    # Boundary Failure 2: Fewer than 5 post-meal readings
    few_post_readings = [valid_readings[1], *valid_readings[3:7]]
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
    assert "insufficient_post_meal_readings_lt_5" in res_few.rejection_reasons

    # Boundary Failure 3: Post-meal window span < 120 min
    short_span_readings = [
        valid_readings[1],
        *[
            {"id": f"s-{m}", "recorded_at": meal_ts + timedelta(minutes=m), "glucose_mg_dl": 135.0, "source_dataset": "cgmacros", "observation_provenance": "native"}
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
    assert "insufficient_post_meal_window_span_lt_120m" in res_short.rejection_reasons

    # Boundary Failure 4: Consecutive sampling gap > 30 min
    gap_readings = [
        valid_readings[1],
        *[
            {"id": f"gap-{m}", "recorded_at": meal_ts + timedelta(minutes=m), "glucose_mg_dl": 140.0, "source_dataset": "cgmacros", "observation_provenance": "native"}
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
    assert "consecutive_sampling_gap_gt_30m" in res_gap.rejection_reasons


# ---------------------------------------------------------------------------
# 3. Observation Provenance (native / interpolated / derived / unknown) & Filtering
# ---------------------------------------------------------------------------
def test_native_vs_interpolated_derived_unknown_provenance_filtering():
    base_ts = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    mixed_readings = [
        {"id": "n-1", "recorded_at": base_ts, "glucose_mg_dl": 100.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "n-2", "recorded_at": base_ts + timedelta(minutes=15), "glucose_mg_dl": 120.0, "source_dataset": "cgmacros", "observation_provenance": "native", "timestamp_semantics": "date_shifted_relative"},
        {"id": "i-1", "recorded_at": base_ts + timedelta(minutes=5), "glucose_mg_dl": 999.0, "source_dataset": "cgmacros", "observation_provenance": "interpolated", "timestamp_semantics": "date_shifted_relative"},
        {"id": "d-1", "recorded_at": base_ts + timedelta(minutes=10), "glucose_mg_dl": 888.0, "source_dataset": "cgmacros", "observation_provenance": "derived", "timestamp_semantics": "date_shifted_relative"},
        {"id": "u-1", "recorded_at": base_ts + timedelta(minutes=20), "glucose_mg_dl": 777.0, "source_dataset": "cgmacros", "observation_provenance": "unknown", "timestamp_semantics": "date_shifted_relative"},
    ]

    summary = compute_glucose_summary(mixed_readings, native_only=True)
    assert summary.observation_count == 2
    assert summary.mean_glucose_mg_dl == 110.0
    assert summary.native_observation_count == 2
    assert summary.interpolated_observation_count == 1
    assert summary.derived_observation_count == 1
    assert summary.unknown_observation_count == 1
    assert summary.excluded_non_native_count == 3
    assert summary.calendar_date_comparable is False
    assert any("Excluded 3 reading(s) with non-native provenance" in n for n in summary.coverage.uncertainty_notes)
    assert any("date_shifted_relative" in n for n in summary.coverage.uncertainty_notes)

    with pytest.raises(ValueError, match="calendar_date_comparison_forbidden_for_date_shifted_relative"):
        validate_calendar_date_comparability(["date_shifted_relative", "real_world_local"], dataset_names=["cgmacros", "shanghai_t2dm"])


# ---------------------------------------------------------------------------
# 4. Missingness, Irregular Sampling, Duplicate & Out-of-Order Timestamps
# ---------------------------------------------------------------------------
def test_missingness_daily_vs_period_coverage_and_duplicate_out_of_order_handling():
    day1 = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)

    day1_ts = [day1 + timedelta(minutes=15 * i) for i in range(80)]
    day2_ts = [
        *(day2 + timedelta(minutes=15 * i) for i in range(24)),
        *(day2 + timedelta(minutes=15 * i) for i in range(36, 60)),
    ]

    combined_readings = [
        {"id": f"d2-{i}", "recorded_at": ts, "glucose_mg_dl": 130.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15, "observation_provenance": "native"}
        for i, ts in enumerate(reversed(day2_ts))
    ] + [
        {"id": f"d1-{i}", "recorded_at": ts, "glucose_mg_dl": 110.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15, "observation_provenance": "native"}
        for i, ts in enumerate(day1_ts)
    ] + [
        {"id": "dup-0", "recorded_at": day1_ts[0], "glucose_mg_dl": 999.0, "source_dataset": "shanghai_t2dm", "sampling_interval_min": 15, "observation_provenance": "native"}
    ]

    summary = compute_glucose_summary(combined_readings)
    assert summary.observation_count == 128
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
# 5. Checksum Semantics (Regular File vs. Directory Manifest vs. Canonical Payload)
# ---------------------------------------------------------------------------
def test_unit_conversion_and_strict_checksum_semantics():
    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(5.5, "mmol/L")
    assert g_mg_dl == 99.1
    assert g_raw == 5.5
    assert g_unit == "mmol/L"

    # A. Regular-file-only enforcement for compute_source_file_checksum
    assert compute_source_file_checksum(None) is None
    assert compute_directory_manifest_checksum(None) is None
    with pytest.raises(ValueError, match="source_file_checksum requires an existing regular file"):
        compute_source_file_checksum(b"raw-bytes-not-a-file")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not exist on disk"):
        compute_source_file_checksum("non_existent_dataset_file.csv")

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        file_a = tmp_dir / "part_a.csv"
        file_b = tmp_dir / "part_b.csv"
        file_a.write_bytes(b"Date,CGM (mg / dl)\n2023-01-01 08:00:00,120\n")
        file_b.write_bytes(b"Date,CGM (mg / dl)\n2023-01-01 08:15:00,125\n")

        # Passing a directory to compute_source_file_checksum MUST raise ValueError
        with pytest.raises(ValueError, match="requires a regular file, not a directory"):
            compute_source_file_checksum(tmp_dir)

        # Passing a regular file to compute_directory_manifest_checksum MUST raise ValueError
        with pytest.raises(ValueError, match="requires a directory path, not a regular file"):
            compute_directory_manifest_checksum(file_a)

        file_hash = compute_source_file_checksum(file_a)
        assert file_hash == compute_sha256(b"Date,CGM (mg / dl)\n2023-01-01 08:00:00,120\n")

        dir_hash_1 = compute_directory_manifest_checksum(tmp_dir)
        dir_hash_2 = compute_directory_manifest_checksum(tmp_dir)
        assert dir_hash_1 is not None
        assert len(dir_hash_1) == 64
        assert dir_hash_1 == dir_hash_2
        assert dir_hash_1 != file_hash

    # B. Canonical input_payload_checksum: timestamps, nulls/NaN, floats, Unicode, nested dicts, and row-order sensitivity
    ts_val = datetime(2026, 5, 1, 8, 30, tzinfo=timezone.utc)
    d_val = date(2026, 5, 1)
    payload_1 = {
        "meta": {"z_key": "餐后血糖 / روٹی", "a_key": None, "nan_val": float("nan"), "neg_zero": -0.0},
        "rows": [
            {"ts": ts_val, "day": d_val, "glucose": 124.5, "note": "first"},
            {"ts": ts_val + timedelta(minutes=15), "day": d_val, "glucose": 130.25, "note": "second"},
        ],
    }
    payload_2_reordered_keys = {
        "rows": [
            {"note": "first", "glucose": 124.5, "day": d_val, "ts": ts_val},
            {"glucose": 130.25, "ts": ts_val + timedelta(minutes=15), "note": "second", "day": d_val},
        ],
        "meta": {"a_key": None, "neg_zero": 0.0, "nan_val": None, "z_key": "餐后血糖 / روٹی"},
    }
    payload_3_reordered_rows = {
        "meta": {"z_key": "餐后血糖 / روٹی", "a_key": None, "nan_val": None, "neg_zero": 0.0},
        "rows": [
            {"ts": ts_val + timedelta(minutes=15), "day": d_val, "glucose": 130.25, "note": "second"},
            {"ts": ts_val, "day": d_val, "glucose": 124.5, "note": "first"},
        ],
    }
    h1 = compute_input_payload_checksum(payload_1)
    h2 = compute_input_payload_checksum(payload_2_reordered_keys)
    h3 = compute_input_payload_checksum(payload_3_reordered_rows)
    assert len(h1) == 64
    assert h1 == h2  # Dict key ordering, -0.0 vs 0.0, and NaN->None produce identical canonical hash
    assert h1 != h3  # List / row ordering is semantically significant and changes the checksum


# ---------------------------------------------------------------------------
# 6. Dual-CGM Database Integrity, DOI, Consent Separation, Provenance & Immutability
# ---------------------------------------------------------------------------
def test_shanghai_t2dm_cgmacros_provenance_consent_immutability_and_medication_dedup():
    # Verify timezone basis helper for Shanghai naive vs offset-confirmed timestamps
    ts_naive, raw_naive, sem_naive, basis_naive = parse_timestamp_with_semantics(
        "2023-01-01 08:00:00",
        semantics="real_world_local",
        assumed_iana_tz="Asia/Shanghai",
    )
    assert ts_naive == datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert raw_naive == "2023-01-01 08:00:00"
    assert sem_naive == "real_world_local"
    assert basis_naive == "assumed_study_location"

    ts_confirmed, _, _, basis_confirmed = parse_timestamp_with_semantics(
        "2023-01-01 08:00:00+08:00",
        semantics="real_world_local",
        assumed_iana_tz="Asia/Shanghai",
    )
    assert ts_confirmed == datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert basis_confirmed == "source_confirmed"

    engine = get_engine()
    conn = engine.connect()
    outer_tx = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        # A. ShanghaiT2DM Ingestion:
        # 1. Verify dataset license ('CC BY 4.0', DOI '10.6084/m9.figshare.20444397.v1') is stored on
        #    DatasetImport while Patient.consent_version is None and Patient.consent_granted is False.
        # 2. Verify naive Shanghai timestamps get timezone_basis == 'assumed_study_location'.
        # 3. Verify medication deduplication:
        #    - Static summary medication creates a Medication regimen only (0 MedicationEvents).
        #    - Contiguous 15-min fill-down rows (08:15 and 08:30 'Metformin 0.5g') emit ONLY 1 event (at 08:15).
        #    - A genuine separate timestamped administration later that day (20:00 'Metformin 0.5g')
        #      is NOT suppressed and emits a 2nd MedicationEvent, preserving source_sheet & source_cell_ref.
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
                "Hypoglycemic Agents": "Acarbose 50mg TID (summary static regimen)",
            },
            {
                "Patient Number": "9002_0_20230101",
                "diabetes_type": "T1D",
            },
        ]
        shanghai_rows_9001 = [
            {
                "Date": "2023-01-01 08:15:00",
                "CGM (mg / dl)": 142.0,
                "Dietary intake": "Steamed bun and soy milk",
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
                "source_sheet": "9001_0_20230101",
                "source_cell_ref": "G3",
            },
            # Contiguous 15-min fill-down cell (08:30 is 15 min after 08:15 on same sheet) -> suppressed
            {
                "Date": "2023-01-01 08:30:00",
                "CGM (mg / dl)": 148.0,
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
                "source_sheet": "9001_0_20230101",
                "source_cell_ref": "G4",
            },
            # Genuine separate evening administration of the same dose at 20:00 -> MUST be preserved!
            {
                "Date": "2023-01-01 20:00:00",
                "CGM (mg / dl)": 156.0,
                "Non-insulin hypoglycemic agents": "Metformin 0.5g",
                "source_sheet": "9001_0_20230101",
                "source_cell_ref": "G50",
            },
            {
                "Date": "2023-01-01 08:00:00",
                "CGM (mg / dl)": 118.0,
                "CBG (mg / dl)": 120.0,
                "Dietary intake": "data not available",
            },
            # Duplicate timestamp on same device -> rejected
            {
                "Date": "2023-01-01 08:00:00",
                "CGM (mg / dl)": 250.0,
            },
            {
                "Date": "2023-01-01 08:45:00",
                "CGM (mg / dl)": -15.0,
            },
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
        )

        assert st_report.license_identifier == "CC BY 4.0"
        assert st_report.dataset_doi == "10.6084/m9.figshare.20444397.v1"
        assert st_report.source_url == "https://ndownloader.figshare.com/files/36582306"
        assert st_report.license_url == "https://creativecommons.org/licenses/by/4.0/"
        assert st_report.timezone_basis == "assumed_study_location"
        assert st_report.source_file_checksum is None
        assert st_report.directory_manifest_checksum is None
        assert st_report.input_payload_checksum is not None
        assert len(st_report.input_payload_checksum) == 64
        assert st_report.participants_ingested == 1
        assert st_report.observation_provenance_counts["native"] == 0
        assert st_report.observation_provenance_counts["unknown"] == 5  # 4 CGM + 1 CBG default to unknown without evidence ref
        assert st_report.rejection_reasons.get("t1d_cohort_mixing_forbidden") == 1
        assert st_report.rejection_reasons.get("duplicate_timestamp") == 1

        st_patient = db.scalar(
            select(Patient).where(
                Patient.source_dataset == "shanghai_t2dm",
                Patient.external_id == "9001",
            )
        )
        assert st_patient is not None
        # Dataset license must NOT populate patient consent fields
        assert st_patient.consent_granted is False
        assert st_patient.consent_version is None

        # Verify timezone_basis on stored ShanghaiT2DM GlucoseReadings
        st_readings = list(
            db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == st_patient.id)).all()
        )
        assert all(r.timezone_basis == "assumed_study_location" for r in st_readings)
        st_summary_native = compute_glucose_summary(st_readings, native_only=True)
        assert st_summary_native.observation_count == 0
        assert st_summary_native.excluded_non_cgm_count == 1
        assert st_summary_native.excluded_non_native_count == 4
        assert any("unverified/unknown" in n for n in st_summary_native.coverage.uncertainty_notes)

        st_summary_all = compute_glucose_summary(st_readings, native_only=False)
        assert st_summary_all.observation_count == 4
        assert st_summary_all.excluded_non_cgm_count == 1
        assert st_summary_all.timezone_basis == ["assumed_study_location"]
        assert any("assumed_study_location" in n for n in st_summary_all.coverage.uncertainty_notes)

        # Verify medication regimens and deduplicated vs genuine separate timestamped MedicationEvents
        st_meds = list(db.scalars(select(Medication).where(Medication.patient_id == st_patient.id)).all())
        st_med_events = list(
            db.scalars(
                select(MedicationEvent)
                .where(MedicationEvent.patient_id == st_patient.id)
                .order_by(MedicationEvent.event_time.asc())
            ).all()
        )
        assert len(st_meds) == 2  # 1 summary Acarbose + 1 time-series Metformin
        assert len(st_med_events) == 3  # All 3 non-empty medication rows preserved with status='unknown'
        assert st_med_events[0].status == "unknown"
        assert st_med_events[0].notes == "Metformin 0.5g"
        assert st_med_events[0].source_sheet == "9001_0_20230101"
        assert st_med_events[0].source_cell_ref == "G3"
        assert st_med_events[0].event_time == datetime(2023, 1, 1, 0, 15, tzinfo=timezone.utc)
        assert st_med_events[1].status == "unknown"
        assert st_med_events[1].notes == "Metformin 0.5g"
        assert st_med_events[1].source_sheet == "9001_0_20230101"
        assert st_med_events[1].source_cell_ref == "G4"
        assert st_med_events[1].event_time == datetime(2023, 1, 1, 0, 30, tzinfo=timezone.utc)
        assert st_med_events[2].status == "unknown"
        assert st_med_events[2].notes == "Metformin 0.5g"
        assert st_med_events[2].source_sheet == "9001_0_20230101"
        assert st_med_events[2].source_cell_ref == "G50"
        assert st_med_events[2].event_time == datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc)

        # B. CGMacros Ingestion:
        # 1. Verify official PhysioNet v1.0.0 DOI '10.13026/3z8q-x658' and license 'CC BY-NC-SA 4.0'.
        # 2. Verify Patient.consent_version is None and Patient.consent_granted is False.
        # 3. Verify that EVEN WHEN rows are spaced at exact 15-minute intervals (nominal Libre cadence),
        #    unverified CGMacros rows remain observation_provenance == 'unknown' and are excluded when native_only=True.
        cg_bio = [
            {"subject": 1, "Age": 58, "Gender": "M", "A1c PDL (Lab)": 7.2, "BMI": 29.1, "Fasting GLU - PDL (Lab)": 145.0},
            {"subject": 2, "Age": 45, "Gender": "F", "A1c PDL (Lab)": 6.0, "BMI": 26.0},
            {"subject": 3, "Age": 31, "Gender": "F", "A1c PDL (Lab)": 5.3, "BMI": 22.4},
        ]
        base_cg_ts = datetime(2023, 5, 10, 12, 0, tzinfo=timezone.utc)
        # Rows spaced at exact 15-minute intervals (0, 15, 30, 45 min) WITHOUT explicit provenance metadata:
        # Must still be classified as 'unknown' (interval spacing alone never establishes native provenance!).
        cg_rows_sub1 = [
            {
                "Timestamp": (base_cg_ts + timedelta(minutes=15 * step)).strftime("%Y-%m-%d %H:%M:%S"),
                "Libre GL": 130.0 + step,
                "Dexcom GL": 128.0 + step,
                "Meal Type": "Lunch" if step == 0 else None,
                "Calories": 520.0 if step == 0 else None,
                "Carbs": 62.0 if step == 0 else None,
            }
            for step in range(4)
        ]

        cg_report = ingest_cgmacros(
            db,
            bio_source=cg_bio,
            participant_sources={"1": cg_rows_sub1, "2": cg_rows_sub1, "3": cg_rows_sub1},
            t2d_only=True,
        )

        assert cg_report.dataset_doi == "10.13026/3z8q-x658"
        assert cg_report.source_url == "https://physionet.org/content/cgmacros/1.0.0/"
        assert cg_report.license_identifier == "CC BY-NC-SA 4.0"
        assert cg_report.license_url == "https://creativecommons.org/licenses/by-nc-sa/4.0/"
        assert cg_report.timestamp_semantics == "date_shifted_relative"
        assert cg_report.timezone_basis == "not_applicable_relative"
        assert cg_report.source_file_checksum is None
        assert cg_report.input_payload_checksum is not None
        assert cg_report.participants_ingested == 1
        assert set(cg_report.excluded_non_t2d_participants) == {"CGMacros-002", "CGMacros-003"}
        # All 4 Libre + 4 Dexcom 15-min spaced rows without provenance verification must remain 'unknown'
        assert cg_report.observation_provenance_counts["unknown"] == 8
        assert cg_report.observation_provenance_counts["native"] == 0

        cg_p1 = query_cgmacros_t2d_cohort(db)[0]
        assert cg_p1.consent_granted is False
        assert cg_p1.consent_version is None

        # Verify simultaneous Libre Pro & Dexcom G6 Pro readings exist at the exact same timestamp t=0
        same_ts_readings = list(
            db.scalars(
                select(GlucoseReading).where(
                    GlucoseReading.patient_id == cg_p1.id,
                    GlucoseReading.recorded_at == base_cg_ts,
                    GlucoseReading.reading_type == "cgm",
                )
            ).all()
        )
        assert len(same_ts_readings) == 2
        assert {r.device_id for r in same_ts_readings} == {"FreeStyle_Libre_Pro", "Dexcom_G6_Pro"}
        assert all(r.timestamp_semantics == "date_shifted_relative" for r in same_ts_readings)
        assert all(r.timezone_basis == "not_applicable_relative" for r in same_ts_readings)
        assert all(r.raw_timestamp == "2023-05-10 12:00:00" for r in same_ts_readings)
        assert all(r.observation_provenance == "unknown" for r in same_ts_readings)

        # Verify PostgreSQL unique index blocks a duplicate reading for the SAME device at the same timestamp
        sp = db.begin_nested()
        try:
            db.add(
                GlucoseReading(
                    patient_id=cg_p1.id,
                    cohort_type="research_participant",
                    recorded_at=base_cg_ts,
                    raw_timestamp="2023-05-10 12:00:00",
                    timestamp_semantics="date_shifted_relative",
                    timezone_basis="not_applicable_relative",
                    glucose_mg_dl=199.0,
                    raw_value=199.0,
                    raw_unit="mg/dL",
                    reading_type="cgm",
                    device_id="FreeStyle_Libre_Pro",
                    sampling_interval_min=15,
                    observation_provenance="unknown",
                    source_dataset="cgmacros",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
        finally:
            sp.rollback()

        # Verify that native-cadence analytics excludes the 15-min spaced 'unknown' CGMacros rows when native_only=True
        all_cg_readings = list(
            db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == cg_p1.id)).all()
        )
        cg_summary = compute_glucose_summary(
            all_cg_readings, native_only=True, device_id="FreeStyle_Libre_Pro"
        )
        assert cg_summary.observation_count == 0
        assert cg_summary.unknown_observation_count == 4
        assert cg_summary.excluded_non_native_count == 4
        assert cg_summary.calendar_date_comparable is False

        # C. Verify PostgreSQL trigger protects completed DatasetImport provenance from UPDATE and DELETE
        completed_import_id = cg_report.dataset_import_id
        for mut_sql in (
            "UPDATE dataset_imports SET input_payload_checksum = '0000000000000000000000000000000000000000000000000000000000000000' WHERE id = :id",
            "UPDATE dataset_imports SET license_identifier = 'MIT' WHERE id = :id",
            "UPDATE dataset_imports SET dataset_doi = '10.13026/tampered' WHERE id = :id",
            "UPDATE dataset_imports SET dataset_version = 'tampered-v2' WHERE id = :id",
            "UPDATE dataset_imports SET preprocessing_version = 'tampered-v9' WHERE id = :id",
            "DELETE FROM dataset_imports WHERE id = :id",
        ):
            sp_mut = db.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="immutable"):
                    db.execute(text(mut_sql), {"id": completed_import_id})
                    db.flush()
            finally:
                sp_mut.rollback()
    finally:
        db.close()
        outer_tx.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# 7. Exploratory Drift Qualification, Synthetic Demo & Analytics API Isolation
# ---------------------------------------------------------------------------
def test_exploratory_drift_qualification_and_analytics_api_isolation():
    email = f"day3-api-{uuid.uuid4().hex[:8]}@example.com"
    engine = get_engine()
    try:
        with Session(engine) as db:
            demo_summary = seed_synthetic_demo_patient(db, days=6, seed=42)
            assert demo_summary.records_accepted > 500
            assert demo_summary.source_file_checksum is None
            assert demo_summary.input_payload_checksum is not None

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

        client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
        login = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123!"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        sum_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/summary", headers=headers)
        assert sum_resp.status_code == 200, sum_resp.text
        sum_data = sum_resp.json()
        assert sum_data["observation_count"] == 6 * 96
        assert sum_data["native_observation_count"] == 6 * 96
        assert sum_data["coverage"]["period_coverage_pct"] == 100.0

        drift_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/drift", headers=headers)
        assert drift_resp.status_code == 200
        drift_data = drift_resp.json()
        assert drift_data["analysis_type"] == "exploratory_descriptive"
        assert drift_data["is_exploratory"] is True
        assert drift_data["status"] == "upward_drift"
        assert drift_data["baseline_observation_count"] > 0
        assert drift_data["recent_observation_count"] > 0
        assert "serially autocorrelated" in drift_data["statistical_note"]

        meals_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/meal-responses", headers=headers)
        assert meals_resp.status_code == 200
        meal_items = meals_resp.json()
        assert len(meal_items) == 6 * 3
        assert any(m["iauc_valid"] is True and m["iauc_mg_dl_min"] > 0 for m in meal_items)

        meds_resp = client.get(f"/api/v1/patients/{demo_id}/analytics/medication-patterns", headers=headers)
        assert meds_resp.status_code == 200
        assert meds_resp.json()["adherence_computable"] is True

        for sub_route in ("summary", "drift", "meal-responses", "medication-patterns"):
            resp = client.get(f"/api/v1/patients/{research_id}/analytics/{sub_route}", headers=headers)
            assert resp.status_code == 403
    finally:
        with Session(engine) as db:
            u = db.scalar(select(User).where(User.email == email))
            if u is not None:
                db.delete(u)
                db.commit()
