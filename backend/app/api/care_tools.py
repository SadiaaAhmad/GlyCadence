from datetime import datetime, timezone
from typing import Annotated, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.specialists import (
    compute_idf_dar_risk,
    run_dose_diary_agent,
    run_kindred_agent,
    run_plate_agent,
    run_rhythm_agent,
    run_roza_guide_agent,
    run_visit_notes_agent,
)
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import (
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    MedicationStock,
    PatientPreferences,
    User,
    WellbeingRecord,
)

router = APIRouter(prefix="/patients/{patient_id}", tags=["Care Tools"])


class MedLogRequest(BaseModel):
    medication_id: str
    status: Literal["taken", "delayed", "missed", "skipped"] = "taken"
    notes: str | None = None


class MedStockUpdateRequest(BaseModel):
    medication_id: str
    units_on_hand: float = Field(ge=0.0, le=1000.0)


class CheckinCreateRequest(BaseModel):
    stress_score: int = Field(ge=1, le=5)
    fatigue_score: int = Field(ge=1, le=5)
    sleep_hours: float = Field(ge=0.0, le=24.0)
    sleep_quality: int = Field(ge=1, le=5)
    illness_flag: bool = False
    mood_notes: str | None = Field(default=None, max_length=500)


class DDS2Request(BaseModel):
    feeling_overwhelmed_1_to_6: int = Field(ge=1, le=6)
    failing_routine_1_to_6: int = Field(ge=1, le=6)


class FastingRiskCheckRequest(BaseModel):
    egfr: float | None = Field(default=None, ge=5.0, le=150.0)
    pregnant: bool = False
    extra_recent_hypos: int = Field(default=0, ge=0, le=20)


class PreferencesUpdateRequest(BaseModel):
    vegetarian: bool | None = None
    budget_tier: Literal["low", "medium", "high"] | None = None
    city: str | None = Field(default=None, max_length=64)
    gentle_mode: bool | None = None
    target_low_mg_dl: float | None = Field(default=None, ge=55.0, le=110.0)
    target_high_mg_dl: float | None = Field(default=None, ge=120.0, le=260.0)
    emergency_contact_name: str | None = Field(default=None, max_length=128)
    emergency_contact_phone: str | None = Field(default=None, max_length=64)


def _load_core(db: Session, patient_id: uuid.UUID):
    readings = list(
        db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == patient_id).order_by(GlucoseReading.recorded_at.asc())).all()
    )
    meals = list(
        db.scalars(select(Meal).where(Meal.patient_id == patient_id).order_by(Meal.logged_at.desc())).all()
    )
    meds = list(
        db.scalars(select(Medication).where(Medication.patient_id == patient_id, Medication.is_active.is_(True))).all()
    )
    med_events = list(
        db.scalars(select(MedicationEvent).where(MedicationEvent.patient_id == patient_id).order_by(MedicationEvent.event_time.desc())).all()
    )
    wellbeing = list(
        db.scalars(select(WellbeingRecord).where(WellbeingRecord.patient_id == patient_id).order_by(WellbeingRecord.logged_at.desc())).all()
    )
    return readings, meals, meds, med_events, wellbeing


@router.get("/overview")
def get_today_overview(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    readings, meals, meds, med_events, wellbeing = _load_core(db, patient.id)
    rhy = run_rhythm_agent(db, patient, readings)
    plt = run_plate_agent(db, patient, readings, meals, meds)
    dose = run_dose_diary_agent(db, patient, meds, med_events)
    kin = run_kindred_agent(db, patient, readings, wellbeing)

    rhy_card = next((c for c in rhy.get("cards", []) if c.get("type") == "glucose_summary_card"), {})
    meal_cards = [c for c in plt.get("cards", []) if c.get("type") == "meal_card"]

    greeting_line = (
        rhy["findings"][1]["rendered_text"]
        if len(rhy.get("findings", [])) > 1
        else (rhy["findings"][0]["rendered_text"] if rhy.get("findings") else "Welcome back to GlyCadence.")
    )
    return {
        "patient_id": str(patient.id),
        "display_name": patient.display_name,
        "cohort_type": patient.cohort_type,
        "greeting_line": greeting_line,
        "hero": rhy_card,
        "next_up": [
            {
                "slot": "Next Meal",
                "title": meal_cards[0]["name"] if meal_cards else "Balanced desi lunch",
                "window": "1:00 PM – 2:00 PM",
                "recipe_id": meal_cards[0]["recipe_id"] if meal_cards else None,
            },
            {
                "slot": "Next Medicine",
                "title": meds[0].medication_name if meds else "Daily medicines",
                "window": meds[0].prescribed_schedule if meds else "With meal",
            },
            {
                "slot": "Wellbeing",
                "title": "20-second check-in",
                "window": f"{len(wellbeing)} day(s) logged",
            },
        ],
        "featured_suggestion": plt["findings"][0]["rendered_text"] if plt.get("findings") else "",
        "featured_recipe": meal_cards[0] if meal_cards else None,
        "wellbeing_note": kin["findings"][0]["rendered_text"] if kin.get("findings") else "",
        "med_note": dose["findings"][0]["rendered_text"] if dose.get("findings") else "",
    }


@router.get("/medicines/summary")
def get_medicines_summary(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id, Medication.is_active.is_(True))).all())
    events = list(db.scalars(select(MedicationEvent).where(MedicationEvent.patient_id == patient.id).order_by(MedicationEvent.event_time.desc()).limit(30)).all())
    stocks = {
        s.medication_id: s
        for s in db.scalars(select(MedicationStock).where(MedicationStock.medication_id.in_([m.id for m in meds]))).all()
    } if meds else {}

    dose_res = run_dose_diary_agent(db, patient, meds, events)
    plain_explanations = {
        "Biguanide": "Helps your body use its own insulin better; usually taken with meals to ease stomach comfort.",
        "Sulfonylurea": "Helps release more insulin; can lower sugar further if a meal is delayed or skipped.",
        "Basal Insulin": "Provides steady background insulin across 24 hours; monitor overnight & fasting levels.",
    }
    med_items = []
    for m in meds:
        st = stocks.get(m.id)
        days_left = int(st.units_on_hand // st.daily_units) if st else None
        med_items.append(
            {
                "id": str(m.id),
                "name": m.medication_name,
                "drug_class": m.drug_class,
                "dose": m.recorded_dose,
                "schedule": m.prescribed_schedule,
                "plain_explanation": plain_explanations.get(m.drug_class or "", "Prescribed by your clinician; ask them before any schedule or dose change."),
                "hypo_risk": any(k in (m.drug_class or "").lower() or k in m.medication_name.lower() for k in ("sulfonylurea", "gliclazide", "insulin")),
                "units_on_hand": st.units_on_hand if st else None,
                "days_left": days_left,
            }
        )
    return {
        "patient_id": str(patient.id),
        "medications": med_items,
        "recent_events": [
            {
                "id": str(e.id),
                "medication_id": str(e.medication_id) if e.medication_id else None,
                "event_time": e.event_time.isoformat(),
                "status": e.status,
                "notes": e.notes,
            }
            for e in events[:12]
        ],
        "agent_summary": dose_res,
    }


@router.post("/medicines/log")
def log_medicine_dose(
    patient_id: uuid.UUID,
    payload: MedLogRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    med = db.scalar(select(Medication).where(Medication.id == uuid.UUID(payload.medication_id), Medication.patient_id == patient.id))
    if med is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found")
    ev = MedicationEvent(
        id=uuid.uuid4(),
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        medication_id=med.id,
        event_time=datetime.now(timezone.utc),
        status=payload.status,
        event_source="patient_log",
        notes=payload.notes,
        source_dataset="app_user",
    )
    db.add(ev)
    if payload.status == "taken":
        st = db.scalar(select(MedicationStock).where(MedicationStock.medication_id == med.id))
        if st and st.units_on_hand > 0:
            st.units_on_hand = max(0.0, st.units_on_hand - 1.0)
            st.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "logged", "event_id": str(ev.id)}


@router.get("/wellbeing/summary")
def get_wellbeing_summary(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    readings, _, _, _, wellbeing = _load_core(db, patient.id)
    kin = run_kindred_agent(db, patient, readings, wellbeing)
    return {
        "patient_id": str(patient.id),
        "checkins": [
            {
                "id": str(w.id),
                "logged_at": w.logged_at.isoformat(),
                "stress_score": w.stress_score,
                "fatigue_score": w.fatigue_score,
                "sleep_hours": w.sleep_hours,
                "sleep_quality": w.sleep_quality,
                "illness_flag": w.illness_flag,
                "mood_notes": w.mood_notes,
            }
            for w in wellbeing[:14]
        ],
        "agent_summary": kin,
    }


@router.post("/wellbeing/checkins")
def create_wellbeing_checkin(
    patient_id: uuid.UUID,
    payload: CheckinCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    rec = WellbeingRecord(
        id=uuid.uuid4(),
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        logged_at=datetime.now(timezone.utc),
        stress_score=payload.stress_score,
        fatigue_score=payload.fatigue_score,
        sleep_hours=payload.sleep_hours,
        sleep_quality=payload.sleep_quality,
        illness_flag=payload.illness_flag,
        mood_notes=payload.mood_notes,
        source_dataset="app_user",
    )
    db.add(rec)
    db.commit()
    return {"status": "saved", "id": str(rec.id)}


@router.post("/wellbeing/dds2")
def score_dds2(
    patient_id: uuid.UUID,
    payload: DDS2Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_patient_access(patient_id, current_user, db, write=False)
    avg_score = round((payload.feeling_overwhelmed_1_to_6 + payload.failing_routine_1_to_6) / 2.0, 2)
    elevated = avg_score >= 3.0
    return {
        "average_score": avg_score,
        "elevated_distress": elevated,
        "message": (
            "Your score suggests managing diabetes feels heavy right now. Switching on Gentle Mode can reduce alerts, and bringing this up with your doctor may help."
            if elevated
            else "Your current distress score is in the lower range. Keep going at a pace that feels sustainable."
        ),
    }


@router.get("/fasting/plan")
def get_ramadan_plan(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    readings, _, meds, _, _ = _load_core(db, patient.id)
    roza = run_roza_guide_agent(db, patient, readings, meds)
    return {"patient_id": str(patient.id), "roza": roza}


@router.post("/fasting/risk-check")
def post_fasting_risk_check(
    patient_id: uuid.UUID,
    payload: FastingRiskCheckRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    readings, _, meds, _, _ = _load_core(db, patient.id)
    uses_insulin = any("insulin" in (m.drug_class or "").lower() or "insulin" in m.medication_name.lower() for m in meds)
    uses_sulfo = any("sulfonylurea" in (m.drug_class or "").lower() or "gliclazide" in m.medication_name.lower() for m in meds)
    hypo_days = len({r.recorded_at.date() for r in readings if r.glucose_mg_dl < 70.0}) + payload.extra_recent_hypos
    return compute_idf_dar_risk(
        diabetes_type=patient.diabetes_type,
        uses_insulin=uses_insulin,
        uses_sulfonylurea=uses_sulfo,
        recent_hypo_count=hypo_days,
        egfr=payload.egfr,
        pregnant=payload.pregnant,
    )


@router.get("/preferences")
def get_preferences(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    if prefs is None:
        prefs = PatientPreferences(id=uuid.uuid4(), patient_id=patient.id, cohort_type=patient.cohort_type)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return {
        "patient_id": str(patient.id),
        "vegetarian": prefs.vegetarian,
        "budget_tier": prefs.budget_tier,
        "city": prefs.city,
        "gentle_mode": prefs.gentle_mode,
        "target_low_mg_dl": prefs.target_low_mg_dl,
        "target_high_mg_dl": prefs.target_high_mg_dl,
        "emergency_contact_name": prefs.emergency_contact_name,
        "emergency_contact_phone": prefs.emergency_contact_phone,
    }


@router.put("/preferences")
def update_preferences(
    patient_id: uuid.UUID,
    payload: PreferencesUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    if prefs is None:
        prefs = PatientPreferences(id=uuid.uuid4(), patient_id=patient.id, cohort_type=patient.cohort_type)
        db.add(prefs)
    if payload.vegetarian is not None:
        prefs.vegetarian = payload.vegetarian
    if payload.budget_tier is not None:
        prefs.budget_tier = payload.budget_tier
    if payload.city is not None:
        prefs.city = payload.city
    if payload.gentle_mode is not None:
        prefs.gentle_mode = payload.gentle_mode
    if payload.target_low_mg_dl is not None:
        prefs.target_low_mg_dl = payload.target_low_mg_dl
    if payload.target_high_mg_dl is not None:
        prefs.target_high_mg_dl = payload.target_high_mg_dl
    if payload.emergency_contact_name is not None:
        prefs.emergency_contact_name = payload.emergency_contact_name
    if payload.emergency_contact_phone is not None:
        prefs.emergency_contact_phone = payload.emergency_contact_phone
    prefs.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_preferences(patient_id, current_user, db)


@router.get("/visit-report", response_model=None)
def get_visit_report(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    format: str = Query(default="json"),
):
    patient = require_patient_access(patient_id, current_user, db, write=False)
    readings, meals, meds, med_events, wellbeing = _load_core(db, patient.id)
    rhy = run_rhythm_agent(db, patient, readings)
    plt = run_plate_agent(db, patient, readings, meals, meds)
    dose = run_dose_diary_agent(db, patient, meds, med_events)
    kin = run_kindred_agent(db, patient, readings, wellbeing)
    roza = run_roza_guide_agent(db, patient, readings, meds)
    vn = run_visit_notes_agent(rhy, plt, dose, kin, roza)

    questions = next((c["questions"] for c in vn.get("cards", []) if c.get("type") == "visit_questions_card"), [])
    rhy_card = next((c for c in rhy.get("cards", []) if c.get("type") == "glucose_summary_card"), {})

    payload = {
        "patient_id": str(patient.id),
        "display_name": patient.display_name,
        "personal_summary": [f["rendered_text"] for f in rhy.get("findings", [])[:4]],
        "metrics": rhy_card,
        "medications": [f"{m.medication_name} {m.recorded_dose or ''} ({m.prescribed_schedule or ''})" for m in meds],
        "questions": questions,
        "clinician_appendix": {
            "cohort_type": patient.cohort_type,
            "source_dataset": patient.source_dataset,
            "data_used": {
                "rhythm": rhy["data_used"],
                "plate": plt["data_used"],
                "dose_diary": dose["data_used"],
                "kindred": kin["data_used"],
            },
        },
    }

    if format == "html":
        q_html = "".join(f"<li><strong>{q['question']}</strong><br/><small>Why: {q['why']}</small></li>" for q in questions)
        m_html = "".join(f"<li>{m}</li>" for m in payload["medications"])
        s_html = "".join(f"<li>{s}</li>" for s in payload["personal_summary"])
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"/><title>GlyCadence Visit Report — {patient.display_name}</title>
<style>body{{font-family:Inter,system-ui,sans-serif;max-width:760px;margin:32px auto;color:#2B1E2F;line-height:1.5}}
h1{{color:#2B1E2F;border-bottom:2px solid #F2A93B;padding-bottom:8px}}ul{{padding-left:20px}}li{{margin-bottom:8px}}
.box{{background:#FBF6EF;border:1px solid #E9DCCB;border-radius:12px;padding:16px;margin:16px 0}}</style></head>
<body><h1>GlyCadence Clinician Visit Report</h1><p><strong>Patient:</strong> {patient.display_name}</p>
<div class="box"><h2>Recent Glucose Summary</h2><ul>{s_html}</ul></div>
<div class="box"><h2>Active Medicines</h2><ul>{m_html}</ul></div>
<div class="box"><h2>Questions for This Visit</h2><ol>{q_html}</ol></div>
<p><small>Cohort: {patient.cohort_type} | Source: {patient.source_dataset} | Non-diagnostic summary</small></p></body></html>"""
        return HTMLResponse(content=html)

    return payload
