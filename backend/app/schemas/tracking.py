import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware (ISO-8601 with offset or Z).")
    return dt.astimezone(timezone.utc)


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class GlucoseCreate(BaseModel):
    recorded_at: datetime
    raw_value: float = Field(gt=0, lt=1500)
    raw_unit: Literal["mg/dL", "mmol/L"] = "mg/dL"
    reading_type: Literal["cgm", "fasting", "pre_meal", "post_meal", "bedtime", "cbg"]
    device_id: str | None = Field(default=None, max_length=64)
    sampling_interval_min: int | None = Field(default=None, ge=1, le=1440)
    observation_provenance: Literal["native", "interpolated", "derived", "unknown"] | None = None

    @field_validator("recorded_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class GlucoseOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    recorded_at: datetime
    glucose_mg_dl: float
    raw_value: float
    raw_unit: str
    reading_type: str
    device_id: str | None
    sampling_interval_min: int | None
    observation_provenance: str
    source_dataset: str

    model_config = {"from_attributes": True}


class MealCreate(BaseModel):
    logged_at: datetime
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "unknown"] = "unknown"
    description: str = Field(min_length=1, max_length=1000)
    ingredients: list[str] = Field(default_factory=list)
    calories: float | None = Field(default=None, ge=0, le=5000)
    carbs_g: float | None = Field(default=None, ge=0, le=1000)
    protein_g: float | None = Field(default=None, ge=0, le=500)
    fat_g: float | None = Field(default=None, ge=0, le=500)
    fiber_g: float | None = Field(default=None, ge=0, le=300)
    cultural_tag: str | None = Field(default=None, max_length=64)

    @field_validator("logged_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class MealOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    logged_at: datetime
    meal_type: str
    description: str
    ingredients: list[str]
    calories: float | None
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    fiber_g: float | None
    cultural_tag: str | None
    source_dataset: str

    model_config = {"from_attributes": True}


class MedicationCreate(BaseModel):
    medication_name: str = Field(min_length=1, max_length=255)
    drug_class: str | None = Field(default=None, max_length=128)
    recorded_dose: str | None = Field(default=None, max_length=128)
    prescribed_schedule: str | None = Field(default=None, max_length=128)
    is_active: bool = True
    start_date: date | None = None
    end_date: date | None = None


class MedicationOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    medication_name: str
    drug_class: str | None
    recorded_dose: str | None
    prescribed_schedule: str | None
    is_active: bool
    start_date: date | None
    end_date: date | None
    source_dataset: str

    model_config = {"from_attributes": True}


class MedicationEventCreate(BaseModel):
    medication_id: uuid.UUID | None = None
    event_time: datetime
    status: Literal["taken", "missed", "delayed", "unknown"]
    event_source: Literal["patient_log", "clinical_record", "unknown"] = "patient_log"
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("event_time")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class MedicationEventOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    medication_id: uuid.UUID | None
    event_time: datetime
    status: str
    event_source: str
    notes: str | None
    source_dataset: str

    model_config = {"from_attributes": True}


class WellbeingCreate(BaseModel):
    logged_at: datetime
    stress_score: int | None = Field(default=None, ge=1, le=5)
    fatigue_score: int | None = Field(default=None, ge=1, le=5)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    mood_notes: str | None = Field(default=None, max_length=1000)
    illness_flag: bool | None = None

    @field_validator("logged_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class WellbeingOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    logged_at: datetime
    stress_score: int | None
    fatigue_score: int | None
    sleep_hours: float | None
    sleep_quality: int | None
    mood_notes: str | None
    illness_flag: bool | None
    source_dataset: str

    model_config = {"from_attributes": True}


class ActivityCreate(BaseModel):
    recorded_at: datetime
    steps: int | None = Field(default=None, ge=0, le=200000)
    active_minutes: int | None = Field(default=None, ge=0, le=1440)
    heart_rate_bpm: float | None = Field(default=None, gt=20, le=250)
    activity_type: str | None = Field(default=None, max_length=64)
    intensity: Literal["low", "moderate", "vigorous", "unknown"] = "unknown"

    @field_validator("recorded_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ActivityOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    recorded_at: datetime
    steps: int | None
    active_minutes: int | None
    heart_rate_bpm: float | None
    activity_type: str | None
    intensity: str
    source_dataset: str

    model_config = {"from_attributes": True}


class TimelineEntry(BaseModel):
    id: uuid.UUID
    record_type: Literal["glucose", "meal", "medication_event", "wellbeing", "activity"]
    timestamp: datetime
    summary: str
    payload: dict[str, Any]
