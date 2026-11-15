import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="patient")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('patient', 'researcher', 'admin')", name="ck_users_role"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    access_jti: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class DatasetImport(Base):
    __tablename__ = "dataset_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_name: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_doi: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    directory_manifest_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_payload_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_report_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "dataset_name IN ('shanghai_t2dm', 'cgmacros', 'diatrend', 'ohiot1dm', 'synthetic_demo')",
            name="ck_dataset_imports_name",
        ),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_dataset_imports_status"),
        CheckConstraint(
            "source_file_checksum IS NOT NULL OR directory_manifest_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL",
            name="ck_dataset_imports_checksum_present",
        ),
    )


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset_imports.id", ondelete="SET NULL"), nullable=True
    )
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(32), nullable=True)
    diabetes_type: Mapped[str] = mapped_column(String(32), nullable=False, default="T2D")
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    dietary_restrictions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cultural_cuisine_pref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consent_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="365_days")
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=365)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="app_user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("id", "cohort_type", name="uq_patients_id_cohort"),
        CheckConstraint(
            "cohort_type IN ('research_participant', 'synthetic_demo', 'app_user')",
            name="ck_patients_cohort_type",
        ),
        CheckConstraint(
            "(cohort_type = 'app_user' AND user_id IS NOT NULL) OR "
            "(cohort_type IN ('research_participant', 'synthetic_demo') AND user_id IS NULL)",
            name="ck_patients_cohort_user_link",
        ),
        CheckConstraint(
            "diabetes_type IN ('T2D', 'T1D', 'prediabetes', 'healthy', 'unknown')",
            name="ck_patients_diabetes_type",
        ),
        CheckConstraint(
            "retention_policy IN ('30_days', '90_days', '180_days', '365_days', 'custom_days', "
            "'indefinite_until_revoked', 'research_archive', 'dataset_license_bound')",
            name="ck_patients_retention_policy",
        ),
    )


class AuditLog(Base):
    """Immutable append-only audit log.

    Note: ``actor_user_id`` and ``patient_id`` are stored as immutable historical
    UUID references (no cascading/SET NULL foreign keys) so that deleting expired
    patient records or test accounts never mutates existing audit rows.
    Non-sensitive operational context is stored in ``context_metadata`` so rows
    remain interpretable even after parent entities are removed.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "action IN ('read_records', 'create_log', 'run_investigation', 'poll_job', "
            "'export_pdf', 'login', 'revoke_token', 'safety_violation')",
            name="ck_audit_logs_action",
        ),
        Index("idx_audit_logs_patient_time", "patient_id", "created_at"),
    )
