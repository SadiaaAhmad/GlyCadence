from datetime import datetime, timedelta
from typing import Sequence

from app.analytics.baselines import (
    GlucosePoint,
    filter_and_count_provenance,
    filter_cgm_only,
    prepare_glucose_points_with_stats,
    resolve_single_device_cgm_points,
)
from app.analytics.data_quality import DATE_SHIFTED_LIMITATION_NOTE, ensure_utc_dt
from app.models import GlucoseReading, Meal
from app.schemas.analytics import (
    CALCULATION_VERSION,
    EvidenceItem,
    MealResponseItem,
    SourceRecordRef,
    build_source_records_metadata,
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
    meal_timestamp_semantics: str = "utc_exact",
    native_only: bool = True,
    device_id: str | None = None,
) -> MealResponseItem:
    """Compute postprandial excursion and strict positive trapezoidal iAUC for one meal."""
    meal_ts = ensure_utc_dt(logged_at)
    all_points, deduplicated_removed = prepare_glucose_points_with_stats(
        glucose_readings, deduplicate_across_devices=False
    )
    cgm_all_points, _ = filter_cgm_only(all_points)
    _, resolved_device_id, devices_present = resolve_single_device_cgm_points(
        cgm_all_points, device_id=device_id
    )

    pre_start = meal_ts - timedelta(minutes=PRE_MEAL_WINDOW_MIN)
    post_end = meal_ts + timedelta(minutes=POST_MEAL_WINDOW_MIN)
    window_points = [p for p in all_points if pre_start <= p.recorded_at <= post_end]

    cgm_window_points, excluded_non_cgm = filter_cgm_only(window_points)
    cgm_window_device_points, _, _ = resolve_single_device_cgm_points(
        cgm_window_points, device_id=device_id
    )
    points, prov_counts, excluded_non_native = filter_and_count_provenance(
        cgm_window_device_points, native_only=native_only
    )
    filter_mode = "native_only" if native_only else "include_non_native"

    sem_set = {meal_timestamp_semantics, *(p.timestamp_semantics for p in window_points)}
    resolved_sem = "date_shifted_relative" if "date_shifted_relative" in sem_set else meal_timestamp_semantics
    cal_comparable = resolved_sem != "date_shifted_relative"

    pre_candidates = [p for p in points if pre_start <= p.recorded_at <= meal_ts]
    post_points = [p for p in points if meal_ts < p.recorded_at <= post_end]

    rejection_reasons: list[str] = []
    uncertainty_notes: list[str] = []

    if not cal_comparable:
        uncertainty_notes.append(DATE_SHIFTED_LIMITATION_NOTE)
    if excluded_non_cgm > 0:
        uncertainty_notes.append(
            f"Excluded {excluded_non_cgm} non-CGM reading(s) (e.g., cbg/fasting/pre_meal finger-stick observations) in meal window."
        )
    if excluded_non_native > 0:
        uncertainty_notes.append(
            f"Excluded {excluded_non_native} non-native glucose reading(s) (interpolated/derived/unknown) in meal window."
        )
    if deduplicated_removed > 0:
        uncertainty_notes.append(
            f"Removed {deduplicated_removed} duplicate timestamp reading(s) during preparation."
        )

    anchor_point: GlucosePoint | None = None
    if pre_candidates:
        anchor_point = max(pre_candidates, key=lambda p: p.recorded_at)
    else:
        rejection_reasons.append("missing_pre_meal_baseline_anchor_within_30m")
        uncertainty_notes.append(
            "No valid native pre-meal glucose reading found within [-30 min, 0 min] of meal timestamp."
        )

    post_count = len(post_points)
    if post_count < MIN_POST_MEAL_READINGS:
        rejection_reasons.append("insufficient_post_meal_readings_lt_5")
        uncertainty_notes.append(
            f"Only {post_count} verified native post-meal reading(s) in (0, +180 min]; at least {MIN_POST_MEAL_READINGS} required."
        )

    post_times_min = [(p.recorded_at - meal_ts).total_seconds() / 60.0 for p in post_points]
    span_minutes = round(post_times_min[-1], 2) if post_times_min else 0.0
    if span_minutes < MIN_POST_MEAL_SPAN_MIN - 1e-6:
        rejection_reasons.append("insufficient_post_meal_window_span_lt_120m")
        uncertainty_notes.append(
            f"Post-meal observations reach {span_minutes:.1f} min post-meal; >=120.0 min coverage required."
        )

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
            timestamp_semantics=resolved_sem,
            calendar_date_comparable=cal_comparable,
            pre_meal_glucose_mg_dl=pre_val,
            pre_meal_recorded_at=anchor_point.recorded_at if anchor_point else None,
            peak_post_meal_glucose_mg_dl=peak_post,
            excursion_delta_mg_dl=excursion_delta,
            post_meal_reading_count=post_count,
            excluded_non_native_count=excluded_non_native,
            excluded_non_cgm_count=excluded_non_cgm,
            deduplicated_removed_count=deduplicated_removed,
            device_id=resolved_device_id,
            devices_present=devices_present,
            native_only=native_only,
            include_non_native=not native_only,
            provenance_filter_mode=filter_mode,
            post_meal_span_minutes=span_minutes,
            max_consecutive_gap_minutes=max_gap_min,
            iauc_mg_dl_min=None,
            iauc_valid=False,
            rejection_reasons=rejection_reasons,
            uncertainty_notes=uncertainty_notes,
            evidence=None,
            evidence_items=[],
        )

    g0 = anchor_point.glucose_mg_dl
    vertices_t = [0.0, *post_times_min]
    vertices_pos_g = [0.0, *[max(p.glucose_mg_dl - g0, 0.0) for p in post_points]]

    iauc = 0.0
    for i in range(len(vertices_t) - 1):
        dt = vertices_t[i + 1] - vertices_t[i]
        iauc += 0.5 * (vertices_pos_g[i] + vertices_pos_g[i + 1]) * dt

    iauc_rounded = round(iauc, 2)

    intervals = [p.sampling_interval_min for p in post_points if p.sampling_interval_min]
    native_interval = intervals[0] if intervals else 15
    expected_post_count = max(MIN_POST_MEAL_READINGS, int(round(POST_MEAL_WINDOW_MIN / native_interval)))
    missingness_pct = round(
        max(0.0, min(100.0, (1.0 - min(1.0, post_count / expected_post_count)) * 100.0)),
        2,
    )

    all_source_refs = (
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
    src_meta = build_source_records_metadata(all_source_refs)
    datasets = tuple(
        sorted({meal_source_dataset, anchor_point.source_dataset, *(p.source_dataset for p in post_points)})
    )

    def _build_meal_ev(
        metric_name: str,
        current_value: float | None,
        unit: str,
        method: str,
        baseline_value: float | None = None,
        delta_val: float | None = None,
    ) -> EvidenceItem:
        return EvidenceItem(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            delta=delta_val,
            unit=unit,
            observation_count=post_count + 1,
            expected_observation_count=expected_post_count + 1,
            window_start=anchor_point.recorded_at,
            window_end=post_points[-1].recorded_at,
            source_datasets=datasets,
            **src_meta,
            calculation_method=method,
            calculation_version=CALCULATION_VERSION,
            missingness_pct=missingness_pct,
            uncertainty_notes=tuple(uncertainty_notes),
        )

    ev_iauc = _build_meal_ev(
        "postprandial_iauc_mg_dl_min",
        iauc_rounded,
        "mg/dL*min",
        "timestamp_positive_trapezoidal_iauc",
        baseline_value=None,
        delta_val=None,
    )
    ev_baseline = _build_meal_ev(
        "pre_meal_baseline_glucose_mg_dl",
        pre_val,
        "mg/dL",
        "nearest_pre_meal_anchor_within_30m",
        baseline_value=pre_val,
        delta_val=None,
    )
    ev_peak = _build_meal_ev(
        "postprandial_peak_excursion_mg_dl",
        peak_post,
        "mg/dL",
        "post_meal_peak_minus_pre_meal_anchor",
        baseline_value=pre_val,
        delta_val=excursion_delta,
    )

    return MealResponseItem(
        meal_id=meal_id,
        logged_at=meal_ts,
        meal_type=meal_type,
        description=description,
        carbs_g=carbs_g,
        timestamp_semantics=resolved_sem,
        calendar_date_comparable=cal_comparable,
        pre_meal_glucose_mg_dl=pre_val,
        pre_meal_recorded_at=anchor_point.recorded_at,
        peak_post_meal_glucose_mg_dl=peak_post,
        excursion_delta_mg_dl=excursion_delta,
        post_meal_reading_count=post_count,
        excluded_non_native_count=excluded_non_native,
        excluded_non_cgm_count=excluded_non_cgm,
        deduplicated_removed_count=deduplicated_removed,
        device_id=resolved_device_id,
        devices_present=devices_present,
        native_only=native_only,
        include_non_native=not native_only,
        provenance_filter_mode=filter_mode,
        post_meal_span_minutes=span_minutes,
        max_consecutive_gap_minutes=max_gap_min,
        iauc_mg_dl_min=iauc_rounded,
        iauc_valid=True,
        rejection_reasons=[],
        uncertainty_notes=uncertainty_notes,
        evidence=ev_iauc,
        evidence_items=[ev_iauc, ev_baseline, ev_peak],
    )


def evaluate_meal_responses(
    meals: Sequence[Meal | dict],
    glucose_readings: Sequence[GlucoseReading | GlucosePoint | dict],
    *,
    native_only: bool = True,
    device_id: str | None = None,
) -> list[MealResponseItem]:
    """Evaluate postprandial responses across a sequence of meals."""
    points, _ = prepare_glucose_points_with_stats(
        glucose_readings, deduplicate_across_devices=False
    )
    cgm_points, _ = filter_cgm_only(points)
    resolve_single_device_cgm_points(cgm_points, device_id=device_id)
    results: list[MealResponseItem] = []
    for idx, meal in enumerate(meals):
        if isinstance(meal, dict):
            m_id = str(meal.get("id") or meal.get("meal_id") or f"meal-{idx}")
            m_ts = ensure_utc_dt(meal["logged_at"])
            m_type = str(meal.get("meal_type") or "unknown")
            m_desc = str(meal.get("description") or "")
            m_carbs = float(meal["carbs_g"]) if meal.get("carbs_g") is not None else None
            m_ds = str(meal.get("source_dataset") or "app_user")
            m_sem = str(meal.get("timestamp_semantics") or "utc_exact")
        else:
            m_id = str(meal.id)
            m_ts = ensure_utc_dt(meal.logged_at)
            m_type = meal.meal_type
            m_desc = meal.description
            m_carbs = meal.carbs_g
            m_ds = meal.source_dataset
            m_sem = getattr(meal, "timestamp_semantics", "utc_exact") or "utc_exact"

        results.append(
            evaluate_single_meal_response(
                meal_id=m_id,
                logged_at=m_ts,
                meal_type=m_type,
                description=m_desc,
                carbs_g=m_carbs,
                meal_source_dataset=m_ds,
                meal_timestamp_semantics=m_sem,
                glucose_readings=points,
                native_only=native_only,
                device_id=device_id,
            )
        )
    return results
