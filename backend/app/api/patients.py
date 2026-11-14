import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models.core import Patient, User
from app.schemas.patients import PatientCreate, PatientOut, PatientUpdate

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def onboard_patient(
    payload: PatientCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Patient:
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
        consent_granted_at=datetime.now(timezone.utc),
        retention_policy=payload.retention_policy,
        retention_days=payload.retention_days,
        retention_expires_at=(
            datetime.now(timezone.utc) + timedelta(days=payload.retention_days)
            if payload.retention_policy == "365_days" and payload.retention_days is not None
            else None
        ),
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

    record_audit_event(
        db,
        action="create_log",
        resource_type="patient",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(patient.id),
        request=request,
    )
    db.commit()
    db.refresh(patient)
    return patient
