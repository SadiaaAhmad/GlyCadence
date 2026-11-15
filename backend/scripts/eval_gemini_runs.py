"""Evaluate real Gemini API runs across 3 patient profiles (12 runs total).

Usage (requires a real GEMINI_API_KEY in .env; never paste keys in chat):
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\eval_gemini_runs.py
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

from app.agents.graph import run_investigation_graph
from app.agents.llm import _is_gemini_key_usable
from app.core.config import get_settings
from app.models import GlucoseReading, Meal, Medication, MedicationEvent


def _build_patient_fixture(profile_idx: int) -> tuple[str, str, list, list, list, list]:
    pid = uuid.uuid4()
    base_ts = datetime(2025, 3, 1 + profile_idx, 8, 0, tzinfo=timezone.utc)
    readings = [
        GlucoseReading(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="synthetic_demo",
            recorded_at=base_ts + timedelta(minutes=15 * i),
            glucose_mg_dl=118.0 + (profile_idx * 14.0) + (i % 7) * 9.0,
            raw_value=118.0 + (profile_idx * 14.0) + (i % 7) * 9.0,
            raw_unit="mg/dL",
            reading_type="cgm",
            device_id="FreeStyle_Libre_Eval",
            sampling_interval_min=15,
            observation_provenance="native",
            timestamp_semantics="real_world_local",
            timezone_basis="assumed_study_location",
            source_dataset="synthetic_demo",
        )
        for i in range(96)
    ]
    meals = [
        Meal(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="synthetic_demo",
            logged_at=base_ts + timedelta(minutes=15 * 6),
            meal_type="lunch",
            description="Balanced meal",
            ingredients=[],
            carbs_g=45.0 + profile_idx * 10.0,
            source_dataset="synthetic_demo",
        )
    ]
    meds = [
        Medication(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="synthetic_demo",
            medication_name="Metformin 500mg",
            drug_class="non_insulin_hypoglycemic",
            is_active=True,
            source_dataset="synthetic_demo",
        )
    ]
    med_events = [
        MedicationEvent(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="synthetic_demo",
            medication_id=meds[0].id,
            event_time=base_ts + timedelta(minutes=60),
            status="taken",
            event_source="user_log",
            source_dataset="synthetic_demo",
        )
    ]
    return str(pid), f"EVAL-PATIENT-{profile_idx + 1}", readings, meals, meds, med_events


def main() -> None:
    settings = get_settings()
    if not _is_gemini_key_usable(settings.gemini_api_key):
        print(
            json.dumps(
                {
                    "status": "skipped_no_gemini_key",
                    "configured_gemini_model": settings.gemini_model,
                    "message": "Set a real GEMINI_API_KEY in .env (never in chat) and re-run this script.",
                },
                indent=2,
            )
        )
        sys.exit(2)

    runs_per_patient = 4
    total_runs = 0
    passed_first_try = 0
    passed_after_repair = 0
    rejected = 0
    models_seen: set[str] = set()
    per_run: list[dict[str, object]] = []

    for p_idx in range(3):
        pid, label, readings, meals, meds, med_events = _build_patient_fixture(p_idx)
        for r_idx in range(runs_per_patient):
            state = run_investigation_graph(
                patient_id=pid,
                cohort_type="synthetic_demo",
                dataset_label=label,
                readings=readings,
                meals=meals,
                medications=meds,
                medication_events=med_events,
                mode="gemini",
            )
            total_runs += 1
            v = state["verifier_report"]
            models_seen.add(state["model_used"])
            if v.passed and v.repair_attempts == 0:
                passed_first_try += 1
            elif v.passed and v.repair_attempts > 0:
                passed_after_repair += 1
            else:
                rejected += 1

            per_run.append(
                {
                    "patient": label,
                    "run_index": r_idx + 1,
                    "execution_mode": state["execution_mode"],
                    "model_used": state["model_used"],
                    "fallback_reason": state.get("fallback_reason"),
                    "passed": v.passed,
                    "repair_attempts": v.repair_attempts,
                    "failed_reasons": v.failed_reasons,
                }
            )

    print(
        json.dumps(
            {
                "models_used": sorted(models_seen),
                "total_runs": total_runs,
                "passed_first_try": passed_first_try,
                "passed_after_repair": passed_after_repair,
                "rejected": rejected,
                "runs": per_run,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
