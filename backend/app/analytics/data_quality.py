from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from typing import Sequence

from app.schemas.analytics import CGMCoverageReport, DailyCoverageItem

ENGINEERING_COVERAGE_THRESHOLD_PCT = 70.0
CLINICAL_14D_MIN_DAYS = 14


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
) -> CGMCoverageReport:
    """Compute monitoring-period coverage and daily coverage with explicit thresholds.

    - Deduplicates identical timestamps.
    - Never interpolates across missing intervals.
    - Flags days with <70% daily coverage as ``is_partial_day = True``.
    - Surfaces explicit uncertainty notes when window duration <14 days or coverage <70%.
    """
    unique_sorted = sorted(set(ensure_utc_dt(t) for t in timestamps))
    interval_min = infer_native_sampling_interval_min(
        unique_sorted, sampling_intervals, default_interval_min=default_interval_min
    )
    expected_per_day = max(1, int(round(1440.0 / interval_min)))

    if not unique_sorted:
        now = datetime.now(timezone.utc)
        w_start = ensure_utc_dt(window_start) if window_start else now
        w_end = ensure_utc_dt(window_end) if window_end else now
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
            engineering_threshold_pct=engineering_threshold_pct,
            meets_14d_clinical_guidance=False,
            meets_engineering_period_threshold=False,
            deterministic_confidence=0.0,
            uncertainty_notes=["No valid CGM readings available in the requested window."],
        )

    w_start = ensure_utc_dt(window_start) if window_start else unique_sorted[0]
    w_end = ensure_utc_dt(window_end) if window_end else unique_sorted[-1]
    if w_end < w_start:
        w_start, w_end = w_end, w_start

    in_window = [t for t in unique_sorted if w_start <= t <= w_end]
    observed_count = len(in_window)

    # Group by UTC calendar date across the covered date span
    start_date: date = w_start.date()
    end_date: date = w_end.date()
    counts_by_day: dict[date, int] = defaultdict(int)
    for t in in_window:
        counts_by_day[t.date()] += 1

    total_calendar_days = (end_date - start_date).days + 1
    daily_items: list[DailyCoverageItem] = []
    partial_days = 0
    full_days = 0

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

    # Expected readings across the monitoring period:
    # If explicit window_start and window_end span >= 1 interval, use exact elapsed intervals + 1
    # when window is sub-day, or calendar-day expectation when spanning full days.
    elapsed_minutes = max(0.0, (w_end - w_start).total_seconds() / 60.0)
    if window_start is not None and window_end is not None and elapsed_minutes >= interval_min:
        expected_period = int(math.floor(elapsed_minutes / interval_min)) + 1
    else:
        expected_period = total_calendar_days * expected_per_day

    expected_period = max(1, expected_period)
    period_cov_pct = min(100.0, round((observed_count / expected_period) * 100.0, 2))
    period_miss_pct = round(max(0.0, 100.0 - period_cov_pct), 2)

    # Detect large sensor gaps (> 2 * native sampling interval)
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

    notes: list[str] = []
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
