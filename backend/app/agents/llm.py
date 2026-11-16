import json
import logging
from typing import Any

from app.core.config import get_settings
from app.schemas.analytics import (
    DriftSummaryOut,
    EvidenceItem,
    GlucoseSummaryOut,
    MealResponseItem,
    MedicationPatternSummaryOut,
)

logger = logging.getLogger(__name__)

DETERMINISTIC_FALLBACK_MODEL = "deterministic_template_v1"


def _is_gemini_key_usable(raw_key: str | None) -> bool:
    if not raw_key:
        return False
    cleaned = raw_key.strip()
    if not cleaned or cleaned.startswith("replace_with_") or cleaned in {"changeme", "none", "null"}:
        return False
    return True


def build_deterministic_narrative(
    *,
    cohort_type: str,
    dataset_label: str,
    summary: GlucoseSummaryOut,
    meal_responses: list[MealResponseItem],
    drift: DriftSummaryOut,
    meds: MedicationPatternSummaryOut,
) -> dict[str, Any]:
    """Build a strictly grounded deterministic narrative (never labeled as AI-generated)."""
    cov = summary.coverage
    used_provs = sorted(
        {
            k
            for ev in summary.evidence_items
            for k, cnt in ev.provenance_counts.items()
            if cnt > 0
        }
    )
    prov_label = ", ".join(used_provs) if used_provs else "none"

    if summary.observation_count > 0:
        patient_parts = [
            f"Deterministic data summary for {dataset_label} ({cohort_type}): "
            f"{summary.observation_count} CGM readings analyzed with provenance [{prov_label}].",
            f"Mean glucose is {summary.mean_glucose_mg_dl} mg/dL, with Time in Range (70-180 mg/dL) at "
            f"{summary.tir_pct}%, Time Below Range (<70 mg/dL) at {summary.tbr_pct}%, and Time Above Range "
            f"(>180 mg/dL) at {summary.tar_pct}%.",
            f"Sensor coverage is {cov.period_coverage_pct}% against the 70% engineering coverage threshold.",
        ]
    else:
        patient_parts = [
            f"Deterministic data summary for {dataset_label} ({cohort_type}): "
            "0 eligible CGM readings were available under the selected provenance filter."
        ]

    valid_meals = [m for m in meal_responses if m.iauc_valid]
    if valid_meals:
        top_meal = max(valid_meals, key=lambda m: abs(m.excursion_delta_mg_dl or 0.0))
        if top_meal.excursion_direction == "postprandial_decline":
            patient_parts.append(
                f"Across {len(valid_meals)} valid meal windows, post-meal readings showed a postprandial_decline "
                f"(excursion delta {top_meal.excursion_delta_mg_dl} mg/dL, iAUC {top_meal.iauc_mg_dl_min} mg/dL*min)."
            )
        else:
            patient_parts.append(
                f"Across {len(valid_meals)} valid meal windows, the largest observed excursion had a delta of "
                f"{top_meal.excursion_delta_mg_dl} mg/dL and iAUC {top_meal.iauc_mg_dl_min} mg/dL*min."
            )

    if drift.status != "insufficient_data":
        patient_parts.append(
            f"Exploratory descriptive comparison indicates {drift.status} "
            f"(baseline mean {drift.baseline_mean_mg_dl} mg/dL vs recent mean {drift.recent_mean_mg_dl} mg/dL, "
            f"delta {drift.delta_mg_dl} mg/dL); this descriptive shift does not establish statistical significance."
        )
    else:
        patient_parts.append(
            "Exploratory glucose drift status is insufficient_data for the selected window."
        )

    if not meds.adherence_computable:
        patient_parts.append(
            f"Medication context lists {meds.active_regimen_count} active regimen(s) and {meds.unknown_count} "
            "clinical-record notation(s) with status='unknown'; adherence percentage is not computable."
        )
    else:
        patient_parts.append(
            f"Medication context lists {meds.active_regimen_count} active regimen(s) with observed taken rate "
            f"{meds.observed_taken_pct}%."
        )

    patient_parts.append(
        "This informational summary is not medical advice; discuss patterns with a qualified clinician."
    )

    clinician_summary = " ".join(patient_parts)
    if not cov.calendar_date_comparable:
        clinician_summary += " Note: timestamps use date_shifted_relative semantics and are not calendar-date comparable across datasets."

    questions = [
        "Do the observed post-meal glucose patterns align with your meal timing and carbohydrate logs?",
        "Are there any sensor wear gaps or medication timing changes that explain the exploratory window shift?",
    ]
    hypotheses = [
        {
            "title": f"Exploratory drift status: {drift.status}",
            "confidence": cov.deterministic_confidence,
            "evidence_metrics": [ev.metric_name for ev in summary.evidence_items[:3]],
        }
    ]
    return {
        "patient_summary": " ".join(patient_parts),
        "clinician_summary": clinician_summary,
        "clinician_questions": questions,
        "hypotheses": hypotheses,
    }


def synthesize_narrative(
    *,
    mode: str,
    cohort_type: str,
    dataset_label: str,
    summary: GlucoseSummaryOut,
    meal_responses: list[MealResponseItem],
    drift: DriftSummaryOut,
    meds: MedicationPatternSummaryOut,
    evidence_items: list[EvidenceItem],
    repair_feedback: list[str] | None = None,
) -> tuple[dict[str, Any], str, str, str | None]:
    """Synthesize patient & clinician summaries via Gemini or deterministic fallback.

    Returns ``(draft_dict, execution_mode, model_used, fallback_reason)``.
    Fallback text is NEVER presented as AI-generated.
    """
    settings = get_settings()
    requested = (mode or settings.agent_execution_mode or "auto").strip().lower()
    key_ok = _is_gemini_key_usable(settings.gemini_api_key)

    if requested == "deterministic_fallback" or (requested == "auto" and not key_ok):
        reason = None if requested == "deterministic_fallback" else "gemini_api_key_not_configured"
        draft = build_deterministic_narrative(
            cohort_type=cohort_type,
            dataset_label=dataset_label,
            summary=summary,
            meal_responses=meal_responses,
            drift=drift,
            meds=meds,
        )
        return draft, "deterministic_fallback", DETERMINISTIC_FALLBACK_MODEL, reason

    if requested == "gemini" and not key_ok:
        raise RuntimeError("GEMINI_API_KEY is not configured in environment variables.")

    # Call Google GenAI SDK with configured GEMINI_MODEL
    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel

        class _HypothesisItem(BaseModel):
            title: str
            confidence: float

        class _GeminiDraftSchema(BaseModel):
            patient_summary: str
            clinician_summary: str
            clinician_questions: list[str]
            hypotheses: list[_HypothesisItem]

        client = genai.Client(api_key=settings.gemini_api_key)
        compact_evidence = [
            {
                "metric_name": ev.metric_name,
                "baseline_value": ev.baseline_value,
                "current_value": ev.current_value,
                "delta": ev.delta,
                "unit": ev.unit,
                "observation_count": ev.observation_count,
                "missingness_pct": ev.missingness_pct,
                "provenance_counts": ev.provenance_counts,
            }
            for ev in evidence_items[:12]
        ]
        metrics_summary = {
            "observation_count": summary.observation_count,
            "mean_glucose_mg_dl": summary.mean_glucose_mg_dl,
            "tir_70_180_pct": summary.tir_pct,
            "tbr_lt_70_pct": summary.tbr_pct,
            "tar_gt_180_pct": summary.tar_pct,
            "cv_pct": summary.cv_pct,
            "period_coverage_pct": summary.coverage.period_coverage_pct,
            "valid_meal_windows": len([m for m in meal_responses if m.iauc_valid]),
            "drift_status": drift.status,
            "drift_baseline_mean_mg_dl": drift.baseline_mean_mg_dl,
            "drift_recent_mean_mg_dl": drift.recent_mean_mg_dl,
            "drift_delta_mg_dl": drift.delta_mg_dl,
            "active_regimen_count": meds.active_regimen_count,
            "adherence_computable": meds.adherence_computable,
            "observed_taken_pct": meds.observed_taken_pct,
        }
        repair_clause = (
            f"\nREPAIR REQUIRED: Your previous draft was REJECTED by the safety verifier with: {repair_feedback}. "
            "Remove or rewrite every flagged number/phrase so ONLY exact numbers from MetricsSummary/Evidence appear in their own metric clause."
            if repair_feedback
            else ""
        )
        prompt = (
            "You are a clinical glycemic data summarizer. Produce strict JSON with keys: "
            "patient_summary (str), clinician_summary (str), clinician_questions (list[str]), hypotheses (list[dict]). "
            "STRICT GROUNDING RULES: "
            "1) Use ONLY numbers present in MetricsSummary or Evidence, OR these exact threshold phrases: "
            "'70-180 mg/dL target range', '<70 mg/dL', '>180 mg/dL', '70% engineering coverage threshold', '14-day clinical guidance'. "
            "2) NEVER write unprovided counts or durations such as 'Type 2', 'Level 1', 'Level 2', '24-hour', '2-hour', '15-minute', '1-day', or '1 logged event'. "
            "3) Always place each number in the same comma/period clause as its metric name (e.g. 'Mean glucose is X mg/dL, Time in Range (70-180 mg/dL) is Y%, Time Below Range (<70 mg/dL) is Z%, Time Above Range (>180 mg/dL) is W%, sensor coverage is C% against the 70% engineering coverage threshold, iAUC is A mg/dL*min'). "
            "4) Include exact non-zero provenance names as `'X CGM readings with provenance [native]'` (or `[dataset_documented]`, `[archive_aligned]`). Do NOT list zero-count provenances (e.g. do NOT write 'dataset_documented is 0'). "
            "5) NEVER make causal claims ('caused by', 'proves that', 'led to', 'drove'), statistical significance claims, or medication dosing advice. "
            f"Cohort: {cohort_type} ({dataset_label}). "
            f"MetricsSummary: {json.dumps(metrics_summary)} "
            f"Evidence: {json.dumps(compact_evidence)}{repair_clause}"
        )
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiDraftSchema,
                temperature=0.1,
            ),
        )
        parsed = json.loads(resp.text or "{}")
        if not isinstance(parsed, dict) or not parsed.get("patient_summary"):
            raise ValueError("Invalid JSON response from Gemini model")
        return (
            {
                "patient_summary": str(parsed.get("patient_summary", "")),
                "clinician_summary": str(parsed.get("clinician_summary", parsed.get("patient_summary", ""))),
                "clinician_questions": list(parsed.get("clinician_questions") or []),
                "hypotheses": list(parsed.get("hypotheses") or []),
            },
            "gemini",
            settings.gemini_model,
            None,
        )
    except Exception as exc:
        logger.warning("Gemini invocation failed (%s); using deterministic_fallback.", exc.__class__.__name__)
        if requested == "gemini":
            raise
        draft = build_deterministic_narrative(
            cohort_type=cohort_type,
            dataset_label=dataset_label,
            summary=summary,
            meal_responses=meal_responses,
            drift=drift,
            meds=meds,
        )
        return draft, "deterministic_fallback", DETERMINISTIC_FALLBACK_MODEL, f"gemini_error:{exc.__class__.__name__}"


def synthesize_plain_text(prompt: str, *, api_key: str, model: str) -> tuple[bool, str, str | None]:
    """Lightweight text synthesis helper using configured google-genai SDK."""
    if not _is_gemini_key_usable(api_key):
        return False, "", "gemini_key_missing"
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        txt = (resp.text or "").strip()
        if not txt:
            return False, "", "empty_response"
        return True, txt, None
    except Exception as exc:
        logger.warning("Gemini plain synthesis fallback: %s", exc.__class__.__name__)
        return False, "", exc.__class__.__name__
