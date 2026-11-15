from datetime import datetime, timezone
from typing import Sequence

import numpy as np

from app.analytics.baselines import (
    GlucosePoint,
    filter_and_count_provenance,
    prepare_glucose_points,
)
from app.analytics.data_quality import compute_cgm_coverage, compute_deterministic_confidence
from app.models import GlucoseReading
from app.schemas.analytics import (
    CALCULATION_VERSION,
    DriftSummaryOut,
    EvidenceItem,
    SourceRecordRef,
)

MIN_DRIFT_DELTA_MG_DL = 10.0
SERIAL_CORRELATION_DISCLAIMER = (
    "Exploratory descriptive comparison only: CGM time series are serially autocorrelated, "
    "so ordinary independent-sample Welch t-test p-values do not establish statistical significance."
)


def compute_glucose_drift(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    split_ratio: float = 0.67,
    native_only: bool = True,
) -> DriftSummaryOut:
    """Compute exploratory descriptive comparison between personal baseline and recent windows.

    Because CGM observations are serially correlated, ordinary independent-sample
    t-test p-values are not used to claim statistical significance.
    """
    all_points = prepare_glucose_points(readings)
    sem_list = sorted({p.timestamp_semantics for p in all_points}) if all_points else ["utc_exact"]
    points, prov_counts, excluded_non_native = filter_and_count_provenance(
        all_points, native_only=native_only
    )
    n = len(points)
    if n < 10:
        now = datetime.now(timezone.utc)
        w_start = points[0].recorded_at if points else now
        w_end = points[-1].recorded_at if points else now
        return DriftSummaryOut(
            window_start=w_start,
            window_end=w_end,
            analysis_type="exploratory_descriptive",
            is_exploratory=True,
            status="insufficient_data",
            baseline_observation_count=0,
            recent_observation_count=0,
            statistical_note=SERIAL_CORRELATION_DISCLAIMER,
            deterministic_confidence=0.0,
            uncertainty_notes=[
                "Fewer than 10 verified native glucose readings available; exploratory drift comparison skipped.",
                SERIAL_CORRELATION_DISCLAIMER,
            ],
            evidence=None,
        )

    split_idx = max(5, min(n - 5, int(round(n * split_ratio))))
    baseline_pts = points[:split_idx]
    recent_pts = points[split_idx:]

    base_vals = np.array([p.glucose_mg_dl for p in baseline_pts], dtype=np.float64)
    rec_vals = np.array([p.glucose_mg_dl for p in recent_pts], dtype=np.float64)

    base_mean = round(float(np.mean(base_vals)), 2)
    rec_mean = round(float(np.mean(rec_vals)), 2)
    delta = round(rec_mean - base_mean, 2)

    if delta >= MIN_DRIFT_DELTA_MG_DL:
        status = "upward_drift"
    elif delta <= -MIN_DRIFT_DELTA_MG_DL:
        status = "downward_drift"
    else:
        status = "stable"

    base_cov = compute_cgm_coverage(
        [p.recorded_at for p in baseline_pts],
        sampling_intervals=[p.sampling_interval_min for p in baseline_pts],
        timestamp_semantics=sem_list,
    )
    rec_cov = compute_cgm_coverage(
        [p.recorded_at for p in recent_pts],
        sampling_intervals=[p.sampling_interval_min for p in recent_pts],
        timestamp_semantics=sem_list,
    )
    overall_cov = compute_cgm_coverage(
        [p.recorded_at for p in points],
        sampling_intervals=[p.sampling_interval_min for p in points],
        provenance_counts=prov_counts,
        excluded_non_native_count=excluded_non_native,
        timestamp_semantics=sem_list,
    )

    confidence = compute_deterministic_confidence(
        coverage_pct=overall_cov.period_coverage_pct,
        observation_count=n,
        min_recommended_observations=48,
    )

    notes = [SERIAL_CORRELATION_DISCLAIMER, *overall_cov.uncertainty_notes]

    datasets = tuple(sorted({p.source_dataset for p in points}))
    source_refs = tuple(
        SourceRecordRef(
            table_name="glucose_readings",
            record_id=p.record_id,
            source_dataset=p.source_dataset,
        )
        for p in points[:200]
    )

    evidence = EvidenceItem(
        metric_name="exploratory_glucose_window_shift_mg_dl",
        baseline_value=base_mean,
        current_value=rec_mean,
        delta=delta,
        unit="mg/dL",
        observation_count=n,
        expected_observation_count=overall_cov.expected_period_readings,
        window_start=points[0].recorded_at,
        window_end=points[-1].recorded_at,
        source_datasets=datasets,
        source_records=source_refs,
        calculation_method="exploratory_descriptive_window_comparison",
        calculation_version=CALCULATION_VERSION,
        missingness_pct=overall_cov.period_missingness_pct,
        uncertainty_notes=tuple(notes),
    )

    return DriftSummaryOut(
        window_start=points[0].recorded_at,
        window_end=points[-1].recorded_at,
        analysis_type="exploratory_descriptive",
        is_exploratory=True,
        status=status,
        baseline_window_start=baseline_pts[0].recorded_at,
        baseline_window_end=baseline_pts[-1].recorded_at,
        recent_window_start=recent_pts[0].recorded_at,
        recent_window_end=recent_pts[-1].recorded_at,
        baseline_observation_count=len(baseline_pts),
        recent_observation_count=len(recent_pts),
        baseline_coverage_pct=base_cov.period_coverage_pct,
        recent_coverage_pct=rec_cov.period_coverage_pct,
        baseline_mean_mg_dl=base_mean,
        recent_mean_mg_dl=rec_mean,
        delta_mg_dl=delta,
        statistical_note=SERIAL_CORRELATION_DISCLAIMER,
        deterministic_confidence=confidence,
        uncertainty_notes=notes,
        evidence=evidence,
    )
