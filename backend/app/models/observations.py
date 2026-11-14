import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClinicalRecord(Base):
    __tablename__ = "clinical_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_imports.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hba1c_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmi: Mapped[float | None] = mapped_column(Float, nullable=True)
    fasting_glucose_mg_dl: Mapped[float | None] = mapped_column(Float, nullable=True)
    egfr: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_labs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_clinical_records_patient_cohort",
            ondelete="CASCADE",
        ),
        Index("idx_clinical_patient_time", "patient_id", text("recorded_at DESC")),
    )


class GlucoseReading(Base):
    __tablename__ = "glucose_readings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_imports.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    glucose_mg_dl: Mapped[float] = mapped_column(Float, nullable=False)
    raw_value: Mapped[float] = mapped_column(Float, nullable=False)
    raw_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="mg/dL")
    reading_type: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sampling_interval_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_glucose_patient_cohort",
            ondelete="CASCADE",
        ),
        CheckConstraint("raw_unit IN ('mg/dL', 'mmol/L')", name="ck_glucose_raw_unit"),
        CheckConstraint(
            "reading_type IN ('cgm', 'fasting', 'pre_meal', 'post_meal', 'bedtime', 'cbg')",
            name="ck_glucose_reading_type",
        ),
        Index("idx_glucose_patient_time", "patient_id", text("recorded_at DESC")),
        Index(
            "uq_glucose_idempotency",
            "patient_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_imports.id", ondelete="SET NULL"), nullable=True
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ingredients: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    cultural_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_meals_patient_cohort",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'unknown')",
            name="ck_meals_meal_type",
        ),
        Index("idx_meals_patient_time", "patient_id", text("logged_at DESC")),
        Index(
            "uq_meals_idempotency",
            "patient_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_imports.id", ondelete="SET NULL"), nullable=True
    )
    medication_name: Mapped[str] = mapped_column(String(255), nullable=False)
    drug_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_dose: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prescribed_schedule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_medications_patient_cohort",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "patient_id", "cohort_type", name="uq_medications_id_patient_cohort"),
    )


class MedicationEvent(Base):
    __tablename__ = "medication_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    medication_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_source: Mapped[str] = mapped_column(String(32), nullable=False, default="patient_log")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_med_events_patient_cohort",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["medication_id", "patient_id", "cohort_type"],
            ["medications.id", "medications.patient_id", "medications.cohort_type"],
            name="fk_med_events_medication_scoped",
            ondelete="SET NULL (medication_id)",
        ),
        CheckConstraint(
            "status IN ('taken', 'missed', 'delayed', 'unknown')",
            name="ck_med_events_status",
        ),
        CheckConstraint(
            "event_source IN ('patient_log', 'clinical_record', 'unknown')",
            name="ck_med_events_source",
        ),
        Index("idx_med_events_patient_time", "patient_id", text("event_time DESC")),
        Index(
            "uq_med_events_idempotency",
            "patient_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class ActivityRecord(Base):
    __tablename__ = "activity_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heart_rate_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intensity: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_activity_patient_cohort",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "intensity IN ('low', 'moderate', 'vigorous', 'unknown')",
            name="ck_activity_intensity",
        ),
        Index("idx_activity_patient_time", "patient_id", text("recorded_at DESC")),
        Index(
            "uq_activity_idempotency",
            "patient_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class WellbeingRecord(Base):
    __tablename__ = "wellbeing_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stress_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fatigue_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    illness_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_wellbeing_patient_cohort",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "stress_score IS NULL OR (stress_score BETWEEN 1 AND 5)",
            name="ck_wellbeing_stress",
        ),
        CheckConstraint(
            "fatigue_score IS NULL OR (fatigue_score BETWEEN 1 AND 5)",
            name="ck_wellbeing_fatigue",
        ),
        CheckConstraint(
            "sleep_quality IS NULL OR (sleep_quality BETWEEN 1 AND 5)",
            name="ck_wellbeing_sleep_quality",
        ),
        Index("idx_wellbeing_patient_time", "patient_id", text("logged_at DESC")),
        Index(
            "uq_wellbeing_idempotency",
            "patient_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
