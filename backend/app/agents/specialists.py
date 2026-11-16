"""Phase P3 Complete Domain Specialist Agents & Sub-Agents (§4.2 - §4.8).

Every specialist returns structured AgentResult dicts conforming to the §4.0 contract:
{
  "agent": "meal_nutrition.meal_response_learner",
  "status": "ok | insufficient_data | skipped",
  "findings": [...],
  "cards": [...],
  "needs_clinician": bool,
  "data_used": {...}
}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import (
    compute_glucose_drift,
    compute_glucose_summary,
    compute_medication_pattern_summary,
    evaluate_meal_responses,
    resolve_single_device_cgm_points,
)
from app.models import (
    FoodItem,
    GlucoseReading,
    Meal,
    MealFoodLink,
    Medication,
    MedicationEvent,
    MedicationStock,
    Patient,
    PatientPreferences,
    Recipe,
    RecipeIngredient,
    WellbeingRecord,
)
from app.services.food_catalog import compute_recipe_nutrition, ensure_food_and_recipe_catalog


@dataclass
class SubAgentFinding:
    id: str
    kind: str
    plain_text_template: str
    values: dict[str, Any]
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str = "medium"
    patient_safe: bool = True

    def render(self) -> str:
        try:
            return self.plain_text_template.format(**self.values)
        except Exception:
            return self.plain_text_template


@dataclass
class AgentResult:
    agent: str
    helper_name: str
    status: str  # ok | insufficient_data | skipped
    findings: list[SubAgentFinding] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    needs_clinician: bool = False
    data_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "helper_name": self.helper_name,
            "status": self.status,
            "findings": [{**asdict(f), "rendered_text": f.render()} for f in self.findings],
            "cards": self.cards,
            "needs_clinician": self.needs_clinician,
            "data_used": self.data_used,
        }


# ---------------------------------------------------------------------------
# 1. Rhythm (glucose_patterns) — §4.2
# ---------------------------------------------------------------------------
def run_rhythm_agent(db: Session, patient: Patient, readings: list[GlucoseReading]) -> dict[str, Any]:
    """Run all 6 Rhythm sub-agents: Snapshot, Daily Rhythm, Low-Risk Watcher, High/Spike Watcher, Drift, Steadiness."""
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    target_low = prefs.target_low_mg_dl if prefs else 70.0
    target_high = prefs.target_high_mg_dl if prefs else 180.0

    cgm_pts, _, _ = resolve_single_device_cgm_points(readings)
    summary = compute_glucose_summary(readings, allowed_provenances=frozenset({"native", "dataset_documented"}))
    drift = compute_glucose_drift(readings, allowed_provenances=frozenset({"native", "dataset_documented"}))

    findings: list[SubAgentFinding] = []
    cards: list[dict[str, Any]] = []
    needs_clinician = False

    if not cgm_pts:
        return AgentResult(
            agent="glucose_patterns",
            helper_name="Rhythm",
            status="insufficient_data",
            findings=[
                SubAgentFinding(
                    id="rhy_no_data",
                    kind="insufficient_data",
                    plain_text_template="No recent sensor readings are loaded yet.",
                    values={},
                    confidence="low",
                )
            ],
            data_used={"cgm_readings": 0},
        ).to_dict()

    # Sub-agent 1: Today Snapshot
    latest = cgm_pts[-1]
    prev = cgm_pts[-4] if len(cgm_pts) >= 4 else cgm_pts[0]
    dt_min = max(1.0, (latest.recorded_at - prev.recorded_at).total_seconds() / 60.0)
    rate = (latest.glucose_mg_dl - prev.glucose_mg_dl) / dt_min
    arrow_word = "rising" if rate >= 1.0 else ("falling" if rate <= -1.0 else "steady")
    findings.append(
        SubAgentFinding(
            id="rhy_snapshot",
            kind="today_snapshot",
            plain_text_template="Latest reading: {latest} mg/dL ({arrow}).",
            values={"latest": round(latest.glucose_mg_dl), "arrow": arrow_word},
            confidence="high",
        )
    )

    # Sub-agent 2: Daily Rhythm (hourly medians)
    hour_buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    for p in cgm_pts:
        hour_buckets[p.recorded_at.hour].append(p.glucose_mg_dl)
    hour_medians = {h: round(median(v), 1) for h, v in hour_buckets.items() if v}
    if len(hour_medians) >= 8:
        hi_h = max(hour_medians, key=lambda h: hour_medians[h])
        lo_h = min(hour_medians, key=lambda h: hour_medians[h])
        findings.append(
            SubAgentFinding(
                id="rhy_daily_rhythm",
                kind="daily_rhythm",
                plain_text_template="Sugar tended to be highest around {hi_hour}:00 ({hi_val} mg/dL) and lowest around {lo_hour}:00 ({lo_val} mg/dL).",
                values={"hi_hour": hi_h, "hi_val": round(hour_medians[hi_h]), "lo_hour": lo_h, "lo_val": round(hour_medians[lo_h])},
                confidence="high",
            )
        )

    # Sub-agent 3: Low-Risk Watcher (<70 for >= 15 min) + reassurance nights
    low_episodes: list[tuple[datetime, float]] = []
    in_low = False
    ep_start: datetime | None = None
    ep_min_val = 999.0
    for p in cgm_pts:
        if p.glucose_mg_dl < target_low:
            if not in_low:
                in_low = True
                ep_start = p.recorded_at
                ep_min_val = p.glucose_mg_dl
            else:
                ep_min_val = min(ep_min_val, p.glucose_mg_dl)
        else:
            if in_low and ep_start is not None:
                if (p.recorded_at - ep_start).total_seconds() >= 900:
                    low_episodes.append((ep_start, round(ep_min_val, 1)))
                in_low = False
                ep_start = None
    if in_low and ep_start is not None and (cgm_pts[-1].recorded_at - ep_start).total_seconds() >= 900:
        low_episodes.append((ep_start, round(ep_min_val, 1)))

    nocturnal_lows = [ep for ep in low_episodes if 0 <= ep[0].hour < 6]
    # Reassurance: count trailing nights (00:00-06:00) with zero <70
    night_days: dict[Any, list[float]] = {}
    for p in cgm_pts:
        if 0 <= p.recorded_at.hour < 6:
            night_days.setdefault(p.recorded_at.date(), []).append(p.glucose_mg_dl)
    safe_nights = 0
    for d in sorted(night_days.keys(), reverse=True):
        if min(night_days[d]) >= target_low:
            safe_nights += 1
        else:
            break

    if low_episodes:
        needs_clinician = True
        findings.append(
            SubAgentFinding(
                id="rhy_lows",
                kind="low_risk",
                plain_text_template="{total_lows} low episode(s) under {target_low} mg/dL ({night_lows} overnight). Last {safe_nights} consecutive night(s) stayed above {target_low} mg/dL.",
                values={
                    "total_lows": len(low_episodes),
                    "night_lows": len(nocturnal_lows),
                    "safe_nights": safe_nights,
                    "target_low": round(target_low),
                },
                confidence="high",
            )
        )
    else:
        findings.append(
            SubAgentFinding(
                id="rhy_lows_clear",
                kind="low_risk_reassurance",
                plain_text_template="No lows below {target_low} mg/dL were seen across the last {safe_nights} nights.",
                values={"target_low": round(target_low), "safe_nights": safe_nights},
                confidence="high",
            )
        )

    # Sub-agent 4: High & Spike Watcher (>target_high or >250)
    high_count = sum(1 for p in cgm_pts if p.glucose_mg_dl > target_high)
    very_high = sum(1 for p in cgm_pts if p.glucose_mg_dl > 250.0)
    if summary.mean_glucose_mg_dl is not None and summary.tir_pct is not None:
        findings.append(
            SubAgentFinding(
                id="rhy_summary",
                kind="glucose_summary",
                plain_text_template="Average sugar: {mean} mg/dL, time in target ({tlow}-{thigh}): {tir}% ({high_pts} readings above range, {vhigh_pts} above 250).",
                values={
                    "mean": round(summary.mean_glucose_mg_dl),
                    "tlow": round(target_low),
                    "thigh": round(target_high),
                    "tir": round(summary.tir_pct, 1),
                    "high_pts": high_count,
                    "vhigh_pts": very_high,
                },
                confidence="high",
            )
        )

    # Sub-agent 5: Trend vs Your Normal (Drift)
    if drift.status in ("upward_drift", "downward_drift", "stable") and drift.delta_mg_dl is not None:
        direction_word = "higher" if drift.delta_mg_dl > 0 else ("lower" if drift.delta_mg_dl < 0 else "similar")
        findings.append(
            SubAgentFinding(
                id="rhy_drift",
                kind="drift",
                plain_text_template="Recent week averaged {abs_delta} mg/dL {dir_word} than the earlier window.",
                values={"abs_delta": abs(round(drift.delta_mg_dl)), "dir_word": direction_word},
                confidence="medium",
            )
        )

    # Sub-agent 6: Steadiness (CV)
    if summary.cv_pct is not None:
        label = "Steady" if summary.cv_pct < 36.0 else "Variable"
        findings.append(
            SubAgentFinding(
                id="rhy_steadiness",
                kind="steadiness",
                plain_text_template="Daily stability is {label} (variation {cv}%).",
                values={"label": label, "cv": round(summary.cv_pct, 1)},
                confidence="high",
            )
        )

    cards.append(
        {
            "type": "glucose_summary_card",
            "latest_mg_dl": round(latest.glucose_mg_dl),
            "trend": arrow_word,
            "tir_pct": round(summary.tir_pct, 1) if summary.tir_pct is not None else None,
            "nocturnal_lows": len(nocturnal_lows),
            "safe_nights": safe_nights,
        }
    )

    return AgentResult(
        agent="glucose_patterns",
        helper_name="Rhythm",
        status="ok",
        findings=findings,
        cards=cards,
        needs_clinician=needs_clinician or len(nocturnal_lows) > 0,
        data_used={"cgm_readings": len(cgm_pts), "window": f"{cgm_pts[0].recorded_at.date()}/{cgm_pts[-1].recorded_at.date()}"},
    ).to_dict()


# ---------------------------------------------------------------------------
# 2. Plate (meal_nutrition) — §4.3
# ---------------------------------------------------------------------------
def run_plate_agent(
    db: Session,
    patient: Patient,
    readings: list[GlucoseReading],
    meals: list[Meal],
    medications: list[Medication],
) -> dict[str, Any]:
    """Run Plate sub-agents: Meal Response Learner, Timing Planner, Plate Builder, Budget Swaps."""
    recipes_map = ensure_food_and_recipe_catalog(db)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    is_veg = prefs.vegetarian if prefs else False
    budget = prefs.budget_tier if prefs else "low"

    cgm_pts, _, _ = resolve_single_device_cgm_points(readings)
    evals = evaluate_meal_responses(meals, cgm_pts, allowed_provenances=frozenset({"native", "dataset_documented"}))
    valid_evals = [e for e in evals if e.iauc_valid and e.excursion_delta_mg_dl is not None]

    findings: list[SubAgentFinding] = []
    cards: list[dict[str, Any]] = []

    if not valid_evals:
        findings.append(
            SubAgentFinding(
                id="plt_insufficient",
                kind="insufficient_data",
                plain_text_template="Log 2 meals with sensor readings around mealtime so Plate can learn your personal responses.",
                values={},
                confidence="low",
            )
        )
    else:
        # Sub-agent: My Meal Response Learner grouped by description
        by_dish: dict[str, list[float]] = {}
        for ev in valid_evals:
            by_dish.setdefault(ev.description, []).append(ev.excursion_delta_mg_dl or 0.0)
        dish_avgs = sorted(((mean(v), len(v), k) for k, v in by_dish.items()), key=lambda t: t[0])
        lowest = dish_avgs[0]
        highest = dish_avgs[-1]
        findings.append(
            SubAgentFinding(
                id="plt_meal_learner",
                kind="meal_response_learner",
                plain_text_template="Observed smaller average rise with {low_dish} (+{low_rise} mg/dL, {low_n}x) and higher observed rise with {high_dish} (+{high_rise} mg/dL, {high_n}x).",
                values={
                    "low_dish": lowest[2],
                    "low_rise": round(lowest[0]),
                    "low_n": lowest[1],
                    "high_dish": highest[2],
                    "high_rise": round(highest[0]),
                    "high_n": highest[1],
                },
                confidence="high",
            )
        )

        # Sub-agent: Meal Timing Planner
        eval_by_id = {e.meal_id: e for e in valid_evals}
        early_din = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour < 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
        late_din = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour >= 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
        if early_din and late_din:
            findings.append(
                SubAgentFinding(
                    id="plt_timing",
                    kind="meal_timing_planner",
                    plain_text_template="Dinners before 9:00 PM showed smaller average rises (+{early} mg/dL) than late dinners after 9:00 PM (+{late} mg/dL).",
                    values={"early": round(mean(early_din)), "late": round(mean(late_din))},
                    confidence="high",
                )
            )
        else:
            has_sulfo = any("sulfonylurea" in (m.drug_class or "").lower() for m in medications)
            findings.append(
                SubAgentFinding(
                    id="plt_timing_default",
                    kind="meal_timing_planner",
                    plain_text_template="Spacing meals 4-5 hours apart ({med_note}) is general guidance for steadier daytime curves.",
                    values={"med_note": "aligning breakfast with Gliclazide" if has_sulfo else "with dinner before 8:30 PM"},
                    confidence="medium",
                )
            )

    # Sub-agent: Plate Builder & Local Budget Adapter (compute exact nutrition)
    foods_by_id = {f.id: f for f in db.scalars(select(FoodItem)).all()}
    ings_by_recipe: dict[uuid.UUID, list[tuple[float, FoodItem]]] = {}
    for ing in db.scalars(select(RecipeIngredient)).all():
        if ing.food_item_id in foods_by_id:
            ings_by_recipe.setdefault(ing.recipe_id, []).append((ing.grams, foods_by_id[ing.food_item_id]))

    scored_recipes: list[tuple[float, Recipe, Any]] = []
    for rec in recipes_map.values():
        if rec.slot in ("suhoor", "iftar"):
            continue
        if is_veg and "vegetarian" not in (rec.tags or []):
            continue
        if budget == "low" and rec.cost_tier == "high":
            continue
        nut = compute_recipe_nutrition(ings_by_recipe.get(rec.id, []))
        scored_recipes.append((nut.estimated_gl, rec, nut))
    scored_recipes.sort(key=lambda t: t[0])

    for _, rec, nut in scored_recipes[:3]:
        cards.append(
            {
                "type": "meal_card",
                "recipe_id": str(rec.id),
                "name": rec.name,
                "slot": rec.slot,
                "image_url": rec.image_url,
                "carbs_g": nut.carbs_g,
                "sugar_g": nut.sugar_g,
                "fibre_g": nut.fibre_g,
                "gl_band": nut.gl_band,
            }
        )

    findings.append(
        SubAgentFinding(
            id="plt_swap",
            kind="local_budget_adapter",
            plain_text_template="Budget-friendly swap option: replace half of white rice with cooked chana daal and kachumber salad to add fibre.",
            values={},
            confidence="high",
        )
    )

    return AgentResult(
        agent="meal_nutrition",
        helper_name="Plate",
        status="ok" if valid_evals else "insufficient_data",
        findings=findings,
        cards=cards,
        needs_clinician=False,
        data_used={"meals_evaluated": len(meals), "valid_meal_windows": len(valid_evals), "recipes_available": len(recipes_map)},
    ).to_dict()


# ---------------------------------------------------------------------------
# 3. Dose Diary (medication) — §4.4
# ---------------------------------------------------------------------------
def run_dose_diary_agent(
    db: Session,
    patient: Patient,
    medications: list[Medication],
    med_events: list[MedicationEvent],
) -> dict[str, Any]:
    """Run Dose Diary sub-agents: Regimen Reader, Timing Companion, Logged Patterns, Low-Risk Flag, Refill Tracker."""
    med_summary = compute_medication_pattern_summary(medications, med_events)
    findings: list[SubAgentFinding] = []
    cards: list[dict[str, Any]] = []
    needs_clinician = False

    if not medications:
        return AgentResult(
            agent="medication",
            helper_name="Dose Diary",
            status="insufficient_data",
            findings=[
                SubAgentFinding(
                    id="dose_none",
                    kind="insufficient_data",
                    plain_text_template="No active diabetes medicines recorded yet.",
                    values={},
                    confidence="low",
                )
            ],
            data_used={"medications": 0},
        ).to_dict()

    # Sub-agent: Regimen Reader & Low-Risk Flag
    med_labels: list[str] = []
    hypo_risk_meds: list[str] = []
    for m in medications:
        med_labels.append(f"{m.medication_name} {m.recorded_dose or ''} ({m.prescribed_schedule or 'daily'})".strip())
        dc = (m.drug_class or "").lower()
        nm = m.medication_name.lower()
        if any(k in dc or k in nm for k in ("sulfonylurea", "gliclazide", "glimepiride", "insulin", "meglitinide", "repaglinide")):
            hypo_risk_meds.append(m.medication_name)

    findings.append(
        SubAgentFinding(
            id="dose_regimen",
            kind="regimen_reader",
            plain_text_template="Active medicines recorded: {regimen_count} ({names}).",
            values={"regimen_count": len(medications), "names": ", ".join(med_labels)},
            confidence="high",
        )
    )

    if hypo_risk_meds:
        needs_clinician = True
        findings.append(
            SubAgentFinding(
                id="dose_hypo_flag",
                kind="low_risk_medicine_flag",
                plain_text_template="{meds} can increase low-sugar risk; keep fast-acting sugar handy and ask your doctor before changing meal or dose schedules.",
                values={"meds": ", ".join(hypo_risk_meds)},
                confidence="high",
            )
        )

    # Sub-agent: Logged-Dose Patterns (strictly logged vs not logged, NEVER infer non-adherence)
    logged_taken = sum(1 for e in med_events if e.status == "taken")
    logged_other = sum(1 for e in med_events if e.status in ("missed", "delayed", "skipped"))
    findings.append(
        SubAgentFinding(
            id="dose_events",
            kind="logged_dose_patterns",
            plain_text_template="Dose diary logs: {taken} marked taken and {other} marked skipped/delayed ({total} total logs).",
            values={"taken": logged_taken, "other": logged_other, "total": med_summary.total_events},
            confidence="high",
        )
    )

    # Sub-agent: Refill Tracker
    med_ids = [m.id for m in medications]
    stocks = list(db.scalars(select(MedicationStock).where(MedicationStock.medication_id.in_(med_ids))).all())
    med_by_id = {m.id: m for m in medications}
    for st in stocks:
        days_left = int(st.units_on_hand // st.daily_units)
        m_name = med_by_id[st.medication_id].medication_name
        if days_left <= 10:
            findings.append(
                SubAgentFinding(
                    id=f"dose_refill_{st.medication_id.hex[:6]}",
                    kind="refill_tracker",
                    plain_text_template="Refill check: about {days_left} days of {med} left ({units} units on hand).",
                    values={"days_left": days_left, "med": m_name, "units": round(st.units_on_hand)},
                    confidence="high",
                )
            )

    cards.append(
        {
            "type": "medication_summary_card",
            "regimens": med_labels,
            "hypo_risk_meds": hypo_risk_meds,
            "taken_logs": logged_taken,
            "other_logs": logged_other,
        }
    )

    return AgentResult(
        agent="medication",
        helper_name="Dose Diary",
        status="ok",
        findings=findings,
        cards=cards,
        needs_clinician=needs_clinician,
        data_used={"medications": len(medications), "events": len(med_events)},
    ).to_dict()


# ---------------------------------------------------------------------------
# 4. Kindred (wellbeing) — §4.5
# ---------------------------------------------------------------------------
def run_kindred_agent(
    db: Session,
    patient: Patient,
    readings: list[GlucoseReading],
    wellbeing: list[WellbeingRecord],
    *,
    user_mentions_sick: bool = False,
) -> dict[str, Any]:
    """Run Kindred sub-agents: Check-in Reader, Co-occurrence, Distress Screener, Gentle Mode, Sick-Day Helper."""
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    gentle_mode = prefs.gentle_mode if prefs else False

    findings: list[SubAgentFinding] = []
    cards: list[dict[str, Any]] = []
    needs_clinician = False

    if not wellbeing and not user_mentions_sick:
        return AgentResult(
            agent="wellbeing",
            helper_name="Kindred",
            status="insufficient_data",
            findings=[
                SubAgentFinding(
                    id="kin_no_data",
                    kind="insufficient_data",
                    plain_text_template="No wellbeing check-ins logged yet. A 20-second mood & sleep check-in helps spot patterns.",
                    values={},
                    confidence="low",
                )
            ],
            data_used={"wellbeing_days": 0, "gentle_mode": gentle_mode},
        ).to_dict()

    if wellbeing:
        poor_sleep_dates = {
            w.logged_at.date()
            for w in wellbeing
            if (w.sleep_hours is not None and w.sleep_hours < 6.0) or (w.stress_score is not None and w.stress_score >= 4)
        }
        good_days = len(wellbeing) - len(poor_sleep_dates)

        # Compute co-occurring morning glucose (06:00-11:00) on poor-sleep/high-stress vs calmer days (NO causal claim!)
        cgm_pts, _, _ = resolve_single_device_cgm_points(readings)
        rough_morning = [p.glucose_mg_dl for p in cgm_pts if p.recorded_at.date() in poor_sleep_dates and 6 <= p.recorded_at.hour <= 11]
        calm_dates = {w.logged_at.date() for w in wellbeing} - poor_sleep_dates
        calm_morning = [p.glucose_mg_dl for p in cgm_pts if p.recorded_at.date() in calm_dates and 6 <= p.recorded_at.hour <= 11]

        if rough_morning and calm_morning:
            diff = round(mean(rough_morning) - mean(calm_morning))
            findings.append(
                SubAgentFinding(
                    id="kin_co_occurrence",
                    kind="co_occurrence",
                    plain_text_template="Across {days} check-in days: on {rough_days} higher-stress or short-sleep day(s), morning sugar averaged {rough_avg} mg/dL vs {calm_avg} mg/dL on calmer days ({diff} mg/dL difference, observed together).",
                    values={
                        "days": len(wellbeing),
                        "rough_days": len(poor_sleep_dates),
                        "rough_avg": round(mean(rough_morning)),
                        "calm_avg": round(mean(calm_morning)),
                        "diff": f"+{diff}" if diff >= 0 else str(diff),
                    },
                    confidence="medium",
                )
            )
        else:
            findings.append(
                SubAgentFinding(
                    id="kin_counts",
                    kind="checkin_summary",
                    plain_text_template="{days} check-in days logged ({rough} higher-stress/short-sleep, {calm} steady).",
                    values={"days": len(wellbeing), "rough": len(poor_sleep_dates), "calm": max(0, good_days)},
                    confidence="high",
                )
            )

    sick_days = [w for w in wellbeing if w.illness_flag is True]
    if user_mentions_sick or sick_days:
        needs_clinician = True
        findings.append(
            SubAgentFinding(
                id="kin_sick_day",
                kind="sick_day_helper",
                plain_text_template="Sick-day guidance: sip fluids regularly, check sugar every 3-4 hours, keep taking prescribed diabetes tablets unless your doctor advises otherwise, and contact a clinician if vomiting or sugars stay above 250 mg/dL.",
                values={},
                confidence="high",
            )
        )
        cards.append(
            {
                "type": "sick_day_checklist",
                "items": [
                    "Stay hydrated with water or sugar-free fluids",
                    "Check blood sugar more often (every 3–4 hours)",
                    "Never stop basal insulin or tablets without medical advice",
                    "Seek medical help urgently if unable to keep fluids down or persistent >250 mg/dL",
                ],
            }
        )

    return AgentResult(
        agent="wellbeing",
        helper_name="Kindred",
        status="ok",
        findings=findings,
        cards=cards,
        needs_clinician=needs_clinician,
        data_used={"wellbeing_days": len(wellbeing), "gentle_mode": gentle_mode},
    ).to_dict()


# ---------------------------------------------------------------------------
# 5. Roza Guide (fasting) — §4.6 IDF-DAR 2021 Ramadan helper
# ---------------------------------------------------------------------------
def compute_idf_dar_risk(
    *,
    diabetes_type: str,
    uses_insulin: bool,
    uses_sulfonylurea: bool,
    recent_hypo_count: int,
    egfr: float | None = None,
    pregnant: bool = False,
) -> dict[str, Any]:
    """Deterministic IDF-DAR 2021 risk stratification (always paired with clinician review note)."""
    score = 0.0
    reasons: list[str] = []
    if diabetes_type == "T1D":
        score += 3.0
        reasons.append("Type 1 diabetes")
    else:
        score += 1.0
    if uses_insulin:
        score += 2.0
        reasons.append("Insulin therapy")
    if uses_sulfonylurea:
        score += 1.5
        reasons.append("Sulfonylurea therapy (e.g., Gliclazide)")
    if recent_hypo_count >= 2:
        score += 3.0
        reasons.append(f"{recent_hypo_count} recent low-sugar episodes")
    elif recent_hypo_count == 1:
        score += 1.5
        reasons.append("1 recent low-sugar episode")
    if egfr is not None and egfr < 60:
        score += 2.5
        reasons.append(f"Reduced kidney filtration (eGFR {round(egfr)})")
    if pregnant:
        score += 6.5
        reasons.append("Pregnancy")

    if score >= 6.5:
        tier = "high"
        advice = "IDF-DAR high-risk category: discuss whether fasting is safe with your doctor before Ramadan."
    elif score >= 3.5:
        tier = "moderate"
        advice = "IDF-DAR moderate-risk category: plan pre-Ramadan review with your doctor to review meal & medicine timing."
    else:
        tier = "low"
        advice = "IDF-DAR lower-risk category: still check your fasting plan and testing times with your doctor."

    return {
        "score": round(score, 1),
        "risk_tier": tier,
        "reasons": reasons,
        "summary": advice,
        "break_fast_rules": [
            "Break the fast immediately if sugar drops below 70 mg/dL.",
            "Break the fast immediately if sugar rises above 300 mg/dL.",
            "Break the fast if you feel shaky, dizzy, sweaty, confused, or acutely unwell.",
        ],
    }


def run_roza_guide_agent(
    db: Session,
    patient: Patient,
    readings: list[GlucoseReading],
    medications: list[Medication],
) -> dict[str, Any]:
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))
    city = prefs.city if prefs else "Lahore"
    uses_insulin = any("insulin" in (m.drug_class or "").lower() or "insulin" in m.medication_name.lower() for m in medications)
    uses_sulfo = any("sulfonylurea" in (m.drug_class or "").lower() or "gliclazide" in m.medication_name.lower() for m in medications)

    cgm_pts, _, _ = resolve_single_device_cgm_points(readings)
    hypo_days = len({p.recorded_at.date() for p in cgm_pts if p.glucose_mg_dl < 70.0})
    idf = compute_idf_dar_risk(
        diabetes_type=patient.diabetes_type,
        uses_insulin=uses_insulin,
        uses_sulfonylurea=uses_sulfo,
        recent_hypo_count=hypo_days,
    )

    recipes_map = ensure_food_and_recipe_catalog(db)
    suhoor = recipes_map.get("suhoor-dalia-eggs-dahi")
    iftar = recipes_map.get("iftar-1-date-chana-tikka")

    findings = [
        SubAgentFinding(
            id="roza_risk",
            kind="idf_dar_risk",
            plain_text_template="Ramadan planning ({city}): {tier} IDF-DAR risk tier ({score} points). {advice} Medicines during Ramadan often need adjustments that only your doctor can prescribe.",
            values={"city": city, "tier": idf["risk_tier"], "score": idf["score"], "advice": idf["summary"]},
            confidence="high",
        )
    ]
    cards = [
        {
            "type": "ramadan_plan_card",
            "city": city,
            "risk_tier": idf["risk_tier"],
            "score": idf["score"],
            "break_fast_rules": idf["break_fast_rules"],
            "suhoor_recipe_id": str(suhoor.id) if suhoor else None,
            "suhoor_name": suhoor.name if suhoor else "Suhoor dalia + eggs",
            "iftar_recipe_id": str(iftar.id) if iftar else None,
            "iftar_name": iftar.name if iftar else "1 date + chana chaat + chicken tikka",
            "check_times": ["Mid-day", "Pre-Iftar", "2 hours post-Iftar"],
        }
    ]
    return AgentResult(
        agent="fasting",
        helper_name="Roza Guide",
        status="ok",
        findings=findings,
        cards=cards,
        needs_clinician=idf["risk_tier"] in ("moderate", "high"),
        data_used={"city": city, "hypo_days": hypo_days},
    ).to_dict()


# ---------------------------------------------------------------------------
# 6. Visit Notes (visit_prep) — §4.8
# ---------------------------------------------------------------------------
def run_visit_notes_agent(
    rhythm_res: dict[str, Any],
    plate_res: dict[str, Any],
    dose_res: dict[str, Any],
    kindred_res: dict[str, Any],
    roza_res: dict[str, Any],
) -> dict[str, Any]:
    """Generate 3-5 patient-specific clinician questions with plain 'Why?' explanations."""
    questions: list[dict[str, str]] = []

    rhy_card = next((c for c in rhythm_res.get("cards", []) if c.get("type") == "glucose_summary_card"), {})
    if rhy_card.get("nocturnal_lows", 0) > 0:
        dose_card = next((c for c in dose_res.get("cards", []) if c.get("type") == "medication_summary_card"), {})
        med_str = ", ".join(dose_card.get("hypo_risk_meds") or ["my current diabetes medicine"])
        questions.append(
            {
                "question": f"I had {rhy_card['nocturnal_lows']} overnight low(s) below 70 mg/dL while taking {med_str}. Should we review my evening routine or medicine timing?",
                "why": f"Observed {rhy_card['nocturnal_lows']} overnight episode(s) under 70 mg/dL in your recent sensor window.",
            }
        )

    for f in plate_res.get("findings", []):
        if f.get("kind") == "meal_response_learner":
            vals = f.get("values", {})
            questions.append(
                {
                    "question": f"My meals with {vals.get('high_dish')} had larger average rises (+{vals.get('high_rise')} mg/dL). What portion or timing swaps fit my plan best?",
                    "why": f"Compared across {vals.get('high_n', 1)} logged meals vs smaller rises (+{vals.get('low_rise')} mg/dL) with {vals.get('low_dish')}.",
                }
            )
            break

    for f in plate_res.get("findings", []):
        if f.get("kind") == "meal_timing_planner" and "early" in f.get("values", {}):
            vals = f.get("values", {})
            questions.append(
                {
                    "question": f"Dinners after 9 PM averaged +{vals['late']} mg/dL vs +{vals['early']} mg/dL before 9 PM. How should my evening medicines fit if I eat late?",
                    "why": "Pattern observed from your logged dinner timestamps and post-meal readings.",
                }
            )
            break

    for f in kindred_res.get("findings", []):
        if f.get("kind") == "co_occurrence":
            vals = f.get("values", {})
            questions.append(
                {
                    "question": f"On my {vals.get('rough_days')} short-sleep or stressful days, morning sugars averaged {vals.get('rough_avg')} mg/dL. What realistic support would help on busy weeks?",
                    "why": f"Observed {vals.get('diff')} mg/dL morning difference across {vals.get('days')} check-in days.",
                }
            )
            break

    roza_card = next((c for c in roza_res.get("cards", []) if c.get("type") == "ramadan_plan_card"), None)
    if roza_card and len(questions) < 5:
        questions.append(
            {
                "question": f"My Ramadan fasting screening showed {roza_card['risk_tier']} risk. Can we review safe meal and medicine adjustments before fasting?",
                "why": f"Based on IDF-DAR 2021 risk criteria ({roza_card['score']} points).",
            }
        )

    if len(questions) < 3 and rhy_card.get("tir_pct") is not None:
        questions.append(
            {
                "question": f"My recent time in target (70–180 mg/dL) is {rhy_card['tir_pct']}%. What target range makes the most sense for me right now?",
                "why": "Calculated from your recent sensor readings against standard 70–180 mg/dL targets.",
            }
        )

    findings = [
        SubAgentFinding(
            id="vn_questions",
            kind="visit_questions",
            plain_text_template="Prepared {n} personal discussion questions for your next doctor visit.",
            values={"n": len(questions)},
            confidence="high",
        )
    ]

    return AgentResult(
        agent="visit_prep",
        helper_name="Visit Notes",
        status="ok",
        findings=findings,
        cards=[{"type": "visit_questions_card", "questions": questions[:5]}],
        needs_clinician=False,
        data_used={"question_count": len(questions[:5])},
    ).to_dict()
