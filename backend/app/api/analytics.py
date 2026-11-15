from datetime import datetime
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import (
    MultipleDevicesError,
    compute_glucose_drift,
    compute_glucose_summary,
    compute_medication_pattern_summary,
    evaluate_meal_responses,
)
from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import GlucoseReading, Meal, Medication, MedicationEvent, User
from app.schemas.analytics import (
    DriftSummaryOut,
    GlucoseSummaryOut,
    MealResponseItem,
    MedicationPatternSummaryOut,
)
from app.schemas.tracking import ensure_utc

router = APIRouter(prefix="/patients/{patient_id}/analytics", tags=["Analytics"])


def _validate_window(start: datetime | None, end: datetime | None) -> tuple[datetime | None, datetime | None]:
    s_utc = ensure_utc(start) if start is not None else None
    e_utc = ensure_utc(end) if end is not None else None
    if s_utc is not None and e_utc is not None and s_utc > e_utc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_date_range", "message": "start must be <= end"},
        )
    return s_utc, e_utc


@router.get("/summary", response_model=GlucoseSummaryOut)
def get_analytics_summary(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    native_only: bool = Query(default=True),
    include_non_native: bool = Query(default=False),
    device_id: str | None = Query(default=None),
) -> GlucoseSummaryOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    s_utc, e_utc = _validate_window(start, end)
    effective_native_only = False if include_non_native else native_only

    stmt = select(GlucoseReading).where(GlucoseReading.patient_id == patient.id)
    if s_utc is not None:
        stmt = stmt.where(GlucoseReading.recorded_at >= s_utc)
    if e_utc is not None:
        stmt = stmt.where(GlucoseReading.recorded_at <= e_utc)
    stmt = stmt.order_by(GlucoseReading.recorded_at.asc())
    readings = list(db.scalars(stmt).all())

    record_audit_event(
        db,
        action="read_records",
        resource_type="analytics_summary",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
            "native_only": effective_native_only,
            "device_id": device_id,
        },
    )
    db.commit()

    try:
        return compute_glucose_summary(
            readings,
            window_start=s_utc,
            window_end=e_utc,
            native_only=effective_native_only,
            device_id=device_id,
            timezone_name=patient.timezone,
        )
    except MultipleDevicesError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "multiple_devices_specify_device_id",
                "message": str(exc),
                "devices_present": exc.devices_present,
            },
        ) from exc


@router.get("/drift", response_model=DriftSummaryOut)
def get_analytics_drift(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    native_only: bool = Query(default=True),
    include_non_native: bool = Query(default=False),
    device_id: str | None = Query(default=None),
) -> DriftSummaryOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    s_utc, e_utc = _validate_window(start, end)
    effective_native_only = False if include_non_native else native_only

    stmt = select(GlucoseReading).where(GlucoseReading.patient_id == patient.id)
    if s_utc is not None:
        stmt = stmt.where(GlucoseReading.recorded_at >= s_utc)
    if e_utc is not None:
        stmt = stmt.where(GlucoseReading.recorded_at <= e_utc)
    stmt = stmt.order_by(GlucoseReading.recorded_at.asc())
    readings = list(db.scalars(stmt).all())

    record_audit_event(
        db,
        action="read_records",
        resource_type="analytics_drift",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
            "native_only": effective_native_only,
            "device_id": device_id,
        },
    )
    db.commit()

    try:
        return compute_glucose_drift(
            readings,
            native_only=effective_native_only,
            device_id=device_id,
        )
    except MultipleDevicesError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "multiple_devices_specify_device_id",
                "message": str(exc),
                "devices_present": exc.devices_present,
            },
        ) from exc


@router.get("/meal-responses", response_model=list[MealResponseItem])
def get_analytics_meal_responses(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    native_only: bool = Query(default=True),
    include_non_native: bool = Query(default=False),
    device_id: str | None = Query(default=None),
) -> list[MealResponseItem]:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    s_utc, e_utc = _validate_window(start, end)
    effective_native_only = False if include_non_native else native_only

    meal_stmt = select(Meal).where(Meal.patient_id == patient.id)
    if s_utc is not None:
        meal_stmt = meal_stmt.where(Meal.logged_at >= s_utc)
    if e_utc is not None:
        meal_stmt = meal_stmt.where(Meal.logged_at <= e_utc)
    meal_stmt = meal_stmt.order_by(Meal.logged_at.asc())
    meals = list(db.scalars(meal_stmt).all())

    glucose_stmt = (
        select(GlucoseReading)
        .where(GlucoseReading.patient_id == patient.id)
        .order_by(GlucoseReading.recorded_at.asc())
    )
    readings = list(db.scalars(glucose_stmt).all())

    record_audit_event(
        db,
        action="read_records",
        resource_type="analytics_meal_responses",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
            "native_only": effective_native_only,
            "device_id": device_id,
        },
    )
    db.commit()

    try:
        return evaluate_meal_responses(
            meals,
            readings,
            native_only=effective_native_only,
            device_id=device_id,
        )
    except MultipleDevicesError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "multiple_devices_specify_device_id",
                "message": str(exc),
                "devices_present": exc.devices_present,
            },
        ) from exc


@router.get("/medication-patterns", response_model=MedicationPatternSummaryOut)
def get_analytics_medication_patterns(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    native_only: bool = Query(default=True),
    include_non_native: bool = Query(default=False),
) -> MedicationPatternSummaryOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    effective_native_only = False if include_non_native else native_only

    meds = list(
        db.scalars(select(Medication).where(Medication.patient_id == patient.id)).all()
    )
    events = list(
        db.scalars(
            select(MedicationEvent)
            .where(MedicationEvent.patient_id == patient.id)
            .order_by(MedicationEvent.event_time.asc())
        ).all()
    )

    record_audit_event(
        db,
        action="read_records",
        resource_type="analytics_medication_patterns",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
            "native_only": effective_native_only,
        },
    )
    db.commit()

    return compute_medication_pattern_summary(meds, events, native_only=effective_native_only)
