from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CALCULATION_VERSION = "v1.1.0"


class SourceRecordRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    table_name: str
    record_id: str
    source_dataset: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_name: str
    baseline_value: float | None = None
    current_value: float | None = None
    delta: float | None = None
    unit: str | None = None
    observation_count: int = Field(ge=0)
    expected_observation_count: int | None = Field(default=None, ge=0)
    window_start: datetime
    window_end: datetime
    source_datasets: tuple[str, ...]
    source_records: tuple[SourceRecordRef, ...]
    calculation_method: str
    calculation_version: str = CALCULATION_VERSION
    missingness_pct: float = Field(ge=0.0, le=100.0)
    uncertainty_notes: tuple[str, ...] = ()

    @field_validator("window_start", "window_end")
    @classmethod
    def require_utc_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() != timedelta(0):
            raise ValueError("Evidence timestamps must be timezone-aware UTC")
        return v

    @model_validator(mode="after")
    def validate_chronological_window(self) -> "EvidenceItem":
        if self.window_start > self.window_end:
            raise ValueError("window_start must be <= window_end")
        return self


class DailyCoverageItem(BaseModel):
    date: date
    observed_readings: int
    expected_readings: int
    coverage_pct: float
    missingness_pct: float
    is_partial_day: bool


class CGMCoverageReport(BaseModel):
    window_start: datetime
    window_end: datetime
    native_sampling_interval_min: int
    observed_readings: int
    expected_period_readings: int
    period_coverage_pct: float
    period_missingness_pct: float
    daily_coverage: list[DailyCoverageItem]
    partial_days_count: int
    full_days_count: int
    large_gaps_count: int
    max_gap_minutes: float
    native_observation_count: int = 0
    interpolated_observation_count: int = 0
    derived_observation_count: int = 0
    unknown_observation_count: int = 0
    excluded_non_native_count: int = 0
    timestamp_semantics: list[str] = Field(default_factory=lambda: ["utc_exact"])
    timezone_basis: list[str] = Field(default_factory=lambda: ["source_confirmed"])
    calendar_date_comparable: bool = True
    engineering_threshold_pct: float = 70.0
    clinical_guidance_reference: str = (
        "International CGM consensus typically recommends >=70% sensor wear over a 14-day window."
    )
    meets_14d_clinical_guidance: bool
    meets_engineering_period_threshold: bool
    deterministic_confidence: float
    uncertainty_notes: list[str]


class GlucoseSummaryOut(BaseModel):
    window_start: datetime
    window_end: datetime
    observation_count: int
    native_observation_count: int = 0
    interpolated_observation_count: int = 0
    derived_observation_count: int = 0
    unknown_observation_count: int = 0
    excluded_non_native_count: int = 0
    timestamp_semantics: list[str] = Field(default_factory=lambda: ["utc_exact"])
    timezone_basis: list[str] = Field(default_factory=lambda: ["source_confirmed"])
    calendar_date_comparable: bool = True
    mean_glucose_mg_dl: float | None
    sd_glucose_mg_dl: float | None
    cv_pct: float | None
    min_glucose_mg_dl: float | None
    max_glucose_mg_dl: float | None
    median_glucose_mg_dl: float | None
    tir_pct: float | None
    tbr_pct: float | None
    tbr_level2_pct: float | None
    tar_pct: float | None
    tar_level2_pct: float | None
    coverage: CGMCoverageReport
    evidence_items: list[EvidenceItem]


class MealResponseItem(BaseModel):
    meal_id: str
    logged_at: datetime
    meal_type: str
    description: str
    carbs_g: float | None
    timestamp_semantics: str = "utc_exact"
    calendar_date_comparable: bool = True
    pre_meal_glucose_mg_dl: float | None
    pre_meal_recorded_at: datetime | None
    peak_post_meal_glucose_mg_dl: float | None
    excursion_delta_mg_dl: float | None
    post_meal_reading_count: int
    excluded_non_native_count: int = 0
    post_meal_span_minutes: float
    max_consecutive_gap_minutes: float | None
    iauc_mg_dl_min: float | None
    iauc_valid: bool
    rejection_reasons: list[str]
    uncertainty_notes: list[str]
    evidence: EvidenceItem | None = None


class DriftSummaryOut(BaseModel):
    window_start: datetime
    window_end: datetime
    analysis_type: Literal["exploratory_descriptive"] = "exploratory_descriptive"
    is_exploratory: bool = True
    status: Literal["upward_drift", "downward_drift", "stable", "insufficient_data"]
    baseline_window_start: datetime | None = None
    baseline_window_end: datetime | None = None
    recent_window_start: datetime | None = None
    recent_window_end: datetime | None = None
    baseline_observation_count: int = 0
    recent_observation_count: int = 0
    baseline_coverage_pct: float | None = None
    recent_coverage_pct: float | None = None
    baseline_mean_mg_dl: float | None
    recent_mean_mg_dl: float | None
    delta_mg_dl: float | None
    statistical_note: str = (
        "Exploratory descriptive comparison only: CGM time series are serially autocorrelated, "
        "so ordinary independent-sample t-test p-values do not establish statistical significance."
    )
    deterministic_confidence: float
    uncertainty_notes: list[str]
    evidence: EvidenceItem | None = None


class MedicationPatternSummaryOut(BaseModel):
    active_regimen_count: int
    total_events: int
    taken_count: int
    missed_count: int
    delayed_count: int
    unknown_count: int
    adherence_computable: bool
    observed_taken_pct: float | None
    uncertainty_notes: list[str]
