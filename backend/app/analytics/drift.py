from datetime import datetime, timezone
from typing import Sequence

import numpy as np
from scipy import stats

from app.analytics.baselines import GlucosePoint, prepare_glucose_points
from app.analytics.data_quality import compute_cgm_coverage, compute_deterministic_confidence
from app.models import GlucoseReading
from app.schemas.analytics import (
    CALCULATION_VERSION,
    DriftSummaryOut,
    EvidenceItem,
    SourceRecordRef,
)

MIN_DRIFT_DELTA_MG_DL = 10.0
ALPHA_THRESHOLD = 0.05


def compute_glucose_drift(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    split_ratio: float = 0.67,
) -> DriftSummaryOut:
    """Compare personal baseline window against recent window using Welch's t-test."""
    points = prepare_glucose_points(readings)
    n = len(points)
    if n < 10:
        now = datetime.now(timezone.utc)
        w_start = points[0].recorded_at if points else now
        w_end = points[-1].recorded_at if points else now
        return DriftSummaryOut(
            window_start=w_start,
            window_end=w_end,
            status="insufficient_data",
            baseline_mean_mg_dl=None,
            recent_mean_mg_dl=None,
            delta_mg_dl=None,
            p_value=None,
            deterministic_confidence=0.0,
            uncertainty_notes=["Fewer than 10 glucose readings available; drift detection skipped."],
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

    if float(np.std(base_vals)) == 0.0 and float(np.std(rec_vals)) == 0.0:
        p_val = 0.0 if abs(delta) > 0 else 1.0
    else:
        _, raw_p = stats.ttest_ind(rec_vals, base_vals, equal_var=False)
        p_val = round(float(raw_p), 6) if not np.isnan(raw_p) else 1.0

    if p_val < ALPHA_THRESHOLD and delta >= MIN_DRIFT_DELTA_MG_DL:
        status = "upward_drift"
    elif p_val < ALPHA_THRESHOLD and delta <= -MIN_DRIFT_DELTA_MG_DL:
        status = "downward_drift"
    else:
        status = "stable"

    coverage = compute_cgm_coverage(
        [p.recorded_at for p in points],
        sampling_intervals=[p.sampling_interval_min for p in points],
    )
    confidence = compute_deterministic_confidence(
        coverage_pct=coverage.period_coverage_pct,
        observation_count=n,
        min_recommended_observations=48,
    )

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
        metric_name="glucose_window_drift_mg_dl",
        baseline_value=base_mean,
        current_value=rec_mean,
        delta=delta,
        unit="mg/dL",
        observation_count=n,
        expected_observation_count=coverage.expected_period_readings,
        window_start=points[0].recorded_at,
        window_end=points[-1].recorded_at,
        source_datasets=datasets,
        source_records=source_refs,
        calculation_method="welch_t_test_window_comparison",
        calculation_version=CALCULATION_VERSION,
        missingness_pct=coverage.period_missingness_pct,
        uncertainty_notes=tuple(coverage.uncertainty_notes),
    )

    return DriftSummaryOut(
        window_start=points[0].recorded_at,
        window_end=points[-1].recorded_at,
        status=status,
        baseline_mean_mg_dl=base_mean,
        recent_mean_mg_dl=rec_mean,
        delta_mg_dl=delta,
        p_value=p_val,
        deterministic_confidence=confidence,
        uncertainty_notes=list(coverage.uncertainty_notes),
        evidence=evidence,
    )
