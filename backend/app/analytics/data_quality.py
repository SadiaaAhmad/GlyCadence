from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, tzinfo
import math
from typing import Sequence

from app.ingestion.common import resolve_iana_tz
from app.schemas.analytics import CGMCoverageReport, DailyCoverageItem

ENGINEERING_COVERAGE_THRESHOLD_PCT = 70.0
CLINICAL_14D_MIN_DAYS = 14
DATE_SHIFTED_LIMITATION_NOTE = (
    "Timestamps use date_shifted_relative semantics (randomly shifted study dates without real-world timezone); "
    "valid only for within-participant elapsed-time analysis and must not be aligned by calendar date across participants or datasets."
)
ASSUMED_TIMEZONE_LIMITATION_NOTE = (
    "Timestamps include assumed_study_location/unknown timezone basis (e.g., Asia/Shanghai assumed from study location "
    "because raw spreadsheet timestamps lack explicit UTC offsets)."
)


def ensure_utc_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def infer_native_sampling_interval_min(
    timestamps: Sequence[datetime],
    explicit_intervals: Sequence[int | None] | None = None,
    default_interval_min: int = 15,
) -> int:
    """Determine native sensor sampling interval in minutes without interpolating gaps."""
    if explicit_intervals:
        valid_explicit = [int(x) for x in explicit_intervals if x is not None and x > 0]
        if valid_explicit:
            most_common, _ = Counter(valid_explicit).most_common(1)[0]
            return most_common

    if len(timestamps) >= 2:
        sorted_ts = sorted(set(ensure_utc_dt(t) for t in timestamps))
        deltas_min = [
            round((sorted_ts[i + 1] - sorted_ts[i]).total_seconds() / 60.0)
            for i in range(len(sorted_ts) - 1)
            if (sorted_ts[i + 1] - sorted_ts[i]).total_seconds() > 0
        ]
        positive_deltas = [d for d in deltas_min if 1 <= d <= 60]
        if positive_deltas:
            most_common_delta, _ = Counter(positive_deltas).most_common(1)[0]
            return int(most_common_delta)

    return default_interval_min


def compute_cgm_coverage(
    timestamps: Sequence[datetime],
    *,
    sampling_intervals: Sequence[int | None] | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    default_interval_min: int = 15,
    engineering_threshold_pct: float = ENGINEERING_COVERAGE_THRESHOLD_PCT,
    provenance_counts: dict[str, int] | None = None,
    excluded_non_native_count: int = 0,
    excluded_non_cgm_count: int = 0,
    deduplicated_removed_count: int = 0,
    device_id: str | None = None,
    devices_present: Sequence[str] | None = None,
    native_only: bool = True,
    timestamp_semantics: Sequence[str] | None = None,
    timezone_basis: Sequence[str] | None = None,
    timezone_name: str | None = None,
) -> CGMCoverageReport:
    """Compute monitoring-period coverage and daily coverage with explicit thresholds and provenance."""
    unique_sorted = sorted(set(ensure_utc_dt(t) for t in timestamps))
    interval_min = infer_native_sampling_interval_min(
        unique_sorted, sampling_intervals, default_interval_min=default_interval_min
    )
    expected_per_day = max(1, int(round(1440.0 / interval_min)))

    p_counts = provenance_counts or {
        "native": len(unique_sorted),
        "interpolated": 0,
        "derived": 0,
        "unknown": 0,
    }
    sem_list = sorted(set(timestamp_semantics)) if timestamp_semantics else ["utc_exact"]
    tz_basis_list = sorted(set(timezone_basis)) if timezone_basis else ["source_confirmed"]
    dev_list = sorted(set(devices_present)) if devices_present else ([device_id] if device_id else [])
    cal_comparable = "date_shifted_relative" not in sem_list
    filter_mode = "native_only" if native_only else "include_non_native"

    extra_notes: list[str] = []
    if not cal_comparable:
        extra_notes.append(DATE_SHIFTED_LIMITATION_NOTE)
    if "assumed_study_location" in tz_basis_list or "unknown" in tz_basis_list:
        extra_notes.append(ASSUMED_TIMEZONE_LIMITATION_NOTE)
    if deduplicated_removed_count > 0:
        extra_notes.append(
            f"Removed {deduplicated_removed_count} duplicate timestamp observation(s) during preparation."
        )
    if excluded_non_cgm_count > 0:
        extra_notes.append(
            f"Excluded {excluded_non_cgm_count} non-CGM reading(s) (e.g., cbg/fasting/pre_meal finger-stick observations) from CGM analytics."
        )
    if excluded_non_native_count > 0:
        extra_notes.append(
            f"Excluded {excluded_non_native_count} reading(s) with non-native provenance "
            f"(interpolated={p_counts.get('interpolated', 0)}, derived={p_counts.get('derived', 0)}, "
            f"unknown={p_counts.get('unknown', 0)}) from native-cadence CGM analytics."
        )

    if not unique_sorted:
        now = datetime.now(timezone.utc)
        w_start = ensure_utc_dt(window_start) if window_start else now
        w_end = ensure_utc_dt(window_end) if window_end else now
        empty_reason = (
            "No verified native CGM readings available in the requested window "
            "(all candidate CGM readings had unverified/unknown or non-native provenance and were excluded under native_only=True; "
            "pass include_non_native=true for exploratory comparison or supply native_evidence_reference during ingestion)."
            if (native_only and excluded_non_native_count > 0)
            else "No verified native CGM readings available in the requested window."
        )
        return CGMCoverageReport(
            window_start=w_start,
            window_end=w_end,
            native_sampling_interval_min=interval_min,
            observed_readings=0,
            expected_period_readings=expected_per_day,
            period_coverage_pct=0.0,
            period_missingness_pct=100.0,
            daily_coverage=[],
            partial_days_count=0,
            full_days_count=0,
            large_gaps_count=0,
            max_gap_minutes=0.0,
            native_observation_count=p_counts.get("native", 0),
            interpolated_observation_count=p_counts.get("interpolated", 0),
            derived_observation_count=p_counts.get("derived", 0),
            unknown_observation_count=p_counts.get("unknown", 0),
            excluded_non_native_count=excluded_non_native_count,
            excluded_non_cgm_count=excluded_non_cgm_count,
            deduplicated_removed_count=deduplicated_removed_count,
            device_id=device_id,
            devices_present=dev_list,
            native_only=native_only,
            include_non_native=not native_only,
            provenance_filter_mode=filter_mode,
            timestamp_semantics=sem_list,
            timezone_basis=tz_basis_list,
            calendar_date_comparable=cal_comparable,
            engineering_threshold_pct=engineering_threshold_pct,
            meets_14d_clinical_guidance=False,
            meets_engineering_period_threshold=False,
            deterministic_confidence=0.0,
            uncertainty_notes=[
                empty_reason,
                *extra_notes,
            ],
        )

    w_start = ensure_utc_dt(window_start) if window_start else unique_sorted[0]
    w_end = ensure_utc_dt(window_end) if window_end else unique_sorted[-1]
    if w_end < w_start:
        w_start, w_end = w_end, w_start

    in_window = [t for t in unique_sorted if w_start <= t <= w_end]
    observed_count = len(in_window)

    daily_items: list[DailyCoverageItem] = []
    partial_days = 0
    full_days = 0

    if not cal_comparable:
        # date_shifted_relative: bucket into 24-hour relative blocks from participant's first reading in window
        anchor_ts = in_window[0] if in_window else w_start
        anchor_base_date = anchor_ts.date()
        counts_by_rel_day: dict[int, int] = defaultdict(int)
        for t in in_window:
            rel_idx = max(0, int((t - anchor_ts).total_seconds() // 86400))
            counts_by_rel_day[rel_idx] += 1
        max_rel_idx = max(
            counts_by_rel_day.keys(),
            default=max(0, int((w_end - anchor_ts).total_seconds() // 86400)),
        )
        total_calendar_days = max_rel_idx + 1
        for rel_idx in range(total_calendar_days):
            cur_date = anchor_base_date + timedelta(days=rel_idx)
            obs_day = counts_by_rel_day.get(rel_idx, 0)
            cov_day = min(100.0, round((obs_day / expected_per_day) * 100.0, 2))
            miss_day = round(max(0.0, 100.0 - cov_day), 2)
            is_partial = cov_day < engineering_threshold_pct
            if is_partial:
                partial_days += 1
            else:
                full_days += 1
            daily_items.append(
                DailyCoverageItem(
                    date=cur_date,
                    observed_readings=obs_day,
                    expected_readings=expected_per_day,
                    coverage_pct=cov_day,
                    missingness_pct=miss_day,
                    is_partial_day=is_partial,
                )
            )
    else:
        # Resolve study/patient local timezone for daily coverage bucketing when applicable
        bucket_tz: tzinfo = timezone.utc
        if timezone_name:
            try:
                bucket_tz = resolve_iana_tz(timezone_name)
            except Exception:
                bucket_tz = timezone.utc
        elif "assumed_study_location" in tz_basis_list or "real_world_local" in sem_list:
            bucket_tz = resolve_iana_tz("Asia/Shanghai")

        start_date: date = w_start.astimezone(bucket_tz).date()
        end_date: date = w_end.astimezone(bucket_tz).date()
        counts_by_day: dict[date, int] = defaultdict(int)
        for t in in_window:
            counts_by_day[t.astimezone(bucket_tz).date()] += 1

        total_calendar_days = (end_date - start_date).days + 1
        for d_offset in range(total_calendar_days):
            cur_date = start_date + timedelta(days=d_offset)
            obs_day = counts_by_day.get(cur_date, 0)
            cov_day = min(100.0, round((obs_day / expected_per_day) * 100.0, 2))
            miss_day = round(max(0.0, 100.0 - cov_day), 2)
            is_partial = cov_day < engineering_threshold_pct
            if is_partial:
                partial_days += 1
            else:
                full_days += 1
            daily_items.append(
                DailyCoverageItem(
                    date=cur_date,
                    observed_readings=obs_day,
                    expected_readings=expected_per_day,
                    coverage_pct=cov_day,
                    missingness_pct=miss_day,
                    is_partial_day=is_partial,
                )
            )

    elapsed_minutes = max(0.0, (w_end - w_start).total_seconds() / 60.0)
    if window_start is not None and window_end is not None and elapsed_minutes >= interval_min:
        expected_period = int(math.floor(elapsed_minutes / interval_min)) + 1
    else:
        expected_period = total_calendar_days * expected_per_day

    expected_period = max(1, expected_period)
    period_cov_pct = min(100.0, round((observed_count / expected_period) * 100.0, 2))
    period_miss_pct = round(max(0.0, 100.0 - period_cov_pct), 2)

    gap_threshold_min = 2.0 * interval_min
    large_gaps = 0
    max_gap_min = 0.0
    for i in range(len(in_window) - 1):
        gap_min = (in_window[i + 1] - in_window[i]).total_seconds() / 60.0
        if gap_min > max_gap_min:
            max_gap_min = round(gap_min, 2)
        if gap_min > gap_threshold_min + 1e-6:
            large_gaps += 1

    meets_eng = period_cov_pct >= engineering_threshold_pct
    meets_14d = total_calendar_days >= CLINICAL_14D_MIN_DAYS and meets_eng

    notes: list[str] = list(extra_notes)
    if total_calendar_days < CLINICAL_14D_MIN_DAYS:
        notes.append(
            f"Monitoring window spans {total_calendar_days} day(s), below the 14-day clinical AGP consensus reference."
        )
    if not meets_eng:
        notes.append(
            f"Period CGM coverage ({period_cov_pct:.1f}%) is below the {engineering_threshold_pct:.0f}% GlyCadence engineering threshold."
        )
    if partial_days > 0:
        notes.append(
            f"{partial_days} of {total_calendar_days} day(s) have <{engineering_threshold_pct:.0f}% daily sensor coverage (flagged as partial_day)."
        )
    if large_gaps > 0:
        notes.append(
            f"Detected {large_gaps} sensor gap(s) exceeding {gap_threshold_min:.0f} minutes (max gap {max_gap_min:.1f} min); gaps are never interpolated."
        )

    confidence = compute_deterministic_confidence(
        coverage_pct=period_cov_pct,
        observation_count=observed_count,
        min_recommended_observations=max(24, expected_per_day),
    )

    return CGMCoverageReport(
        window_start=w_start,
        window_end=w_end,
        native_sampling_interval_min=interval_min,
        observed_readings=observed_count,
        expected_period_readings=expected_period,
        period_coverage_pct=period_cov_pct,
        period_missingness_pct=period_miss_pct,
        daily_coverage=daily_items,
        partial_days_count=partial_days,
        full_days_count=full_days,
        large_gaps_count=large_gaps,
        max_gap_minutes=max_gap_min,
        native_observation_count=p_counts.get("native", 0),
        interpolated_observation_count=p_counts.get("interpolated", 0),
        derived_observation_count=p_counts.get("derived", 0),
        unknown_observation_count=p_counts.get("unknown", 0),
        excluded_non_native_count=excluded_non_native_count,
        excluded_non_cgm_count=excluded_non_cgm_count,
        deduplicated_removed_count=deduplicated_removed_count,
        device_id=device_id,
        devices_present=dev_list,
        native_only=native_only,
        include_non_native=not native_only,
        provenance_filter_mode=filter_mode,
        timestamp_semantics=sem_list,
        timezone_basis=tz_basis_list,
        calendar_date_comparable=cal_comparable,
        engineering_threshold_pct=engineering_threshold_pct,
        meets_14d_clinical_guidance=meets_14d,
        meets_engineering_period_threshold=meets_eng,
        deterministic_confidence=confidence,
        uncertainty_notes=notes,
    )


def compute_deterministic_confidence(
    *,
    coverage_pct: float,
    observation_count: int,
    min_recommended_observations: int = 96,
) -> float:
    """Compute a deterministic [0.0, 1.0] confidence score from coverage and sample size."""
    if observation_count <= 0 or coverage_pct <= 0.0:
        return 0.0
    coverage_factor = min(1.0, max(0.0, coverage_pct / 100.0))
    sample_factor = min(1.0, observation_count / max(1, min_recommended_observations))
    score = 0.65 * coverage_factor + 0.35 * sample_factor
    return round(min(1.0, max(0.0, score)), 4)
