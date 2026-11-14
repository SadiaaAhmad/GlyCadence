import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models.core import Patient, User
from app.schemas.patients import POLICY_DEFAULT_DAYS, PatientCreate, PatientOut, PatientUpdate

router = APIRouter(prefix="/patients", tags=["Patients"])


def _compute_retention_window(
    retention_policy: str, retention_days: int | None, reference_time: datetime
) -> tuple[int | None, datetime | None]:
    if retention_policy in {"indefinite_until_revoked", "research_archive"}:
        return None, None
    resolved_days = retention_days or POLICY_DEFAULT_DAYS.get(retention_policy)
    if resolved_days is not None:
        return resolved_days, reference_time + timedelta(days=resolved_days)
    return None, None


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def onboard_patient(
    payload: PatientCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Patient:
    now = datetime.now(timezone.utc)
    resolved_days, expires_at = _compute_retention_window(
        payload.retention_policy, payload.retention_days, now
    )
    patient = Patient(
        user_id=current_user.id,
        cohort_type="app_user",
        display_name=payload.display_name,
        age=payload.age,
        sex=payload.sex,
        diabetes_type=payload.diabetes_type,
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        dietary_restrictions=payload.dietary_restrictions,
        cultural_cuisine_pref=payload.cultural_cuisine_pref,
        consent_granted=payload.consent_granted,
        consent_version=payload.consent_version,
        consent_granted_at=now,
        retention_policy=payload.retention_policy,
        retention_days=resolved_days,
        retention_expires_at=expires_at,
        source_dataset="app_user",
    )
    db.add(patient)
    db.flush()
    record_audit_event(
        db,
        action="create_log",
        resource_type="patient",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "retention_policy": patient.retention_policy,
            "actor_role": current_user.role,
        },
    )
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Patient:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    record_audit_event(
        db,
        action="read_records",
        resource_type="patient",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
        },
    )
    db.commit()
    return patient


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Patient:
    patient = require_patient_access(patient_id, current_user, db, write=True)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(patient, field, value)

    if "retention_policy" in updates or "retention_days" in updates:
        resolved_days, expires_at = _compute_retention_window(
            patient.retention_policy,
            patient.retention_days,
            patient.consent_granted_at or datetime.now(timezone.utc),
        )
        patient.retention_days = resolved_days
        patient.retention_expires_at = expires_at

    record_audit_event(
        db,
        action="create_log",
        resource_type="patient",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "retention_policy": patient.retention_policy,
            "actor_role": current_user.role,
        },
    )
    db.commit()
    db.refresh(patient)
    return patient
