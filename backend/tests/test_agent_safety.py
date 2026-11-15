from datetime import datetime, timedelta, timezone
import uuid

from app.agents import run_investigation_graph, verify_agent_draft
from app.models import GlucoseReading, Meal, Medication, MedicationEvent
from app.schemas.analytics import DriftSummaryOut, EvidenceItem, MealResponseItem, SourceRecordRef


def _make_evidence(
    *,
    metric_name: str = "mean_glucose_mg_dl",
    current_value: float = 142.5,
    baseline_value: float | None = None,
    delta: float | None = None,
    unit: str = "mg/dL",
    provenance_counts: dict[str, int] | None = None,
) -> EvidenceItem:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    return EvidenceItem(
        metric_name=metric_name,
        baseline_value=baseline_value,
        current_value=current_value,
        delta=delta,
        unit=unit,
        observation_count=96,
        expected_observation_count=96,
        window_start=now - timedelta(hours=24),
        window_end=now,
        source_datasets=("shanghai_t2dm",),
        source_records=(
            SourceRecordRef(table_name="glucose_readings", record_id="r-1", source_dataset="shanghai_t2dm"),
        ),
        calculation_method="arithmetic_mean_native_cadence",
        missingness_pct=0.0,
        provenance_counts=provenance_counts or {"native": 96},
    )


def test_verifier_rejects_ungrounded_bare_numbers_and_requires_named_thresholds():
    ev = _make_evidence(current_value=142.5)

    # 1. Deliberately bad draft with ungrounded number 312 and bare uncontextualized 70
    bad_rep = verify_agent_draft(
        patient_text="Mean glucose was 142.5 mg/dL, with a peak of 312 and score 70.",
        clinician_text="Patient had 96 readings.",
        evidence_items=[ev],
    )
    assert bad_rep.passed is False
    assert bad_rep.verification_status == "rejected"
    assert "numeric_ungrounded" in bad_rep.failed_reasons
    assert "312" in bad_rep.ungrounded_numbers
    assert "70" in bad_rep.ungrounded_numbers

    # 2. Properly grounded draft using EvidenceItem values + named GlycemicThresholds with units/context
    good_rep = verify_agent_draft(
        patient_text=(
            "Mean glucose was 142.5 mg/dL across 96 readings (0.0% missingness), "
            "compared against the 70-180 mg/dL target range and 70% engineering coverage threshold."
        ),
        clinician_text="96 observations evaluated against 14-day clinical guidance.",
        evidence_items=[ev],
    )
    assert good_rep.passed is True
    assert good_rep.verification_status == "passed"
    assert "target_range_low_mg_dl" in good_rep.named_thresholds_used
    assert "target_range_high_mg_dl" in good_rep.named_thresholds_used
    assert "clinical_guidance_min_days" in good_rep.named_thresholds_used


def test_verifier_rejects_unit_swaps_and_direction_contradictions():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    ev_iauc = _make_evidence(
        metric_name="postprandial_iauc_mg_dl_min",
        current_value=0.0,
        unit="mg/dL*min",
    )
    declining_meal = MealResponseItem(
        meal_id="m-1",
        logged_at=now,
        meal_type="lunch",
        description="Salad",
        carbs_g=10.0,
        pre_meal_glucose_mg_dl=160.0,
        pre_meal_recorded_at=now - timedelta(minutes=10),
        peak_post_meal_glucose_mg_dl=140.0,
        excursion_delta_mg_dl=-20.0,
        excursion_direction="postprandial_decline",
        post_meal_reading_count=6,
        post_meal_span_minutes=120.0,
        max_consecutive_gap_minutes=30.0,
        iauc_mg_dl_min=0.0,
        iauc_valid=True,
        rejection_reasons=[],
        uncertainty_notes=[],
    )
    upward_drift = DriftSummaryOut(
        window_start=now - timedelta(days=2),
        window_end=now,
        status="upward_drift",
        baseline_mean_mg_dl=120.0,
        recent_mean_mg_dl=145.0,
        delta_mg_dl=25.0,
        deterministic_confidence=0.9,
        uncertainty_notes=[],
    )

    bad_rep = verify_agent_draft(
        patient_text="Your lunch caused a glucose spike with iAUC 0.0 mg/dL and downward drift.",
        clinician_text="Observed upward_drift of 25.0 mg/dL.",
        evidence_items=[ev_iauc],
        meal_responses=[declining_meal],
        drift_summary=upward_drift,
        extra_grounded_numbers=[25.0],
    )
    assert bad_rep.passed is False
    assert "unit_mismatch" in bad_rep.failed_reasons
    assert "direction_contradiction" in bad_rep.failed_reasons


def test_verifier_rejects_causal_and_prescriptive_language():
    ev = _make_evidence(current_value=142.5)
    bad_rep = verify_agent_draft(
        patient_text=(
            "Mean glucose 142.5 mg/dL was caused by your dinner and proves that "
            "you should increase your dose immediately (statistically significant, p < 0.01)."
        ),
        clinician_text="96 readings.",
        evidence_items=[ev],
    )
    assert bad_rep.passed is False
    assert "causal_overclaim" in bad_rep.failed_reasons
    assert "prescriptive_overclaim" in bad_rep.failed_reasons


def test_verifier_requires_provenance_disclosure_for_dataset_documented():
    ev = _make_evidence(
        current_value=135.0,
        provenance_counts={"native": 0, "dataset_documented": 96},
    )
    bad_rep = verify_agent_draft(
        patient_text="Mean glucose was 135.0 mg/dL across 96 readings (0.0% missingness).",
        clinician_text="Summary complete.",
        evidence_items=[ev],
    )
    assert bad_rep.passed is False
    assert "missing_provenance_disclosure" in bad_rep.failed_reasons


def test_langgraph_pipeline_deterministic_fallback_and_simulate_bad_draft():
    pid = uuid.uuid4()
    base_ts = datetime(2023, 5, 1, 8, 0, tzinfo=timezone.utc)
    readings = [
        GlucoseReading(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="research_participant",
            recorded_at=base_ts + timedelta(minutes=15 * i),
            glucose_mg_dl=120.0 + (i % 6) * 5.0 + (20.0 if i > 48 else 0.0),
            raw_value=120.0,
            raw_unit="mg/dL",
            reading_type="cgm",
            device_id="FreeStyle_Libre_H",
            sampling_interval_min=15,
            observation_provenance="dataset_documented",
            timestamp_semantics="real_world_local",
            timezone_basis="assumed_study_location",
            source_dataset="shanghai_t2dm",
        )
        for i in range(96)
    ]
    meal_ts = base_ts + timedelta(minutes=15 * 4)
    meals = [
        Meal(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="research_participant",
            logged_at=meal_ts,
            meal_type="lunch",
            description="Steamed rice",
            ingredients=[],
            carbs_g=45.0,
            source_dataset="shanghai_t2dm",
        )
    ]
    meds = [
        Medication(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="research_participant",
            medication_name="Metformin 0.5g",
            drug_class="non_insulin_hypoglycemic",
            is_active=True,
            source_dataset="shanghai_t2dm",
        )
    ]
    med_events = [
        MedicationEvent(
            id=uuid.uuid4(),
            patient_id=pid,
            cohort_type="research_participant",
            medication_id=meds[0].id,
            event_time=meal_ts,
            status="unknown",
            event_source="clinical_record",
            source_dataset="shanghai_t2dm",
        )
    ]

    # 1. Normal deterministic fallback run passes Verifier and reports execution_mode + model_used
    state_ok = run_investigation_graph(
        patient_id=str(pid),
        cohort_type="research_participant",
        dataset_label="ShanghaiT2DM v3 (ST2D-1001)",
        readings=readings,
        meals=meals,
        medications=meds,
        medication_events=med_events,
        mode="deterministic_fallback",
    )
    assert state_ok["execution_mode"] == "deterministic_fallback"
    assert state_ok["model_used"] == "deterministic_template_v1"
    assert state_ok["verifier_report"].passed is True
    assert "dataset_documented" in state_ok["draft"]["patient_summary"]
    assert len(state_ok["observations"]) == 3

    # 2. Simulated bad draft is blocked by Verifier
    state_bad = run_investigation_graph(
        patient_id=str(pid),
        cohort_type="research_participant",
        dataset_label="ShanghaiT2DM v3 (ST2D-1001)",
        readings=readings,
        meals=meals,
        medications=meds,
        medication_events=med_events,
        simulate_bad_draft=True,
    )
    assert state_bad["verifier_report"].passed is False
    assert state_bad["verifier_report"].verification_status == "rejected"
    assert "numeric_ungrounded" in state_bad["verifier_report"].failed_reasons
    assert "causal_overclaim" in state_bad["verifier_report"].failed_reasons
    assert "prescriptive_overclaim" in state_bad["verifier_report"].failed_reasons


def test_investigations_api_cohort_isolation_bad_draft_and_audit():
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.core.database import get_engine
    from app.core.rate_limit import reset_rate_limiter
    from app.main import app
    from app.models import (
        AuditLog,
        DoctorReport,
        Investigation,
        Patient,
        User,
    )

    reset_rate_limiter()
    client = TestClient(app)
    engine = get_engine()

    patient_email = f"inv-pat-{uuid.uuid4().hex[:8]}@example.com"
    researcher_email = f"inv-res-{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPass123!"

    reg_p = client.post("/api/v1/auth/register", json={"email": patient_email, "password": password})
    assert reg_p.status_code == 201, reg_p.text
    reg_r = client.post("/api/v1/auth/register", json={"email": researcher_email, "password": password})
    assert reg_r.status_code == 201, reg_r.text

    research_pid = uuid.uuid4()
    demo_pid = uuid.uuid4()
    base_ts = datetime(2025, 2, 1, 8, 0, tzinfo=timezone.utc)

    with Session(engine) as db:
        researcher_user = db.scalar(select(User).where(User.email == researcher_email))
        assert researcher_user is not None
        researcher_user.role = "researcher"

        research_patient = Patient(
            id=research_pid,
            cohort_type="research_participant",
            external_id=f"SH-TEST-{uuid.uuid4().hex[:6]}",
            source_dataset="shanghai_t2dm",
            display_name="ShanghaiT2DM Test Subject",
            diabetes_type="T2D",
            timezone="Asia/Shanghai",
            retention_policy="research_archive",
        )
        demo_patient = Patient(
            id=demo_pid,
            cohort_type="synthetic_demo",
            external_id=f"SYNTH-TEST-{uuid.uuid4().hex[:6]}",
            source_dataset="synthetic_demo",
            display_name="Synthetic Demo Test",
            diabetes_type="T2D",
            timezone="UTC",
            retention_policy="365_days",
        )
        db.add_all([research_patient, demo_patient])
        db.flush()

        for pid, src, prov in [
            (research_pid, "shanghai_t2dm", "dataset_documented"),
            (demo_pid, "synthetic_demo", "native"),
        ]:
            for i in range(48):
                db.add(
                    GlucoseReading(
                        id=uuid.uuid4(),
                        patient_id=pid,
                        cohort_type="research_participant" if pid == research_pid else "synthetic_demo",
                        recorded_at=base_ts + timedelta(minutes=15 * i),
                        glucose_mg_dl=122.0 + (i % 6) * 8.0,
                        raw_value=122.0 + (i % 6) * 8.0,
                        raw_unit="mg/dL",
                        reading_type="cgm",
                        device_id="FreeStyle_Libre_H",
                        sampling_interval_min=15,
                        observation_provenance=prov,
                        timestamp_semantics="real_world_local",
                        timezone_basis="assumed_study_location",
                        source_dataset=src,
                    )
                )
            db.add(
                Meal(
                    id=uuid.uuid4(),
                    patient_id=pid,
                    cohort_type="research_participant" if pid == research_pid else "synthetic_demo",
                    logged_at=base_ts + timedelta(minutes=60),
                    meal_type="lunch",
                    description="Steamed rice",
                    ingredients=[],
                    carbs_g=45.0,
                    source_dataset=src,
                )
            )
        db.commit()

    created_inv_ids: list[uuid.UUID] = []
    try:
        tok_p = client.post("/api/v1/auth/login", json={"email": patient_email, "password": password}).json()["access_token"]
        tok_r = client.post("/api/v1/auth/login", json={"email": researcher_email, "password": password}).json()["access_token"]

        # 1. Ordinary user cannot see research_participant in GET /patients or run investigations on it
        list_p = client.get("/api/v1/patients", headers={"Authorization": f"Bearer {tok_p}"})
        assert list_p.status_code == 200
        listed_ids_p = {item["id"] for item in list_p.json()}
        assert str(research_pid) not in listed_ids_p
        assert str(demo_pid) in listed_ids_p

        forbidden = client.post(
            f"/api/v1/patients/{research_pid}/investigations",
            headers={"Authorization": f"Bearer {tok_p}"},
            json={},
        )
        assert forbidden.status_code == 403

        # 2. Researcher sees shanghai_t2dm in GET /patients and can run read-only investigation
        list_r = client.get("/api/v1/patients", headers={"Authorization": f"Bearer {tok_r}"})
        assert list_r.status_code == 200
        assert any(item["id"] == str(research_pid) for item in list_r.json())

        res_inv = client.post(
            f"/api/v1/patients/{research_pid}/investigations",
            headers={"Authorization": f"Bearer {tok_r}"},
            json={"mode": "deterministic_fallback"},
        )
        assert res_inv.status_code == 201, res_inv.text
        res_body = res_inv.json()
        created_inv_ids.append(uuid.UUID(res_body["id"]))
        assert res_body["is_research_dataset"] is True
        assert res_body["execution_mode"] == "deterministic_fallback"
        assert res_body["model_used"] == "deterministic_template_v1"
        assert res_body["safety_passed"] is True
        assert res_body["doctor_report"]["is_safe_to_display"] is True
        assert "dataset_documented" in res_body["primary_summary_patient"]

        # 3. Ordinary user on synthetic_demo: normal run passes, simulate_bad_draft is blocked
        demo_ok = client.post(
            f"/api/v1/patients/{demo_pid}/investigations",
            headers={"Authorization": f"Bearer {tok_p}"},
            json={"mode": "deterministic_fallback"},
        )
        assert demo_ok.status_code == 201, demo_ok.text
        ok_body = demo_ok.json()
        created_inv_ids.append(uuid.UUID(ok_body["id"]))
        assert ok_body["safety_passed"] is True
        assert ok_body["doctor_report"]["is_safe_to_display"] is True

        demo_bad = client.post(
            f"/api/v1/patients/{demo_pid}/investigations",
            headers={"Authorization": f"Bearer {tok_p}"},
            json={"mode": "deterministic_fallback", "simulate_bad_draft": True},
        )
        assert demo_bad.status_code == 201, demo_bad.text
        bad_body = demo_bad.json()
        created_inv_ids.append(uuid.UUID(bad_body["id"]))
        assert bad_body["safety_passed"] is False
        assert bad_body["primary_summary_patient"] is None
        assert bad_body["doctor_report"]["is_safe_to_display"] is False
        assert bad_body["verifier_report"]["verification_status"] == "rejected"

        # 4. GET investigation list & detail
        get_detail = client.get(
            f"/api/v1/patients/{demo_pid}/investigations/{bad_body['id']}",
            headers={"Authorization": f"Bearer {tok_p}"},
        )
        assert get_detail.status_code == 200
        assert get_detail.json()["id"] == bad_body["id"]

        # 5. Audit logs contain checksums and IDs, never API keys or raw patient free text
        with Session(engine) as db:
            audits = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.resource_type == "investigation",
                        AuditLog.resource_id.in_([str(x) for x in created_inv_ids]),
                    )
                ).all()
            )
            assert len(audits) == 4
            create_audits = [a for a in audits if a.action == "create_log"]
            assert len(create_audits) == 3
            for a in create_audits:
                assert "evidence_checksums" in a.context_metadata
            for a in audits:
                meta_str = str(a.context_metadata)
                assert "AIza" not in meta_str
                assert "gemini_api_key" not in meta_str.lower()
                assert "Steamed rice" not in meta_str
                assert "patient_summary" not in a.context_metadata
    finally:
        reset_rate_limiter()
        with Session(engine) as db:
            for inv_id in created_inv_ids:
                dr = db.scalar(select(DoctorReport).where(DoctorReport.investigation_id == inv_id))
                if dr is not None:
                    db.delete(dr)
                inv = db.get(Investigation, inv_id)
                if inv is not None:
                    db.delete(inv)
            for email in (patient_email, researcher_email):
                u = db.scalar(select(User).where(User.email == email))
                if u is not None:
                    db.delete(u)
            db.commit()
