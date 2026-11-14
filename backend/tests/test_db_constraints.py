import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.core.security import hash_password
from app.models import (
    AgentObservation,
    DoctorReport,
    GlucoseReading,
    Investigation,
    Medication,
    MedicationEvent,
    Patient,
    User,
    WellbeingRecord,
)


def _new_session() -> Session:
    engine = get_engine()
    assert engine is not None
    return Session(bind=engine)


def test_all_15_tables_exist() -> None:
    engine = get_engine()
    assert engine is not None
    tables = set(inspect(engine).get_table_names())
    expected = {
        "users",
        "user_sessions",
        "dataset_imports",
        "patients",
        "audit_logs",
        "clinical_records",
        "glucose_readings",
        "meals",
        "medications",
        "medication_events",
        "activity_records",
        "wellbeing_records",
        "investigations",
        "agent_observations",
        "doctor_reports",
    }
    assert expected.issubset(tables)


def test_composite_fk_blocks_cross_cohort_glucose() -> None:
    db = _new_session()
    user_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    try:
        db.add(User(id=user_id, email=f"cohort-{user_id}@test.local", password_hash=hash_password("Pass1234!")))
        db.flush()
        db.add(
            Patient(
                id=patient_id,
                user_id=user_id,
                cohort_type="app_user",
                display_name="Cohort Test",
                diabetes_type="T2D",
                consent_granted=True,
                source_dataset="app_user",
            )
        )
        db.commit()

        # Attempt to insert glucose reading with mismatched cohort_type
        db.add(
            GlucoseReading(
                patient_id=patient_id,
                cohort_type="research_participant",
                recorded_at=datetime.now(timezone.utc),
                glucose_mg_dl=120.0,
                raw_value=120.0,
                raw_unit="mg/dL",
                reading_type="fasting",
                source_dataset="app_user",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        u = db.get(User, user_id)
        p = db.get(Patient, patient_id)
        if p:
            db.delete(p)
        if u:
            db.delete(u)
        db.commit()
        db.close()


def test_scoped_medication_event_fk_blocks_other_patient_med() -> None:
    db = _new_session()
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    med_p1 = uuid.uuid4()
    try:
        db.add_all([
            User(id=u1, email=f"m1-{u1}@test.local", password_hash=hash_password("Pass1234!")),
            User(id=u2, email=f"m2-{u2}@test.local", password_hash=hash_password("Pass1234!")),
        ])
        db.flush()
        db.add_all([
            Patient(id=p1, user_id=u1, cohort_type="app_user", display_name="P1", diabetes_type="T2D", consent_granted=True),
            Patient(id=p2, user_id=u2, cohort_type="app_user", display_name="P2", diabetes_type="T2D", consent_granted=True),
        ])
        db.flush()
        db.add(
            Medication(
                id=med_p1,
                patient_id=p1,
                cohort_type="app_user",
                medication_name="Metformin",
            )
        )
        db.commit()

        # Attempt to attach p1's medication_id to p2's medication_event
        db.add(
            MedicationEvent(
                patient_id=p2,
                cohort_type="app_user",
                medication_id=med_p1,
                event_time=datetime.now(timezone.utc),
                status="taken",
                event_source="patient_log",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        for pid in (p1, p2):
            p = db.get(Patient, pid)
            if p:
                db.delete(p)
        for uid in (u1, u2):
            u = db.get(User, uid)
            if u:
                db.delete(u)
        db.commit()
        db.close()


def test_scoped_investigation_fk_and_doctor_report_default_unsafe() -> None:
    db = _new_session()
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    inv_p1 = uuid.uuid4()
    rep_p1 = uuid.uuid4()
    try:
        db.add_all([
            User(id=u1, email=f"i1-{u1}@test.local", password_hash=hash_password("Pass1234!")),
            User(id=u2, email=f"i2-{u2}@test.local", password_hash=hash_password("Pass1234!")),
        ])
        db.flush()
        db.add_all([
            Patient(id=p1, user_id=u1, cohort_type="app_user", display_name="P1", diabetes_type="T2D", consent_granted=True),
            Patient(id=p2, user_id=u2, cohort_type="app_user", display_name="P2", diabetes_type="T2D", consent_granted=True),
        ])
        db.flush()
        now = datetime.now(timezone.utc)
        db.add(
            Investigation(
                id=inv_p1,
                patient_id=p1,
                cohort_type="app_user",
                status="queued",
                window_start=now,
                window_end=now,
            )
        )
        db.flush()
        rep = DoctorReport(
            id=rep_p1,
            patient_id=p1,
            cohort_type="app_user",
            investigation_id=inv_p1,
            period_start=now,
            period_end=now,
            report_payload={},
            clinician_questions=[],
        )
        db.add(rep)
        db.commit()
        db.refresh(rep)
        assert rep.safety_passed is False

        # Cross-patient AgentObservation must fail
        db.add(
            AgentObservation(
                patient_id=p2,
                cohort_type="app_user",
                investigation_id=inv_p1,
                agent_name="pattern_watcher",
                window_start=now,
                window_end=now,
                finding_summary="test",
                evidence_items=[],
                observation_count=0,
                missingness_pct=0.0,
                deterministic_confidence=0.0,
                uncertainty_notes=[],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        for pid in (p1, p2):
            p = db.get(Patient, pid)
            if p:
                db.delete(p)
        for uid in (u1, u2):
            u = db.get(User, uid)
            if u:
                db.delete(u)
        db.commit()
        db.close()


def test_wellbeing_illness_flag_preserves_null_false_true() -> None:
    db = _new_session()
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    try:
        db.add(User(id=uid, email=f"wb-{uid}@test.local", password_hash=hash_password("Pass1234!")))
        db.flush()
        db.add(Patient(id=pid, user_id=uid, cohort_type="app_user", display_name="WB", diabetes_type="T2D", consent_granted=True))
        db.flush()
        now = datetime.now(timezone.utc)
        r_null = WellbeingRecord(patient_id=pid, cohort_type="app_user", logged_at=now, illness_flag=None)
        r_false = WellbeingRecord(patient_id=pid, cohort_type="app_user", logged_at=now, illness_flag=False)
        r_true = WellbeingRecord(patient_id=pid, cohort_type="app_user", logged_at=now, illness_flag=True)
        db.add_all([r_null, r_false, r_true])
        db.commit()
        db.refresh(r_null)
        db.refresh(r_false)
        db.refresh(r_true)
        assert r_null.illness_flag is None
        assert r_false.illness_flag is False
        assert r_true.illness_flag is True
    finally:
        p = db.get(Patient, pid)
        if p:
            db.delete(p)
        u = db.get(User, uid)
        if u:
            db.delete(u)
        db.commit()
        db.close()
