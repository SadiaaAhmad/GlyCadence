"""Google Cloud ADK wrapper for GlyCadence (for `adk web` / Vertex AI rubric compatibility).

This standalone workspace exposes GlyCadence's evidence-grounded specialist checks
as ADK tools without modifying the core FastAPI + LangGraph production backend.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from google.adk.agents import Agent
except ImportError:  # pragma: no cover - allows inspecting/testing without google-adk installed
    class Agent:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)


def check_glucose_target_status(latest_mg_dl: float, target_low: float = 70.0, target_high: float = 180.0) -> dict[str, Any]:
    """Classify a blood glucose reading against ADA target bounds (70-180 mg/dL) with urgent safety rules."""
    if latest_mg_dl < 70:
        return {
            "status": "below_target_urgent",
            "reading_mg_dl": latest_mg_dl,
            "guidance": "Follow the 15-15 rule: take 15g fast-acting sugar (half glass juice or 3 glucose tablets) and recheck in 15 minutes.",
        }
    if latest_mg_dl >= 250:
        return {
            "status": "high_urgent",
            "reading_mg_dl": latest_mg_dl,
            "guidance": "Do NOT take fast sugar. Hydrate with plain water, avoid vigorous exercise, and contact your doctor if feeling unwell.",
        }
    if latest_mg_dl > target_high:
        return {
            "status": "above_target",
            "reading_mg_dl": latest_mg_dl,
            "guidance": "Above target (70-180 mg/dL). Sip water, consider a gentle 15-minute post-meal walk if feeling well, and monitor.",
        }
    return {
        "status": "in_target",
        "reading_mg_dl": latest_mg_dl,
        "guidance": f"Within target range ({target_low:.0f}-{target_high:.0f} mg/dL). Keep up your steady routine.",
    }


def evaluate_meal_suitability(carbs_g: float, sugar_g: float, fibre_g: float, latest_mg_dl: float | None = None) -> dict[str, Any]:
    """Evaluate a meal's estimated glycaemic load and diabetes suitability from nutrition totals."""
    net_carbs = max(0.0, carbs_g - fibre_g)
    est_gl = round((50.0 * net_carbs) / 100.0, 1)
    band = "Low" if est_gl <= 10 else ("Medium" if est_gl <= 19 else "High")
    note = f"{band} glycaemic load (est. GL {est_gl}, {carbs_g}g carbs, {sugar_g}g sugar, {fibre_g}g fibre)."
    if latest_mg_dl is not None and latest_mg_dl > 180:
        note += f" Because your latest reading is {latest_mg_dl:.0f} mg/dL, keep starchy portions modest."
    return {"gl_band": band, "estimated_gl": est_gl, "guidance": note}


def check_pre_workout_safety(glucose_mg_dl: float) -> dict[str, Any]:
    """Run Mover exercise pre-workout glucose safety check."""
    if glucose_mg_dl < 100:
        return {"cleared": False, "action": "Eat a 15g fast-acting carb snack and recheck before exercising."}
    if glucose_mg_dl >= 250:
        return {"cleared": False, "action": "Skip vigorous cardio; choose gentle seated mobility/stretching only and hydrate."}
    return {"cleared": True, "action": "Safe zone (100-249 mg/dL) for brisk walking or strength training."}


def log_wellbeing_for_doctor(stress_1_to_5: int, fatigue_1_to_5: int, mood_note: str = "") -> dict[str, Any]:
    """Summarize mental and physical wellbeing check-in for the patient's Doctor Visit Report."""
    flagged = stress_1_to_5 >= 4 or any(w in mood_note.lower() for w in ("tingl", "numb", "blur", "dizzy", "burnout"))
    return {
        "stress": stress_1_to_5,
        "fatigue": fatigue_1_to_5,
        "flagged_for_doctor": flagged,
        "visit_question": "Could stress, sleep, or diabetes distress be affecting my daily readings, and what support helps?",
    }


root_agent = Agent(
    name="glycadence_cadie_adk",
    model=os.getenv("ADK_GEMINI_MODEL", "gemini-2.5-flash"),
    description="GlyCadence Diabetes & Wellbeing Companion (Google ADK + Vertex AI wrapper).",
    instruction=(
        "You are Cadie, GlyCadence's warm, evidence-grounded diabetes companion. "
        "Always call the deterministic safety/nutrition tools before giving guidance. "
        "Never diagnose, never prescribe or change medication doses, and never recommend fast sugar when glucose is >= 180 mg/dL."
    ),
    tools=[
        check_glucose_target_status,
        evaluate_meal_suitability,
        check_pre_workout_safety,
        log_wellbeing_for_doctor,
    ],
)
