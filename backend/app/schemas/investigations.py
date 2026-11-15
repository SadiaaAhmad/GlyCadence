from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analytics import EvidenceItem


class GlycemicThresholds(BaseModel):
    """Named clinical and engineering thresholds used for deterministic numeric grounding."""

    model_config = ConfigDict(frozen=True)

    target_range_low_mg_dl: float = 70.0
    target_range_high_mg_dl: float = 180.0
    hypo_level1_lt_mg_dl: float = 70.0
    hypo_level2_lt_mg_dl: float = 54.0
    hyper_level1_gt_mg_dl: float = 180.0
    hyper_level2_gt_mg_dl: float = 250.0
    clinical_guidance_min_days: int = 14
    engineering_coverage_threshold_pct: float = 70.0
    iauc_pre_meal_window_min: float = 30.0
    iauc_post_meal_window_min: float = 180.0
    iauc_min_post_readings: int = 5
    iauc_min_post_span_min: float = 120.0
    iauc_max_consecutive_gap_min: float = 30.0
    drift_min_delta_mg_dl: float = 10.0


GLYCEMIC_THRESHOLDS = GlycemicThresholds()


class VerifierReportOut(BaseModel):
    passed: bool
    verification_status: Literal["passed", "rejected"]
    checks_run: list[str] = Field(default_factory=list)
    failed_reasons: list[str] = Field(default_factory=list)
    failed_details: list[str] = Field(default_factory=list)
    named_thresholds_used: list[str] = Field(default_factory=list)
    ungrounded_numbers: list[str] = Field(default_factory=list)
    repair_attempts: int = 0


class AgentObservationOut(BaseModel):
    agent_name: str
    window_start: datetime
    window_end: datetime
    finding_summary: str
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    observation_count: int
    missingness_pct: float
    deterministic_confidence: float
    uncertainty_notes: list[str] = Field(default_factory=list)


class DoctorReportOut(BaseModel):
    id: uuid.UUID
    investigation_id: uuid.UUID | None = None
    patient_id: uuid.UUID
    cohort_type: str
    period_start: datetime
    period_end: datetime
    safety_passed: bool
    is_safe_to_display: bool
    execution_mode: Literal["gemini", "deterministic_fallback"]
    model_used: str
    clinician_questions: list[str] = Field(default_factory=list)
    report_payload: dict[str, Any] = Field(default_factory=dict)
    safety_audit_notes: dict[str, Any] | None = None
    created_at: datetime


class InvestigationRunCreate(BaseModel):
    trigger_type: Literal["manual", "user_query", "drift_detected", "scheduled"] = "manual"
    mode: Literal["auto", "gemini", "deterministic_fallback"] = "auto"
    allowed_provenances: list[str] | None = None
    baseline_method: Literal["nearest_anchor", "pre_window_median"] = "nearest_anchor"
    device_id: str | None = None
    simulate_bad_draft: bool = False


class InvestigationRunOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    cohort_type: str
    is_research_dataset: bool = False
    dataset_label: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    progress_pct: int
    current_step: str | None = None
    trigger_type: str
    execution_mode: Literal["gemini", "deterministic_fallback"]
    model_used: str
    window_start: datetime
    window_end: datetime
    primary_summary_patient: str | None = None
    primary_summary_clinician: str | None = None
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    conflicting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    deterministic_confidence: float | None = None
    safety_passed: bool
    safety_audit_notes: dict[str, Any] | None = None
    verifier_report: VerifierReportOut | None = None
    observations: list[AgentObservationOut] = Field(default_factory=list)
    doctor_report: DoctorReportOut | None = None
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
