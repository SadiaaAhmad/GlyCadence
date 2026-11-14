from datetime import datetime, timedelta
from typing import Sequence

from app.analytics.baselines import GlucosePoint, prepare_glucose_points
from app.analytics.data_quality import ensure_utc_dt
from app.models import GlucoseReading, Meal
from app.schemas.analytics import (
    CALCULATION_VERSION,
    EvidenceItem,
    MealResponseItem,
    SourceRecordRef,
)

PRE_MEAL_WINDOW_MIN = 30.0
POST_MEAL_WINDOW_MIN = 180.0
MIN_POST_MEAL_READINGS = 5
MIN_POST_MEAL_SPAN_MIN = 120.0
MAX_PERMISSIBLE_GAP_MIN = 30.0


def evaluate_single_meal_response(
    *,
    meal_id: str,
    logged_at: datetime,
    meal_type: str,
    description: str,
    carbs_g: float | None,
    meal_source_dataset: str,
    glucose_readings: Sequence[GlucoseReading | GlucosePoint | dict],
) -> MealResponseItem:
    """Compute postprandial excursion and strict positive trapezoidal iAUC for one meal.

    Strict validity gates (all 4 required for ``iauc_valid = True``):
    1. Pre-meal anchor: >=1 valid reading in [-30 min, 0 min]; closest to logged_at is
       anchored at t = 0 as baseline G_0.
    2. Post-meal count: >=5 separate post-meal readings in (0 min, +180 min].
    3. Window coverage: post-meal coverage within [0, +180 min] spans >=120 minutes
       (last post-meal reading at t >= 120 min).
    4. Max consecutive gap: <=30 minutes across the entire integration path starting
       from the t = 0 baseline anchor through the last post-meal reading.
    """
    meal_ts = ensure_utc_dt(logged_at)
    points = prepare_glucose_points(glucose_readings)

    pre_start = meal_ts - timedelta(minutes=PRE_MEAL_WINDOW_MIN)
    post_end = meal_ts + timedelta(minutes=POST_MEAL_WINDOW_MIN)

    pre_candidates = [p for p in points if pre_start <= p.recorded_at <= meal_ts]
    post_points = [p for p in points if meal_ts < p.recorded_at <= post_end]

    rejection_reasons: list[str] = []
    uncertainty_notes: list[str] = []

    # 1. Pre-meal baseline anchor (closest to meal_ts in [-30m, 0m])
    anchor_point: GlucosePoint | None = None
    if pre_candidates:
        anchor_point = max(pre_candidates, key=lambda p: p.recorded_at)
    else:
        rejection_reasons.append("missing_pre_meal_baseline_anchor_within_30m")
        uncertainty_notes.append(
            "No valid pre-meal glucose reading found within [-30 min, 0 min] of meal timestamp."
        )

    # 2. Post-meal reading count
    post_count = len(post_points)
    if post_count < MIN_POST_MEAL_READINGS:
        rejection_reasons.append("insufficient_post_meal_readings_lt_5")
        uncertainty_notes.append(
            f"Only {post_count} post-meal reading(s) in (0, +180 min]; at least {MIN_POST_MEAL_READINGS} required."
        )

    # 3. Post-meal window coverage span within [0, +180 min]
    post_times_min = [(p.recorded_at - meal_ts).total_seconds() / 60.0 for p in post_points]
    span_minutes = round(post_times_min[-1], 2) if post_times_min else 0.0
    if span_minutes < MIN_POST_MEAL_SPAN_MIN - 1e-6:
        rejection_reasons.append("insufficient_post_meal_window_span_lt_120m")
        uncertainty_notes.append(
            f"Post-meal observations reach {span_minutes:.1f} min post-meal; >=120.0 min coverage required."
        )

    # 4. Consecutive sampling gap check (including t = 0 baseline anchor)
    max_gap_min: float | None = None
    if post_times_min:
        path_times = [0.0, *post_times_min]
        gaps = [path_times[i + 1] - path_times[i] for i in range(len(path_times) - 1)]
        max_gap_min = round(max(gaps), 2)
        if max_gap_min > MAX_PERMISSIBLE_GAP_MIN + 1e-6:
            rejection_reasons.append("consecutive_sampling_gap_gt_30m")
            uncertainty_notes.append(
                f"Maximum consecutive sampling gap is {max_gap_min:.1f} min (>30.0 min limit); large gaps are never interpolated."
            )

    pre_val = round(anchor_point.glucose_mg_dl, 2) if anchor_point else None
    peak_post = round(max(p.glucose_mg_dl for p in post_points), 2) if post_points else None
    excursion_delta = (
        round(peak_post - pre_val, 2)
        if (peak_post is not None and pre_val is not None)
        else None
    )

    if rejection_reasons or anchor_point is None:
        return MealResponseItem(
            meal_id=meal_id,
            logged_at=meal_ts,
            meal_type=meal_type,
            description=description,
            carbs_g=carbs_g,
            pre_meal_glucose_mg_dl=pre_val,
            pre_meal_recorded_at=anchor_point.recorded_at if anchor_point else None,
            peak_post_meal_glucose_mg_dl=peak_post,
            excursion_delta_mg_dl=excursion_delta,
            post_meal_reading_count=post_count,
            post_meal_span_minutes=span_minutes,
            max_consecutive_gap_minutes=max_gap_min,
            iauc_mg_dl_min=None,
            iauc_valid=False,
            rejection_reasons=rejection_reasons,
            uncertainty_notes=uncertainty_notes,
            evidence=None,
        )

    # Valid iAUC: positive trapezoidal integration above G_0 anchored at t = 0
    g0 = anchor_point.glucose_mg_dl
    vertices_t = [0.0, *post_times_min]
    vertices_pos_g = [0.0, *[max(p.glucose_mg_dl - g0, 0.0) for p in post_points]]

    iauc = 0.0
    for i in range(len(vertices_t) - 1):
        dt = vertices_t[i + 1] - vertices_t[i]
        iauc += 0.5 * (vertices_pos_g[i] + vertices_pos_g[i + 1]) * dt

    iauc_rounded = round(iauc, 2)

    # Expected readings across [0, +180 min] based on native interval (default 15m -> 12 post-meal readings)
    intervals = [p.sampling_interval_min for p in post_points if p.sampling_interval_min]
    native_interval = intervals[0] if intervals else 15
    expected_post_count = max(MIN_POST_MEAL_READINGS, int(round(POST_MEAL_WINDOW_MIN / native_interval)))
    missingness_pct = round(
        max(0.0, min(100.0, (1.0 - min(1.0, post_count / expected_post_count)) * 100.0)),
        2,
    )

    source_refs = (
        SourceRecordRef(
            table_name="meals",
            record_id=meal_id,
            source_dataset=meal_source_dataset,
        ),
        SourceRecordRef(
            table_name="glucose_readings",
            record_id=anchor_point.record_id,
            source_dataset=anchor_point.source_dataset,
        ),
        *(
            SourceRecordRef(
                table_name="glucose_readings",
                record_id=p.record_id,
                source_dataset=p.source_dataset,
            )
            for p in post_points
        ),
    )
    datasets = tuple(
        sorted({meal_source_dataset, anchor_point.source_dataset, *(p.source_dataset for p in post_points)})
    )

    evidence = EvidenceItem(
        metric_name="postprandial_iauc_mg_dl_min",
        baseline_value=pre_val,
        current_value=iauc_rounded,
        delta=excursion_delta,
        unit="mg/dL*min",
        observation_count=post_count + 1,
        expected_observation_count=expected_post_count + 1,
        window_start=anchor_point.recorded_at,
        window_end=post_points[-1].recorded_at,
        source_datasets=datasets,
        source_records=source_refs,
        calculation_method="timestamp_positive_trapezoidal_iauc",
        calculation_version=CALCULATION_VERSION,
        missingness_pct=missingness_pct,
        uncertainty_notes=tuple(uncertainty_notes),
    )

    return MealResponseItem(
        meal_id=meal_id,
        logged_at=meal_ts,
        meal_type=meal_type,
        description=description,
        carbs_g=carbs_g,
        pre_meal_glucose_mg_dl=pre_val,
        pre_meal_recorded_at=anchor_point.recorded_at,
        peak_post_meal_glucose_mg_dl=peak_post,
        excursion_delta_mg_dl=excursion_delta,
        post_meal_reading_count=post_count,
        post_meal_span_minutes=span_minutes,
        max_consecutive_gap_minutes=max_gap_min,
        iauc_mg_dl_min=iauc_rounded,
        iauc_valid=True,
        rejection_reasons=[],
        uncertainty_notes=uncertainty_notes,
        evidence=evidence,
    )


def evaluate_meal_responses(
    meals: Sequence[Meal | dict],
    glucose_readings: Sequence[GlucoseReading | GlucosePoint | dict],
) -> list[MealResponseItem]:
    """Evaluate postprandial responses across a sequence of meals."""
    points = prepare_glucose_points(glucose_readings)
    results: list[MealResponseItem] = []
    for idx, meal in enumerate(meals):
        if isinstance(meal, dict):
            m_id = str(meal.get("id") or meal.get("meal_id") or f"meal-{idx}")
            m_ts = ensure_utc_dt(meal["logged_at"])
            m_type = str(meal.get("meal_type") or "unknown")
            m_desc = str(meal.get("description") or "")
            m_carbs = float(meal["carbs_g"]) if meal.get("carbs_g") is not None else None
            m_ds = str(meal.get("source_dataset") or "app_user")
        else:
            m_id = str(meal.id)
            m_ts = ensure_utc_dt(meal.logged_at)
            m_type = meal.meal_type
            m_desc = meal.description
            m_carbs = meal.carbs_g
            m_ds = meal.source_dataset

        results.append(
            evaluate_single_meal_response(
                meal_id=m_id,
                logged_at=m_ts,
                meal_type=m_type,
                description=m_desc,
                carbs_g=m_carbs,
                meal_source_dataset=m_ds,
                glucose_readings=points,
            )
        )
    return results
