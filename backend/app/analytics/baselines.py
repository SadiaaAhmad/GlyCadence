from dataclasses import dataclass
from datetime import datetime
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
    build_source_records_metadata,
)

HYPO_LEVEL2_MG_DL = 54.0
TARGET_LOW_MG_DL = 70.0
TARGET_HIGH_MG_DL = 180.0
HYPER_LEVEL2_MG_DL = 250.0


class MultipleDevicesError(ValueError):
    """Raised when multiple CGM devices are present in a series and no device_id is specified."""

    def __init__(self, devices_present: Sequence[str]) -> None:
        self.devices_present: list[str] = sorted(set(devices_present))
        super().__init__(
            f"multiple_devices_specify_device_id: Multiple CGM devices present ({', '.join(self.devices_present)}); specify device_id."
        )


@dataclass(frozen=True)
class GlucosePoint:
    record_id: str
    recorded_at: datetime
    glucose_mg_dl: float
    source_dataset: str
    reading_type: str = "cgm"
    sampling_interval_min: int | None = None
    device_id: str | None = None
    observation_provenance: str = "unknown"
    timestamp_semantics: str = "utc_exact"
    timezone_basis: str = "source_confirmed"


def prepare_glucose_points_with_stats(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    deduplicate_across_devices: bool = False,
) -> tuple[list[GlucosePoint], int]:
    """Extract, sort deterministically in UTC, and deduplicate glucose observations.

    Returns ``(deduped_points, deduplicated_removed_count)``.
    Defaults to ``deduplicate_across_devices=False`` so multi-device readings (e.g. Libre + Dexcom)
    at the same timestamp are never silently discarded.
    Sorting is keyed on ``(recorded_at, reading_type, device_id, record_id, glucose_mg_dl)``
    so the output is completely invariant to input ordering.
    """
    extracted: list[GlucosePoint] = []
    for idx, item in enumerate(readings):
        if isinstance(item, GlucosePoint):
            pt = GlucosePoint(
                record_id=item.record_id,
                recorded_at=ensure_utc_dt(item.recorded_at),
                glucose_mg_dl=float(item.glucose_mg_dl),
                source_dataset=item.source_dataset,
                reading_type=(item.reading_type or "cgm").strip().lower(),
                sampling_interval_min=item.sampling_interval_min,
                device_id=item.device_id,
                observation_provenance=item.observation_provenance or "unknown",
                timestamp_semantics=item.timestamp_semantics or "utc_exact",
                timezone_basis=item.timezone_basis or "source_confirmed",
            )
        elif isinstance(item, dict):
            raw_prov = item.get("observation_provenance")
            raw_rtype = item.get("reading_type")
            pt = GlucosePoint(
                record_id=str(item.get("id") or item.get("record_id") or f"pt-{idx}"),
                recorded_at=ensure_utc_dt(item["recorded_at"]),
                glucose_mg_dl=float(item["glucose_mg_dl"]),
                source_dataset=str(item.get("source_dataset") or "app_user"),
                reading_type=str(raw_rtype).strip().lower() if raw_rtype else "cgm",
                sampling_interval_min=item.get("sampling_interval_min"),
                device_id=item.get("device_id"),
                observation_provenance=str(raw_prov).strip().lower() if raw_prov else "unknown",
                timestamp_semantics=str(item.get("timestamp_semantics") or "utc_exact"),
                timezone_basis=str(item.get("timezone_basis") or "source_confirmed"),
            )
        else:
            raw_prov = getattr(item, "observation_provenance", None)
            raw_rtype = getattr(item, "reading_type", None)
            pt = GlucosePoint(
                record_id=str(item.id),
                recorded_at=ensure_utc_dt(item.recorded_at),
                glucose_mg_dl=float(item.glucose_mg_dl),
                source_dataset=str(item.source_dataset),
                reading_type=str(raw_rtype).strip().lower() if raw_rtype else "cgm",
                sampling_interval_min=item.sampling_interval_min,
                device_id=item.device_id,
                observation_provenance=str(raw_prov).strip().lower() if raw_prov else "unknown",
                timestamp_semantics=getattr(item, "timestamp_semantics", "utc_exact") or "utc_exact",
                timezone_basis=getattr(item, "timezone_basis", "source_confirmed") or "source_confirmed",
            )

        if math.isnan(pt.glucose_mg_dl) or math.isinf(pt.glucose_mg_dl) or pt.glucose_mg_dl <= 0:
            continue
        extracted.append(pt)

    extracted.sort(
        key=lambda pt: (
            pt.recorded_at,
            pt.reading_type,
            pt.device_id or "",
            pt.record_id,
            pt.glucose_mg_dl,
        )
    )

    deduped: list[GlucosePoint] = []
    seen_keys: set[tuple] = set()
    removed_count = 0
    for pt in extracted:
        key = (
            (pt.recorded_at, pt.reading_type)
            if deduplicate_across_devices
            else (pt.recorded_at, pt.reading_type, pt.device_id or "__none__")
        )
        if key in seen_keys:
            removed_count += 1
            continue
        seen_keys.add(key)
        deduped.append(pt)

    return deduped, removed_count


def prepare_glucose_points(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    deduplicate_across_devices: bool = False,
) -> list[GlucosePoint]:
    """Extract, sort deterministically in UTC, and deduplicate glucose observations."""
    deduped, _ = prepare_glucose_points_with_stats(
        readings, deduplicate_across_devices=deduplicate_across_devices
    )
    return deduped


def filter_cgm_only(points: Sequence[GlucosePoint]) -> tuple[list[GlucosePoint], int]:
    """Filter strictly to reading_type == 'cgm' and return (cgm_points, excluded_non_cgm_count)."""
    cgm_pts = [p for p in points if p.reading_type == "cgm"]
    return cgm_pts, len(points) - len(cgm_pts)


def resolve_single_device_cgm_points(
    cgm_points: Sequence[GlucosePoint],
    *,
    device_id: str | None = None,
) -> tuple[list[GlucosePoint], str | None, list[str]]:
    """Ensure CGM analytics operate on a single sensor stream without mixing devices/cadences."""
    devices_present = sorted({p.device_id for p in cgm_points if p.device_id})
    if device_id is not None:
        filtered = [p for p in cgm_points if p.device_id == device_id]
        return filtered, device_id, devices_present

    if len(devices_present) > 1:
        raise MultipleDevicesError(devices_present)

    resolved_device = devices_present[0] if len(devices_present) == 1 else None
    return list(cgm_points), resolved_device, devices_present


def filter_and_count_provenance(
    points: Sequence[GlucosePoint],
    *,
    native_only: bool = True,
) -> tuple[list[GlucosePoint], dict[str, int], int]:
    """Count observation provenance categories and optionally filter to verified native readings."""
    counts: dict[str, int] = {"native": 0, "interpolated": 0, "derived": 0, "unknown": 0}
    for p in points:
        prov = p.observation_provenance if p.observation_provenance in counts else "unknown"
        counts[prov] += 1

    if not native_only:
        return list(points), counts, 0

    native_pts = [p for p in points if p.observation_provenance == "native"]
    excluded = len(points) - len(native_pts)
    return native_pts, counts, excluded


def compute_glucose_summary(
    readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    default_interval_min: int = 15,
    native_only: bool = True,
    device_id: str | None = None,
    timezone_name: str | None = None,
) -> GlucoseSummaryOut:
    """Deterministically compute mean glucose, SD, CV%, TIR, TBR, TAR, and CGM coverage.

    - Uses ``reading_type == 'cgm'`` only (excluding non-CGM finger-stick/fasting points).
    - Never merges multiple CGM devices; raises ``MultipleDevicesError`` when more than one
      device is present and ``device_id`` is not specified.
    - Returns ``None`` for ``sd_glucose_mg_dl`` and ``cv_pct`` when ``observation_count < 2``.
    """
    all_points, dedup_removed = prepare_glucose_points_with_stats(
        readings, deduplicate_across_devices=False
    )
    if window_start is not None:
        w_start_filter = ensure_utc_dt(window_start)
        all_points = [p for p in all_points if p.recorded_at >= w_start_filter]
    if window_end is not None:
        w_end_filter = ensure_utc_dt(window_end)
        all_points = [p for p in all_points if p.recorded_at <= w_end_filter]

    sem_list = sorted({p.timestamp_semantics for p in all_points}) if all_points else ["utc_exact"]
    tz_basis_list = sorted({p.timezone_basis for p in all_points}) if all_points else ["source_confirmed"]
    cgm_points, excluded_non_cgm = filter_cgm_only(all_points)
    device_points, resolved_device_id, devices_present = resolve_single_device_cgm_points(
        cgm_points, device_id=device_id
    )
    points, prov_counts, excluded_non_native = filter_and_count_provenance(
        device_points, native_only=native_only
    )
    filter_mode = "native_only" if native_only else "include_non_native"

    coverage = compute_cgm_coverage(
        [p.recorded_at for p in points],
        sampling_intervals=[p.sampling_interval_min for p in points],
        window_start=window_start,
        window_end=window_end,
        default_interval_min=default_interval_min,
        provenance_counts=prov_counts,
        excluded_non_native_count=excluded_non_native,
        excluded_non_cgm_count=excluded_non_cgm,
        deduplicated_removed_count=dedup_removed,
        device_id=resolved_device_id,
        devices_present=devices_present,
        native_only=native_only,
        timestamp_semantics=sem_list,
        timezone_basis=tz_basis_list,
        timezone_name=timezone_name,
    )

    n = len(points)
    if n == 0:
        return GlucoseSummaryOut(
            window_start=coverage.window_start,
            window_end=coverage.window_end,
            observation_count=0,
            native_observation_count=prov_counts["native"],
            interpolated_observation_count=prov_counts["interpolated"],
            derived_observation_count=prov_counts["derived"],
            unknown_observation_count=prov_counts["unknown"],
            excluded_non_native_count=excluded_non_native,
            excluded_non_cgm_count=excluded_non_cgm,
            deduplicated_removed_count=dedup_removed,
            device_id=resolved_device_id,
            devices_present=devices_present,
            native_only=native_only,
            include_non_native=not native_only,
            provenance_filter_mode=filter_mode,
            timestamp_semantics=coverage.timestamp_semantics,
            timezone_basis=coverage.timezone_basis,
            calendar_date_comparable=coverage.calendar_date_comparable,
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
    sd_val: float | None = float(np.std(values, ddof=1)) if n >= 2 else None
    cv_val: float | None = (
        (sd_val / mean_val * 100.0) if (sd_val is not None and mean_val > 0) else None
    )
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
    sd_rounded = round(sd_val, 2) if sd_val is not None else None
    cv_rounded = round(cv_val, 2) if cv_val is not None else None

    datasets = tuple(sorted({p.source_dataset for p in points}))
    full_source_refs = [
        SourceRecordRef(
            table_name="glucose_readings",
            record_id=p.record_id,
            source_dataset=p.source_dataset,
        )
        for p in points
    ]
    src_meta = build_source_records_metadata(full_source_refs)
    uncertainty_tuple = tuple(coverage.uncertainty_notes)

    common_ev_kwargs = {
        "observation_count": n,
        "expected_observation_count": coverage.expected_period_readings,
        "window_start": coverage.window_start,
        "window_end": coverage.window_end,
        "source_datasets": datasets,
        **src_meta,
        "calculation_version": CALCULATION_VERSION,
        "missingness_pct": coverage.period_missingness_pct,
        "uncertainty_notes": uncertainty_tuple,
    }

    evidence_items: list[EvidenceItem] = [
        EvidenceItem(
            metric_name="mean_glucose_mg_dl",
            current_value=mean_rounded,
            unit="mg/dL",
            calculation_method="arithmetic_mean_native_cadence",
            **common_ev_kwargs,
        ),
    ]
    if cv_rounded is not None:
        evidence_items.append(
            EvidenceItem(
                metric_name="glucose_cv_pct",
                current_value=cv_rounded,
                unit="%",
                calculation_method="sample_sd_over_mean_pct_native_cadence",
                **common_ev_kwargs,
            )
        )
    evidence_items.extend(
        [
            EvidenceItem(
                metric_name="time_in_range_70_180_pct",
                current_value=tir_pct,
                unit="%",
                calculation_method="consensus_range_proportion_70_180_mg_dl",
                **common_ev_kwargs,
            ),
            EvidenceItem(
                metric_name="time_below_range_lt_70_pct",
                current_value=tbr_pct,
                unit="%",
                calculation_method="consensus_range_proportion_lt_70_mg_dl",
                **common_ev_kwargs,
            ),
            EvidenceItem(
                metric_name="time_below_range_level2_lt_54_pct",
                current_value=tbr_l2_pct,
                unit="%",
                calculation_method="consensus_range_proportion_lt_54_mg_dl",
                **common_ev_kwargs,
            ),
            EvidenceItem(
                metric_name="time_above_range_gt_180_pct",
                current_value=tar_pct,
                unit="%",
                calculation_method="consensus_range_proportion_gt_180_mg_dl",
                **common_ev_kwargs,
            ),
            EvidenceItem(
                metric_name="time_above_range_level2_gt_250_pct",
                current_value=tar_l2_pct,
                unit="%",
                calculation_method="consensus_range_proportion_gt_250_mg_dl",
                **common_ev_kwargs,
            ),
        ]
    )

    return GlucoseSummaryOut(
        window_start=coverage.window_start,
        window_end=coverage.window_end,
        observation_count=n,
        native_observation_count=prov_counts["native"],
        interpolated_observation_count=prov_counts["interpolated"],
        derived_observation_count=prov_counts["derived"],
        unknown_observation_count=prov_counts["unknown"],
        excluded_non_native_count=excluded_non_native,
        excluded_non_cgm_count=excluded_non_cgm,
        deduplicated_removed_count=dedup_removed,
        device_id=resolved_device_id,
        devices_present=devices_present,
        native_only=native_only,
        include_non_native=not native_only,
        provenance_filter_mode=filter_mode,
        timestamp_semantics=coverage.timestamp_semantics,
        timezone_basis=coverage.timezone_basis,
        calendar_date_comparable=coverage.calendar_date_comparable,
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
