"""Day 4 End-to-End Demo Script for GlyCadence.

Runs the deterministic analytics + LangGraph multi-agent pipeline + Verifier safety gate on:
1. Primary path: Real ShanghaiT2DM v3 research_participant (if ingested in Postgres).
2. Secondary path: SYNTH-DEMO-001 synthetic_demo patient (seeded idempotently if absent).
3. Rejected-draft demo: simulate_bad_draft=True showing the Verifier blocking ungrounded/causal/prescriptive text.

All secrets/keys are read from environment variables (.env) only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.graph import run_investigation_graph
from app.agents.llm import _is_gemini_key_usable
from app.core.config import get_settings
from app.core.database import get_engine
from app.models import GlucoseReading, Meal, Medication, MedicationEvent, Patient, WellbeingRecord


def _ensure_synth_demo(db: Session) -> Patient:
    existing = db.scalar(
        select(Patient).where(
            Patient.cohort_type == "synthetic_demo",
            Patient.external_id == "SYNTH-DEMO-001",
        )
    )
    if existing is not None:
        has_wb = db.scalar(select(WellbeingRecord).where(WellbeingRecord.patient_id == existing.id))
        if has_wb is None:
            base_wb = datetime(2025, 2, 1, 9, 0, tzinfo=timezone.utc)
            db.add_all([
                WellbeingRecord(
                    id=uuid.uuid4(),
                    patient_id=existing.id,
                    cohort_type="synthetic_demo",
                    logged_at=base_wb,
                    stress_score=4,
                    fatigue_score=3,
                    sleep_hours=5.5,
                    sleep_quality=2,
                    illness_flag=False,
                    source_dataset="synthetic_demo",
                ),
                WellbeingRecord(
                    id=uuid.uuid4(),
                    patient_id=existing.id,
                    cohort_type="synthetic_demo",
                    logged_at=base_wb + timedelta(days=1),
                    stress_score=2,
                    fatigue_score=4,
                    sleep_hours=7.0,
                    sleep_quality=4,
                    illness_flag=False,
                    source_dataset="synthetic_demo",
                ),
            ])
            db.commit()
        return existing

    pid = uuid.uuid4()
    patient = Patient(
        id=pid,
        cohort_type="synthetic_demo",
        external_id="SYNTH-DEMO-001",
        source_dataset="synthetic_demo",
        display_name="SYNTH-DEMO-001 (Demo Patient)",
        diabetes_type="T2D",
        timezone="UTC",
        retention_policy="365_days",
    )
    db.add(patient)
    db.flush()

    base_ts = datetime(2025, 2, 1, 8, 0, tzinfo=timezone.utc)
    for i in range(96):
        val = 128.0 + (i % 8) * 10.0
        db.add(
            GlucoseReading(
                id=uuid.uuid4(),
                patient_id=pid,
                cohort_type="synthetic_demo",
                recorded_at=base_ts + timedelta(minutes=15 * i),
                glucose_mg_dl=val,
                raw_value=val,
                raw_unit="mg/dL",
                reading_type="cgm",
                device_id="FreeStyle_Libre_Demo",
                sampling_interval_min=15,
                observation_provenance="native",
                timestamp_semantics="real_world_local",
                timezone_basis="assumed_study_location",
                source_dataset="synthetic_demo",
            )
        )
    db.add(
        Meal(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="synthetic_demo",
            logged_at=base_ts + timedelta(minutes=60),
            meal_type="lunch",
            description="Mixed rice bowl",
            ingredients=[],
            carbs_g=52.0,
            source_dataset="synthetic_demo",
        )
    )
    db.commit()
    db.refresh(patient)
    return patient


def _run_for_patient(db: Session, patient: Patient, label: str, simulate_bad: bool = False) -> dict:
    readings = list(
        db.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.patient_id == patient.id)
            .order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )
    meals = list(
        db.scalars(select(Meal).where(Meal.patient_id == patient.id).order_by(Meal.logged_at.asc())).all()
    )
    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id)).all())
    med_events = list(
        db.scalars(
            select(MedicationEvent)
            .where(MedicationEvent.patient_id == patient.id)
            .order_by(MedicationEvent.event_time.asc())
        ).all()
    )

    state = run_investigation_graph(
        patient_id=str(patient.id),
        cohort_type=patient.cohort_type,
        dataset_label=label,
        readings=readings,
        meals=meals,
        medications=meds,
        medication_events=med_events,
        wellbeing_records=list(
            db.scalars(
                select(WellbeingRecord)
                .where(WellbeingRecord.patient_id == patient.id)
                .order_by(WellbeingRecord.logged_at.asc())
            ).all()
        ),
        simulate_bad_draft=simulate_bad,
    )
    v = state["verifier_report"]
    checksums = sorted(
        {ev.source_record_set_checksum for ev in state["evidence_items"] if ev.source_record_set_checksum}
    )
    return {
        "patient_id": str(patient.id),
        "external_id": patient.external_id,
        "cohort_type": patient.cohort_type,
        "dataset_label": label,
        "execution_mode": state["execution_mode"],
        "model_used": state["model_used"],
        "fallback_reason": state.get("fallback_reason"),
        "verification_status": v.verification_status,
        "safety_passed": v.passed,
        "failed_reasons": v.failed_reasons,
        "evidence_checksum_count": len(checksums),
        "sample_checksum": checksums[0] if checksums else None,
        "patient_summary_displayed": state["draft"].get("patient_summary") if v.passed else None,
    }


def main() -> None:
    settings = get_settings()
    engine = get_engine()
    results: dict[str, object] = {
        "configured_gemini_model": settings.gemini_model,
        "configured_execution_mode": settings.agent_execution_mode,
        "gemini_key_present": _is_gemini_key_usable(settings.gemini_api_key),
    }

    with Session(engine) as db:
        shanghai_patient = db.scalar(
            select(Patient)
            .where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == "shanghai_t2dm",
                Patient.external_id.not_like("SH-TEST-%"),
            )
            .order_by(Patient.external_id.asc())
        )
        if shanghai_patient is not None:
            results["primary_shanghai_t2dm_v3"] = _run_for_patient(
                db,
                shanghai_patient,
                f"ShanghaiT2DM v3 ({shanghai_patient.external_id or shanghai_patient.id}) — Research Dataset (Read-Only)",
            )
        else:
            results["primary_shanghai_t2dm_v3"] = {
                "status": "not_ingested_yet",
                "hint": "Ingest ShanghaiT2DM v3 first to run the primary research cohort demo path.",
            }

        synth_patient = _ensure_synth_demo(db)
        results["secondary_synth_demo_001"] = _run_for_patient(
            db, synth_patient, "SYNTH-DEMO-001 (Synthetic Demo)"
        )
        results["rejected_bad_draft_demo"] = _run_for_patient(
            db, synth_patient, "SYNTH-DEMO-001 (Rejected Bad Draft Demo)", simulate_bad=True
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
