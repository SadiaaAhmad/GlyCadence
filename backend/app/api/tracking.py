import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models.core import User
from app.models.observations import (
    ActivityRecord,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    WellbeingRecord,
)
from app.schemas.tracking import (
    ActivityCreate,
    ActivityOut,
    GlucoseCreate,
    GlucoseOut,
    MealCreate,
    MealOut,
    MedicationCreate,
    MedicationEventCreate,
    MedicationEventOut,
    MedicationOut,
    PaginatedResponse,
    TimelineEntry,
    WellbeingCreate,
    WellbeingOut,
    ensure_utc,
)

router = APIRouter(prefix="/patients/{patient_id}", tags=["Tracking"])


def _validate_date_range(start: datetime | None, end: datetime | None) -> tuple[datetime | None, datetime | None]:
    utc_start = ensure_utc(start) if start is not None else None
    utc_end = ensure_utc(end) if end is not None else None
    if utc_start is not None and utc_end is not None and utc_start > utc_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_date_range", "message": "'start' must be <= 'end'."},
        )
    return utc_start, utc_end


# --- Glucose ---


@router.post("/glucose", response_model=GlucoseOut, status_code=status.HTTP_201_CREATED)
def create_glucose_reading(
    patient_id: uuid.UUID,
    payload: GlucoseCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GlucoseReading:
    patient = require_patient_access(patient_id, current_user, db, write=True)

    if idempotency_key:
        existing = db.execute(
            select(GlucoseReading).where(
                GlucoseReading.patient_id == patient.id,
                GlucoseReading.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    glucose_mg_dl = (
        payload.raw_value if payload.raw_unit == "mg/dL" else round(payload.raw_value * 18.0182, 2)
    )
    # Explicit provenance for manual user entries ("as entered by the user, not interpolated"):
    # Non-CGM point readings (fasting, pre_meal, post_meal, bedtime, cbg) are never native CGM.
    # For manual CGM entries, 'native' denotes "as entered directly by the user, not interpolated".
    if payload.reading_type == "cgm":
        explicit_provenance = payload.observation_provenance or "native"
    else:
        if payload.observation_provenance == "native":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "non_cgm_cannot_be_native_cgm",
                    "message": "Non-CGM point readings cannot be marked as native CGM.",
                },
            )
        explicit_provenance = payload.observation_provenance or "unknown"

    row = GlucoseReading(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        recorded_at=payload.recorded_at,
        glucose_mg_dl=glucose_mg_dl,
        raw_value=payload.raw_value,
        raw_unit=payload.raw_unit,
        reading_type=payload.reading_type,
        device_id=payload.device_id,
        sampling_interval_min=payload.sampling_interval_min,
        observation_provenance=explicit_provenance,
        source_dataset="app_user",
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="glucose_reading",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/glucose", response_model=PaginatedResponse)
def list_glucose_readings(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    reading_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    utc_start, utc_end = _validate_date_range(start, end)

    stmt = select(GlucoseReading).where(GlucoseReading.patient_id == patient.id)
    count_stmt = select(func.count(GlucoseReading.id)).where(GlucoseReading.patient_id == patient.id)

    if utc_start is not None:
        stmt = stmt.where(GlucoseReading.recorded_at >= utc_start)
        count_stmt = count_stmt.where(GlucoseReading.recorded_at >= utc_start)
    if utc_end is not None:
        stmt = stmt.where(GlucoseReading.recorded_at <= utc_end)
        count_stmt = count_stmt.where(GlucoseReading.recorded_at <= utc_end)
    if reading_type is not None:
        stmt = stmt.where(GlucoseReading.reading_type == reading_type)
        count_stmt = count_stmt.where(GlucoseReading.reading_type == reading_type)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(GlucoseReading.recorded_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    record_audit_event(
        db,
        action="read_records",
        resource_type="glucose_readings",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return PaginatedResponse(
        items=[GlucoseOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Meals ---


@router.post("/meals", response_model=MealOut, status_code=status.HTTP_201_CREATED)
def create_meal(
    patient_id: uuid.UUID,
    payload: MealCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Meal:
    patient = require_patient_access(patient_id, current_user, db, write=True)

    if idempotency_key:
        existing = db.execute(
            select(Meal).where(Meal.patient_id == patient.id, Meal.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    row = Meal(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        logged_at=payload.logged_at,
        meal_type=payload.meal_type,
        description=payload.description,
        ingredients=payload.ingredients,
        calories=payload.calories,
        carbs_g=payload.carbs_g,
        protein_g=payload.protein_g,
        fat_g=payload.fat_g,
        fiber_g=payload.fiber_g,
        cultural_tag=payload.cultural_tag,
        source_dataset="app_user",
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="meal",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/meals", response_model=PaginatedResponse)
def list_meals(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    utc_start, utc_end = _validate_date_range(start, end)

    stmt = select(Meal).where(Meal.patient_id == patient.id)
    count_stmt = select(func.count(Meal.id)).where(Meal.patient_id == patient.id)
    if utc_start is not None:
        stmt = stmt.where(Meal.logged_at >= utc_start)
        count_stmt = count_stmt.where(Meal.logged_at >= utc_start)
    if utc_end is not None:
        stmt = stmt.where(Meal.logged_at <= utc_end)
        count_stmt = count_stmt.where(Meal.logged_at <= utc_end)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(stmt.order_by(Meal.logged_at.desc()).offset(offset).limit(limit)).scalars().all()

    record_audit_event(
        db,
        action="read_records",
        resource_type="meals",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return PaginatedResponse(
        items=[MealOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Medications & Medication Events ---


@router.post("/medications", response_model=MedicationOut, status_code=status.HTTP_201_CREATED)
def create_medication(
    patient_id: uuid.UUID,
    payload: MedicationCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Medication:
    patient = require_patient_access(patient_id, current_user, db, write=True)
    row = Medication(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        medication_name=payload.medication_name,
        drug_class=payload.drug_class,
        recorded_dose=payload.recorded_dose,
        prescribed_schedule=payload.prescribed_schedule,
        is_active=payload.is_active,
        start_date=payload.start_date,
        end_date=payload.end_date,
        source_dataset="app_user",
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="medication",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/medications/events", response_model=MedicationEventOut, status_code=status.HTTP_201_CREATED)
def create_medication_event(
    patient_id: uuid.UUID,
    payload: MedicationEventCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MedicationEvent:
    patient = require_patient_access(patient_id, current_user, db, write=True)

    if idempotency_key:
        existing = db.execute(
            select(MedicationEvent).where(
                MedicationEvent.patient_id == patient.id,
                MedicationEvent.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    if payload.medication_id is not None:
        med = db.execute(
            select(Medication).where(
                Medication.id == payload.medication_id,
                Medication.patient_id == patient.id,
                Medication.cohort_type == patient.cohort_type,
            )
        ).scalar_one_or_none()
        if med is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "medication_not_found", "message": "Medication regimen not found for this patient."},
            )

    row = MedicationEvent(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        medication_id=payload.medication_id,
        event_time=payload.event_time,
        status=payload.status,
        event_source=payload.event_source,
        notes=payload.notes,
        source_dataset="app_user",
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="medication_event",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/medications", response_model=dict)
def list_medications_and_events(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    regimens = db.execute(
        select(Medication).where(Medication.patient_id == patient.id).order_by(Medication.medication_name)
    ).scalars().all()
    total_events = db.execute(
        select(func.count(MedicationEvent.id)).where(MedicationEvent.patient_id == patient.id)
    ).scalar_one()
    events = db.execute(
        select(MedicationEvent)
        .where(MedicationEvent.patient_id == patient.id)
        .order_by(MedicationEvent.event_time.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    record_audit_event(
        db,
        action="read_records",
        resource_type="medications",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return {
        "regimens": [MedicationOut.model_validate(r) for r in regimens],
        "events": PaginatedResponse(
            items=[MedicationEventOut.model_validate(e) for e in events],
            total=total_events,
            limit=limit,
            offset=offset,
        ),
    }


# --- Wellbeing ---


@router.post("/wellbeing", response_model=WellbeingOut, status_code=status.HTTP_201_CREATED)
def create_wellbeing_record(
    patient_id: uuid.UUID,
    payload: WellbeingCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WellbeingRecord:
    patient = require_patient_access(patient_id, current_user, db, write=True)

    if idempotency_key:
        existing = db.execute(
            select(WellbeingRecord).where(
                WellbeingRecord.patient_id == patient.id,
                WellbeingRecord.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    row = WellbeingRecord(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        logged_at=payload.logged_at,
        stress_score=payload.stress_score,
        fatigue_score=payload.fatigue_score,
        sleep_hours=payload.sleep_hours,
        sleep_quality=payload.sleep_quality,
        mood_notes=payload.mood_notes,
        illness_flag=payload.illness_flag,
        source_dataset="app_user",
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="wellbeing_record",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/wellbeing", response_model=PaginatedResponse)
def list_wellbeing_records(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    utc_start, utc_end = _validate_date_range(start, end)

    stmt = select(WellbeingRecord).where(WellbeingRecord.patient_id == patient.id)
    count_stmt = select(func.count(WellbeingRecord.id)).where(WellbeingRecord.patient_id == patient.id)
    if utc_start is not None:
        stmt = stmt.where(WellbeingRecord.logged_at >= utc_start)
        count_stmt = count_stmt.where(WellbeingRecord.logged_at >= utc_start)
    if utc_end is not None:
        stmt = stmt.where(WellbeingRecord.logged_at <= utc_end)
        count_stmt = count_stmt.where(WellbeingRecord.logged_at <= utc_end)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(WellbeingRecord.logged_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    record_audit_event(
        db,
        action="read_records",
        resource_type="wellbeing_records",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return PaginatedResponse(
        items=[WellbeingOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Activity (Dedicated Endpoints) ---


@router.post("/activity", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity_record(
    patient_id: uuid.UUID,
    payload: ActivityCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ActivityRecord:
    patient = require_patient_access(patient_id, current_user, db, write=True)

    if idempotency_key:
        existing = db.execute(
            select(ActivityRecord).where(
                ActivityRecord.patient_id == patient.id,
                ActivityRecord.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    row = ActivityRecord(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        recorded_at=payload.recorded_at,
        steps=payload.steps,
        active_minutes=payload.active_minutes,
        heart_rate_bpm=payload.heart_rate_bpm,
        activity_type=payload.activity_type,
        intensity=payload.intensity,
        source_dataset="app_user",
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="activity_record",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(row.id),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/activity", response_model=PaginatedResponse)
def list_activity_records(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    utc_start, utc_end = _validate_date_range(start, end)

    stmt = select(ActivityRecord).where(ActivityRecord.patient_id == patient.id)
    count_stmt = select(func.count(ActivityRecord.id)).where(ActivityRecord.patient_id == patient.id)
    if utc_start is not None:
        stmt = stmt.where(ActivityRecord.recorded_at >= utc_start)
        count_stmt = count_stmt.where(ActivityRecord.recorded_at >= utc_start)
    if utc_end is not None:
        stmt = stmt.where(ActivityRecord.recorded_at <= utc_end)
        count_stmt = count_stmt.where(ActivityRecord.recorded_at <= utc_end)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(ActivityRecord.recorded_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    record_audit_event(
        db,
        action="read_records",
        resource_type="activity_records",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return PaginatedResponse(
        items=[ActivityOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Unified Timeline ---


@router.get("/timeline", response_model=PaginatedResponse)
def get_patient_timeline(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    utc_start, utc_end = _validate_date_range(start, end)

    entries: list[TimelineEntry] = []

    g_stmt = select(GlucoseReading).where(GlucoseReading.patient_id == patient.id)
    m_stmt = select(Meal).where(Meal.patient_id == patient.id)
    me_stmt = select(MedicationEvent).where(MedicationEvent.patient_id == patient.id)
    w_stmt = select(WellbeingRecord).where(WellbeingRecord.patient_id == patient.id)
    a_stmt = select(ActivityRecord).where(ActivityRecord.patient_id == patient.id)

    if utc_start is not None:
        g_stmt = g_stmt.where(GlucoseReading.recorded_at >= utc_start)
        m_stmt = m_stmt.where(Meal.logged_at >= utc_start)
        me_stmt = me_stmt.where(MedicationEvent.event_time >= utc_start)
        w_stmt = w_stmt.where(WellbeingRecord.logged_at >= utc_start)
        a_stmt = a_stmt.where(ActivityRecord.recorded_at >= utc_start)

    if utc_end is not None:
        g_stmt = g_stmt.where(GlucoseReading.recorded_at <= utc_end)
        m_stmt = m_stmt.where(Meal.logged_at <= utc_end)
        me_stmt = me_stmt.where(MedicationEvent.event_time <= utc_end)
        w_stmt = w_stmt.where(WellbeingRecord.logged_at <= utc_end)
        a_stmt = a_stmt.where(ActivityRecord.recorded_at <= utc_end)

    for g in db.execute(g_stmt).scalars().all():
        entries.append(
            TimelineEntry(
                id=g.id,
                record_type="glucose",
                timestamp=g.recorded_at,
                summary=f"{g.glucose_mg_dl} mg/dL ({g.reading_type})",
                payload=GlucoseOut.model_validate(g).model_dump(mode="json"),
            )
        )
    for m in db.execute(m_stmt).scalars().all():
        entries.append(
            TimelineEntry(
                id=m.id,
                record_type="meal",
                timestamp=m.logged_at,
                summary=f"{m.meal_type}: {m.description}",
                payload=MealOut.model_validate(m).model_dump(mode="json"),
            )
        )
    for me in db.execute(me_stmt).scalars().all():
        entries.append(
            TimelineEntry(
                id=me.id,
                record_type="medication_event",
                timestamp=me.event_time,
                summary=f"Medication {me.status}",
                payload=MedicationEventOut.model_validate(me).model_dump(mode="json"),
            )
        )
    for w in db.execute(w_stmt).scalars().all():
        entries.append(
            TimelineEntry(
                id=w.id,
                record_type="wellbeing",
                timestamp=w.logged_at,
                summary=f"Wellbeing (stress={w.stress_score}, fatigue={w.fatigue_score}, illness={w.illness_flag})",
                payload=WellbeingOut.model_validate(w).model_dump(mode="json"),
            )
        )
    for a in db.execute(a_stmt).scalars().all():
        entries.append(
            TimelineEntry(
                id=a.id,
                record_type="activity",
                timestamp=a.recorded_at,
                summary=f"Activity ({a.activity_type or a.intensity})",
                payload=ActivityOut.model_validate(a).model_dump(mode="json"),
            )
        )

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    total = len(entries)
    paged = entries[offset : offset + limit]

    record_audit_event(
        db,
        action="read_records",
        resource_type="timeline",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        request=request,
    )
    db.commit()

    return PaginatedResponse(items=paged, total=total, limit=limit, offset=offset)
