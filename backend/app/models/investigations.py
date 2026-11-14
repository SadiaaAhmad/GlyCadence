import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_summary_patient: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_summary_clinician: Mapped[str | None] = mapped_column(Text, nullable=True)
    hypotheses: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    conflicting_evidence: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    missing_context: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    deterministic_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    safety_audit_notes: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_investigations_patient_cohort",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "patient_id", "cohort_type", name="uq_investigations_id_patient_cohort"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_investigations_status",
        ),
        CheckConstraint(
            "trigger_type IN ('drift_detected', 'user_query', 'scheduled', 'manual')",
            name="ck_investigations_trigger_type",
        ),
        Index(
            "idx_investigations_patient_status",
            "patient_id",
            "status",
            text("created_at DESC"),
        ),
    )


class AgentObservation(Base):
    __tablename__ = "agent_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    investigation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finding_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_items: Mapped[list] = mapped_column(JSONB, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missingness_pct: Mapped[float] = mapped_column(Float, nullable=False)
    deterministic_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty_notes: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_agent_obs_patient_cohort",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["investigation_id", "patient_id", "cohort_type"],
            ["investigations.id", "investigations.patient_id", "investigations.cohort_type"],
            name="fk_agent_obs_investigation_scoped",
            ondelete="CASCADE",
        ),
    )


class DoctorReport(Base):
    __tablename__ = "doctor_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    clinician_questions: Mapped[list] = mapped_column(JSONB, nullable=False)
    safety_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    safety_audit_notes: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    pdf_storage_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_doctor_reports_patient_cohort",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["investigation_id", "patient_id", "cohort_type"],
            ["investigations.id", "investigations.patient_id", "investigations.cohort_type"],
            name="fk_doctor_reports_investigation_scoped",
            ondelete="SET NULL (investigation_id)",
        ),
    )
