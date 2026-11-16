from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import GlucoseReading, Meal, Medication, MedicationEvent, PatientPreferences, User
from app.schemas.tracking import ensure_utc

router = APIRouter(prefix="/patients/{patient_id}/glucose", tags=["Glucose"])


class GlucoseReadingPointOut(BaseModel):
    recorded_at: datetime
    glucose_mg_dl: float
    provenance: str


class TimelineMarkerOut(BaseModel):
    id: str
    kind: str  # "meal" | "medication"
    timestamp: datetime
    label: str
    sublabel: str | None = None
    meal_id: str | None = None


class GlucoseReadingsResponse(BaseModel):
    patient_id: str
    target_low_mg_dl: float
    target_high_mg_dl: float
    latest_glucose_mg_dl: float | None
    latest_recorded_at: datetime | None
    trend_arrow: str
    source_summary: str
    readings: list[GlucoseReadingPointOut]
    markers: list[TimelineMarkerOut]


class DailyPatternHourOut(BaseModel):
    hour: int
    label: str
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    sample_count: int


class DailyPatternResponse(BaseModel):
    patient_id: str
    days: int
    target_low_mg_dl: float
    target_high_mg_dl: float
    hours: list[DailyPatternHourOut]


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 1)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac, 1)


def _compute_trend_arrow(readings: list[GlucoseReading]) -> str:
    if len(readings) < 2:
        return "steady"
    last = readings[-1]
    prev = readings[-4] if len(readings) >= 4 else readings[0]
    dt_min = max(1.0, (last.recorded_at - prev.recorded_at).total_seconds() / 60.0)
    rate_per_min = (last.glucose_mg_dl - prev.glucose_mg_dl) / dt_min
    if rate_per_min >= 2.0:
        return "up_fast"
    if rate_per_min >= 1.0:
        return "up"
    if rate_per_min <= -2.0:
        return "down_fast"
    if rate_per_min <= -1.0:
        return "down"
    return "steady"


@router.get("/readings", response_model=GlucoseReadingsResponse)
def get_glucose_readings(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=90),
    max_points: int = Query(default=480, ge=30, le=2000),
) -> GlucoseReadingsResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    target_low = prefs.target_low_mg_dl if prefs else 70.0
    target_high = prefs.target_high_mg_dl if prefs else 180.0

    # Determine effective window anchored to patient's latest reading if end is None
    latest_row = db.scalar(
        select(GlucoseReading)
        .where(GlucoseReading.patient_id == patient.id)
        .order_by(GlucoseReading.recorded_at.desc())
        .limit(1)
    )
    anchor_end = ensure_utc(end) if end else (latest_row.recorded_at if latest_row else datetime.now(timezone.utc))
    anchor_start = ensure_utc(start) if start else (anchor_end - timedelta(days=days))

    all_rows = list(
        db.scalars(
            select(GlucoseReading)
            .where(
                GlucoseReading.patient_id == patient.id,
                GlucoseReading.recorded_at >= anchor_start,
                GlucoseReading.recorded_at <= anchor_end,
            )
            .order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )

    if not all_rows:
        # Fallback to any glucose reading
        all_rows = list(
            db.scalars(
                select(GlucoseReading)
                .where(GlucoseReading.patient_id == patient.id)
                .order_by(GlucoseReading.recorded_at.asc())
                .limit(max_points)
            ).all()
        )

    trend = _compute_trend_arrow(all_rows)
    latest_val = all_rows[-1].glucose_mg_dl if all_rows else None
    latest_at = all_rows[-1].recorded_at if all_rows else None

    # Downsample evenly if > max_points while preserving endpoints
    if len(all_rows) > max_points:
        step = max(1, len(all_rows) // max_points)
        sampled = all_rows[::step]
        if sampled[-1].id != all_rows[-1].id:
            sampled.append(all_rows[-1])
    else:
        sampled = all_rows

    meals = list(
        db.scalars(
            select(Meal)
            .where(
                Meal.patient_id == patient.id,
                Meal.logged_at >= anchor_start,
                Meal.logged_at <= anchor_end,
            )
            .order_by(Meal.logged_at.asc())
        ).all()
    )
    meds_by_id = {
        m.id: m for m in db.scalars(select(Medication).where(Medication.patient_id == patient.id)).all()
    }
    med_events = list(
        db.scalars(
            select(MedicationEvent)
            .where(
                MedicationEvent.patient_id == patient.id,
                MedicationEvent.event_time >= anchor_start,
                MedicationEvent.event_time <= anchor_end,
            )
            .order_by(MedicationEvent.event_time.asc())
        ).all()
    )

    markers: list[TimelineMarkerOut] = []
    for m in meals:
        markers.append(
            TimelineMarkerOut(
                id=str(m.id),
                kind="meal",
                timestamp=m.logged_at,
                label=m.description,
                sublabel=m.meal_type,
                meal_id=str(m.id),
            )
        )
    for ev in med_events[:25]:
        med_obj = meds_by_id.get(ev.medication_id) if ev.medication_id else None
        markers.append(
            TimelineMarkerOut(
                id=str(ev.id),
                kind="medication",
                timestamp=ev.event_time,
                label=med_obj.medication_name if med_obj else "Medication",
                sublabel=ev.status,
            )
        )

    prov_set = {r.observation_provenance for r in all_rows}
    if prov_set == {"dataset_documented"}:
        src_summary = f"Based on {len(all_rows)} research study sensor readings"
    else:
        src_summary = f"Based on {len(all_rows)} sensor readings"

    return GlucoseReadingsResponse(
        patient_id=str(patient.id),
        target_low_mg_dl=target_low,
        target_high_mg_dl=target_high,
        latest_glucose_mg_dl=latest_val,
        latest_recorded_at=latest_at,
        trend_arrow=trend,
        source_summary=src_summary,
        readings=[
            GlucoseReadingPointOut(
                recorded_at=r.recorded_at,
                glucose_mg_dl=r.glucose_mg_dl,
                provenance=r.observation_provenance,
            )
            for r in sampled
        ],
        markers=markers,
    )


@router.get("/daily-pattern", response_model=DailyPatternResponse)
def get_daily_pattern(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(default=14, ge=3, le=60),
) -> DailyPatternResponse:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    target_low = prefs.target_low_mg_dl if prefs else 70.0
    target_high = prefs.target_high_mg_dl if prefs else 180.0

    latest_row = db.scalar(
        select(GlucoseReading)
        .where(GlucoseReading.patient_id == patient.id)
        .order_by(GlucoseReading.recorded_at.desc())
        .limit(1)
    )
    anchor_end = latest_row.recorded_at if latest_row else datetime.now(timezone.utc)
    anchor_start = anchor_end - timedelta(days=days)

    rows = list(
        db.scalars(
            select(GlucoseReading)
            .where(
                GlucoseReading.patient_id == patient.id,
                GlucoseReading.recorded_at >= anchor_start,
                GlucoseReading.recorded_at <= anchor_end,
            )
            .order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )

    buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    for r in rows:
        buckets[r.recorded_at.hour].append(r.glucose_mg_dl)

    hours: list[DailyPatternHourOut] = []
    for h in range(24):
        vals = sorted(buckets[h])
        label = f"{h:02d}:00"
        if vals:
            hours.append(
                DailyPatternHourOut(
                    hour=h,
                    label=label,
                    p10=_percentile(vals, 10),
                    p25=_percentile(vals, 25),
                    p50=round(median(vals), 1),
                    p75=_percentile(vals, 75),
                    p90=_percentile(vals, 90),
                    sample_count=len(vals),
                )
            )
        else:
            hours.append(
                DailyPatternHourOut(
                    hour=h, label=label, p10=0.0, p25=0.0, p50=0.0, p75=0.0, p90=0.0, sample_count=0
                )
            )

    return DailyPatternResponse(
        patient_id=str(patient.id),
        days=days,
        target_low_mg_dl=target_low,
        target_high_mg_dl=target_high,
        hours=hours,
    )
