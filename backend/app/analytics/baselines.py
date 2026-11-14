from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Sequence

import numpy as np

from app.analytics.data_quality import compute_cgm_coverage, ensure_utc_dt
from app.models import GlucoseReading
from app.schemas.analytics import (
    CALCULATION_VERSION,
    EvidenceItem,
    GlucoseSummaryOut,
    SourceRecordRef,
)

HYPO_LEVEL2_MG_DL = 54.0
TARGET_LOW_MG_DL = 70.0
TARGET_HIGH_MG_DL = 180.0
HYPER_LEVEL2_MG_DL = 250.0


@dataclass(frozen=True)
class GlucosePoint:
    record_id: str
    recorded_at: datetime
    glucose_mg_dl: float
    source_dataset: str
    sampling_interval_min: int | None = None
    device_id: str | None = None


def prepare_glucose_points(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
) -> list[GlucosePoint]:
    """Deduplicate by (recorded_at, device_id) and sort chronologically in UTC."""
    extracted: list[tuple[int, GlucosePoint]] = []
    for idx, item in enumerate(readings):
        if isinstance(item, GlucosePoint):
            pt = GlucosePoint(
                record_id=item.record_id,
                recorded_at=ensure_utc_dt(item.recorded_at),
                glucose_mg_dl=float(item.glucose_mg_dl),
                source_dataset=item.source_dataset,
                sampling_interval_min=item.sampling_interval_min,
                device_id=item.device_id,
            )
        elif isinstance(item, dict):
            pt = GlucosePoint(
                record_id=str(item.get("id") or item.get("record_id") or f"pt-{idx}"),
                recorded_at=ensure_utc_dt(item["recorded_at"]),
                glucose_mg_dl=float(item["glucose_mg_dl"]),
                source_dataset=str(item.get("source_dataset") or "app_user"),
                sampling_interval_min=item.get("sampling_interval_min"),
                device_id=item.get("device_id"),
            )
        else:
            pt = GlucosePoint(
                record_id=str(item.id),
                recorded_at=ensure_utc_dt(item.recorded_at),
                glucose_mg_dl=float(item.glucose_mg_dl),
                source_dataset=str(item.source_dataset),
                sampling_interval_min=item.sampling_interval_min,
                device_id=item.device_id,
            )

        if math.isnan(pt.glucose_mg_dl) or math.isinf(pt.glucose_mg_dl) or pt.glucose_mg_dl <= 0:
            continue
        extracted.append((idx, pt))

    # Sort by timestamp ASC, preserving first-seen source order for ties
    extracted.sort(key=lambda pair: (pair[1].recorded_at, pair[0]))

    deduped: list[GlucosePoint] = []
    seen_timestamps: set[datetime] = set()
    for _, pt in extracted:
        if pt.recorded_at in seen_timestamps:
            continue
        seen_timestamps.add(pt.recorded_at)
        deduped.append(pt)

    return deduped


def compute_glucose_summary(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    default_interval_min: int = 15,
) -> GlucoseSummaryOut:
    """Deterministically compute mean glucose, SD, CV%, TIR, TBR, TAR, and CGM coverage."""
    points = prepare_glucose_points(readings)
    if window_start is not None:
        w_start_filter = ensure_utc_dt(window_start)
        points = [p for p in points if p.recorded_at >= w_start_filter]
    if window_end is not None:
        w_end_filter = ensure_utc_dt(window_end)
        points = [p for p in points if p.recorded_at <= w_end_filter]

    coverage = compute_cgm_coverage(
        [p.recorded_at for p in points],
        sampling_intervals=[p.sampling_interval_min for p in points],
        window_start=window_start,
        window_end=window_end,
        default_interval_min=default_interval_min,
    )

    n = len(points)
    if n == 0:
        return GlucoseSummaryOut(
            window_start=coverage.window_start,
            window_end=coverage.window_end,
            observation_count=0,
            mean_glucose_mg_dl=None,
            sd_glucose_mg_dl=None,
            cv_pct=None,
            min_glucose_mg_dl=None,
            max_glucose_mg_dl=None,
            median_glucose_mg_dl=None,
            tir_pct=None,
            tbr_pct=None,
            tbr_level2_pct=None,
            tar_pct=None,
            tar_level2_pct=None,
            coverage=coverage,
            evidence_items=[],
        )

    values = np.array([p.glucose_mg_dl for p in points], dtype=np.float64)
    mean_val = float(np.mean(values))
    sd_val = float(np.std(values, ddof=1)) if n >= 2 else 0.0
    cv_val = (sd_val / mean_val * 100.0) if (n >= 2 and mean_val > 0) else 0.0
    min_val = float(np.min(values))
    max_val = float(np.max(values))
    median_val = float(np.median(values))

    tbr_l2_count = int(np.sum(values < HYPO_LEVEL2_MG_DL))
    tbr_count = int(np.sum(values < TARGET_LOW_MG_DL))
    tir_count = int(np.sum((values >= TARGET_LOW_MG_DL) & (values <= TARGET_HIGH_MG_DL)))
    tar_count = int(np.sum(values > TARGET_HIGH_MG_DL))
    tar_l2_count = int(np.sum(values > HYPER_LEVEL2_MG_DL))

    tbr_l2_pct = round((tbr_l2_count / n) * 100.0, 2)
    tbr_pct = round((tbr_count / n) * 100.0, 2)
    tir_pct = round((tir_count / n) * 100.0, 2)
    tar_pct = round((tar_count / n) * 100.0, 2)
    tar_l2_pct = round((tar_l2_count / n) * 100.0, 2)

    mean_rounded = round(mean_val, 2)
    sd_rounded = round(sd_val, 2)
    cv_rounded = round(cv_val, 2)

    datasets = tuple(sorted({p.source_dataset for p in points}))
    source_refs = tuple(
        SourceRecordRef(
            table_name="glucose_readings",
            record_id=p.record_id,
            source_dataset=p.source_dataset,
        )
        for p in points[:200]
    )
    uncertainty_tuple = tuple(coverage.uncertainty_notes)

    evidence_items = [
        EvidenceItem(
            metric_name="mean_glucose_mg_dl",
            current_value=mean_rounded,
            unit="mg/dL",
            observation_count=n,
            expected_observation_count=coverage.expected_period_readings,
            window_start=coverage.window_start,
            window_end=coverage.window_end,
            source_datasets=datasets,
            source_records=source_refs,
            calculation_method="arithmetic_mean",
            calculation_version=CALCULATION_VERSION,
            missingness_pct=coverage.period_missingness_pct,
            uncertainty_notes=uncertainty_tuple,
        ),
        EvidenceItem(
            metric_name="glucose_cv_pct",
            current_value=cv_rounded,
            unit="%",
            observation_count=n,
            expected_observation_count=coverage.expected_period_readings,
            window_start=coverage.window_start,
            window_end=coverage.window_end,
            source_datasets=datasets,
            source_records=source_refs,
            calculation_method="sample_sd_over_mean_pct",
            calculation_version=CALCULATION_VERSION,
            missingness_pct=coverage.period_missingness_pct,
            uncertainty_notes=uncertainty_tuple,
        ),
        EvidenceItem(
            metric_name="time_in_range_70_180_pct",
            current_value=tir_pct,
            unit="%",
            observation_count=n,
            expected_observation_count=coverage.expected_period_readings,
            window_start=coverage.window_start,
            window_end=coverage.window_end,
            source_datasets=datasets,
            source_records=source_refs,
            calculation_method="consensus_range_proportion_70_180_mg_dl",
            calculation_version=CALCULATION_VERSION,
            missingness_pct=coverage.period_missingness_pct,
            uncertainty_notes=uncertainty_tuple,
        ),
    ]

    return GlucoseSummaryOut(
        window_start=coverage.window_start,
        window_end=coverage.window_end,
        observation_count=n,
        mean_glucose_mg_dl=mean_rounded,
        sd_glucose_mg_dl=sd_rounded,
        cv_pct=cv_rounded,
        min_glucose_mg_dl=round(min_val, 2),
        max_glucose_mg_dl=round(max_val, 2),
        median_glucose_mg_dl=round(median_val, 2),
        tir_pct=tir_pct,
        tbr_pct=tbr_pct,
        tbr_level2_pct=tbr_l2_pct,
        tar_pct=tar_pct,
        tar_level2_pct=tar_l2_pct,
        coverage=coverage,
        evidence_items=evidence_items,
    )
