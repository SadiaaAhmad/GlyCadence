from datetime import datetime, timedelta, timezone
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.common import (
    PREPROCESSING_VERSION,
    IngestionSummary,
    compute_input_payload_checksum,
)
from app.models import (
    ActivityRecord,
    ClinicalRecord,
    DatasetImport,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
    WellbeingRecord,
)

DATASET_NAME = "synthetic_demo"
SYNTHETIC_EXTERNAL_ID = "SYNTH-DEMO-001"
LICENSE_IDENTIFIER = "INTERNAL-SYNTHETIC-DEMO"


def seed_synthetic_demo_patient(
    db: Session,
    *,
    days: int = 14,
    seed: int = 42,
    start_time: datetime | None = None,
) -> IngestionSummary:
    """Generate a deterministic synthetic_demo patient for UX demonstration only.

    WARNING: Tagged strictly with ``cohort_type = 'synthetic_demo'``. Must NEVER be
    used for clinical validation or mixed with ``research_participant`` cohorts.
    """
    rng = random.Random(seed)
    base_start = start_time or datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    payload_checksum = compute_input_payload_checksum(
        {"dataset": DATASET_NAME, "days": days, "seed": seed, "start_time": base_start.isoformat()}
    )

    dataset_import = DatasetImport(
        dataset_name=DATASET_NAME,
        dataset_version=f"synth-v1-d{days}-s{seed}",
        license_identifier=LICENSE_IDENTIFIER,
        source_file_checksum=None,
        input_payload_checksum=payload_checksum,
        preprocessing_version=PREPROCESSING_VERSION,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(dataset_import)
    db.flush()

    existing = db.scalar(
        select(Patient).where(
            Patient.cohort_type == "synthetic_demo",
            Patient.external_id == SYNTHETIC_EXTERNAL_ID,
        )
    )
    if existing is not None:
        existing.retention_expires_at = None
        db.flush()
        db.delete(existing)
        db.flush()

    patient = Patient(
        user_id=None,
        dataset_import_id=dataset_import.id,
        cohort_type="synthetic_demo",
        external_id=SYNTHETIC_EXTERNAL_ID,
        display_name="Demo Patient — Amina Khan (Synthetic)",
        age=54,
        sex="female",
        diabetes_type="T2D",
        height_cm=162.0,
        weight_kg=74.5,
        dietary_restrictions=["halal"],
        cultural_cuisine_pref="South Asian / Pakistani",
        consent_granted=False,
        retention_policy="365_days",
        source_dataset=DATASET_NAME,
    )
    db.add(patient)
    db.flush()

    accepted = 0
    cgm_count = 0
    db.add(
        ClinicalRecord(
            patient_id=patient.id,
            cohort_type="synthetic_demo",
            dataset_import_id=dataset_import.id,
            recorded_at=base_start,
            hba1c_pct=7.6,
            bmi=28.4,
            fasting_glucose_mg_dl=134.0,
            egfr=84.0,
            source_dataset=DATASET_NAME,
            source_record_id="synth:clinical:0",
        )
    )
    accepted += 1

    metformin = Medication(
        patient_id=patient.id,
        cohort_type="synthetic_demo",
        dataset_import_id=dataset_import.id,
        medication_name="Metformin XR",
        drug_class="biguanide",
        recorded_dose="500 mg",
        prescribed_schedule="twice_daily",
        is_active=True,
        start_date=base_start.date(),
        source_dataset=DATASET_NAME,
        source_record_id="synth:med:metformin",
    )
    db.add(metformin)
    db.flush()
    accepted += 1

    for day_idx in range(days):
        day_start = base_start + timedelta(days=day_idx)
        drift_offset = 18.0 if day_idx >= (days * 2 // 3) else 0.0

        meals_spec = [
            (8, 0, "breakfast", "Whole-wheat paratha with omelette & unsweetened chai", 420.0, 46.0, 16.0, 18.0, 6.0, 32.0),
            (13, 30, "lunch", "Chana daal with brown basmati rice & cucumber raita", 540.0, 64.0, 22.0, 14.0, 11.0, 48.0),
            (19, 30, "dinner", "Grilled chicken chapli kabab with 2 whole-wheat rotis & bhindi", 580.0, 58.0, 34.0, 21.0, 9.0, 52.0),
        ]
        meal_spikes: list[tuple[datetime, float]] = []
        for hr, mn, mtype, desc, cal, carbs, prot, fat, fib, spike in meals_spec:
            m_ts = day_start + timedelta(hours=hr, minutes=mn)
            meal_spikes.append((m_ts, spike))
            db.add(
                Meal(
                    patient_id=patient.id,
                    cohort_type="synthetic_demo",
                    dataset_import_id=dataset_import.id,
                    logged_at=m_ts,
                    raw_timestamp=m_ts.isoformat(),
                    timestamp_semantics="utc_exact",
                    meal_type=mtype,
                    description=desc,
                    ingredients=[desc],
                    calories=cal,
                    carbs_g=carbs,
                    protein_g=prot,
                    fat_g=fat,
                    fiber_g=fib,
                    cultural_tag="south_asian",
                    source_dataset=DATASET_NAME,
                    source_record_id=f"synth:meal:d{day_idx}:{mtype}",
                )
            )
            accepted += 1

        for step in range(96):
            ts = day_start + timedelta(minutes=15 * step)
            baseline = 122.0 + drift_offset + rng.uniform(-5.0, 5.0)
            postprandial = 0.0
            for m_ts, peak in meal_spikes:
                dt_min = (ts - m_ts).total_seconds() / 60.0
                if 0.0 < dt_min <= 180.0:
                    if dt_min <= 60.0:
                        postprandial += peak * (dt_min / 60.0)
                    else:
                        postprandial += peak * max(0.0, 1.0 - (dt_min - 60.0) / 120.0)
            val = round(baseline + postprandial, 1)
            db.add(
                GlucoseReading(
                    patient_id=patient.id,
                    cohort_type="synthetic_demo",
                    dataset_import_id=dataset_import.id,
                    recorded_at=ts,
                    raw_timestamp=ts.isoformat(),
                    timestamp_semantics="utc_exact",
                    glucose_mg_dl=val,
                    raw_value=val,
                    raw_unit="mg/dL",
                    reading_type="cgm",
                    device_id="Synthetic_CGM_15m",
                    sampling_interval_min=15,
                    observation_provenance="native",
                    source_dataset=DATASET_NAME,
                    source_record_id=f"synth:cgm:d{day_idx}:s{step}",
                )
            )
            accepted += 1
            cgm_count += 1

        for dose_idx, hr in enumerate((8, 20)):
            ev_ts = day_start + timedelta(hours=hr, minutes=15)
            status = "missed" if (day_idx >= (days * 2 // 3) and dose_idx == 1) else "taken"
            db.add(
                MedicationEvent(
                    patient_id=patient.id,
                    cohort_type="synthetic_demo",
                    medication_id=metformin.id,
                    event_time=ev_ts,
                    status=status,
                    event_source="patient_log",
                    source_dataset=DATASET_NAME,
                    source_record_id=f"synth:med_ev:d{day_idx}:{dose_idx}",
                )
            )
            accepted += 1

        illness_cycle = (False, None, True) if day_idx == days - 1 else (False, None, False)
        db.add(
            WellbeingRecord(
                patient_id=patient.id,
                cohort_type="synthetic_demo",
                logged_at=day_start + timedelta(hours=21),
                stress_score=4 if day_idx >= (days * 2 // 3) else 2,
                fatigue_score=3,
                sleep_hours=6.2 if day_idx >= (days * 2 // 3) else 7.5,
                sleep_quality=3 if day_idx >= (days * 2 // 3) else 4,
                illness_flag=illness_cycle[day_idx % 3],
                source_dataset=DATASET_NAME,
                source_record_id=f"synth:wellbeing:d{day_idx}",
            )
        )
        db.add(
            ActivityRecord(
                patient_id=patient.id,
                cohort_type="synthetic_demo",
                recorded_at=day_start + timedelta(hours=18),
                steps=5800 + rng.randint(-800, 1200),
                active_minutes=32,
                heart_rate_bpm=98.0,
                activity_type="evening_walk",
                intensity="moderate",
                source_dataset=DATASET_NAME,
                source_record_id=f"synth:activity:d{day_idx}",
            )
        )
        accepted += 2

    dataset_import.status = "completed"
    dataset_import.records_accepted = accepted
    dataset_import.records_rejected = 0
    dataset_import.completed_at = datetime.now(timezone.utc)
    dataset_import.quality_report_summary = {
        "records_accepted": accepted,
        "records_rejected": 0,
        "rejection_reasons": {},
        "synthetic_disclaimer": "Synthetic demo cohort only; never used for clinical validation.",
    }
    db.commit()

    return IngestionSummary(
        dataset_import_id=str(dataset_import.id),
        dataset_name=DATASET_NAME,
        dataset_version=dataset_import.dataset_version,
        license_identifier=LICENSE_IDENTIFIER,
        preprocessing_version=PREPROCESSING_VERSION,
        source_file_checksum=None,
        input_payload_checksum=payload_checksum,
        records_accepted=accepted,
        records_rejected=0,
        rejection_reasons={},
        rejected_samples=[],
        participants_ingested=1,
        observation_provenance_counts={"native": cgm_count, "interpolated": 0, "derived": 0, "unknown": 0},
        timestamp_semantics="utc_exact",
    )
