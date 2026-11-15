from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.llm import synthesize_narrative
from app.agents.verifier import verify_agent_draft
from app.analytics import (
    compute_glucose_drift,
    compute_glucose_summary,
    compute_medication_pattern_summary,
    evaluate_meal_responses,
)
from app.models import GlucoseReading, Meal, Medication, MedicationEvent
from app.schemas.analytics import (
    DriftSummaryOut,
    EvidenceItem,
    GlucoseSummaryOut,
    MealResponseItem,
    MedicationPatternSummaryOut,
)
from app.schemas.investigations import AgentObservationOut, VerifierReportOut


class InvestigationGraphState(TypedDict, total=False):
    patient_id: str
    cohort_type: str
    dataset_label: str
    mode: str
    allowed_provenances: list[str] | None
    baseline_method: Literal["nearest_anchor", "pre_window_median"]
    device_id: str | None
    simulate_bad_draft: bool
    readings: list[GlucoseReading]
    meals: list[Meal]
    medications: list[Medication]
    medication_events: list[MedicationEvent]
    summary: GlucoseSummaryOut
    meal_responses: list[MealResponseItem]
    drift: DriftSummaryOut
    meds_summary: MedicationPatternSummaryOut
    observations: list[AgentObservationOut]
    evidence_items: list[EvidenceItem]
    draft: dict[str, Any]
    execution_mode: Literal["gemini", "deterministic_fallback"]
    model_used: str
    fallback_reason: str | None
    verifier_report: VerifierReportOut
    repair_attempts: int


def _supervisor_node(state: InvestigationGraphState) -> dict[str, Any]:
    return {"repair_attempts": 0, "observations": [], "evidence_items": []}


def _data_quality_node(state: InvestigationGraphState) -> dict[str, Any]:
    summary = compute_glucose_summary(
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        device_id=state.get("device_id"),
    )
    cov = summary.coverage
    obs = AgentObservationOut(
        agent_name="data_quality_agent",
        window_start=cov.window_start,
        window_end=cov.window_end,
        finding_summary=(
            f"Analyzed {summary.observation_count} CGM readings (coverage {cov.period_coverage_pct}%, "
            f"missingness {cov.period_missingness_pct}%, allowed_provenances={cov.allowed_provenances})."
        ),
        evidence_items=list(summary.evidence_items),
        observation_count=summary.observation_count,
        missingness_pct=cov.period_missingness_pct,
        deterministic_confidence=cov.deterministic_confidence,
        uncertainty_notes=list(cov.uncertainty_notes),
    )
    return {
        "summary": summary,
        "observations": [*state.get("observations", []), obs],
        "evidence_items": [*state.get("evidence_items", []), *summary.evidence_items],
    }


def _pattern_node(state: InvestigationGraphState) -> dict[str, Any]:
    meals_res = evaluate_meal_responses(
        state["meals"],
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        baseline_method=state.get("baseline_method", "nearest_anchor"),
        device_id=state.get("device_id"),
    )
    drift = compute_glucose_drift(
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        device_id=state.get("device_id"),
    )
    meal_evs: list[EvidenceItem] = []
    for mr in meals_res:
        if mr.iauc_valid and mr.evidence_items:
            meal_evs.extend(mr.evidence_items)
    all_evs = [*meal_evs]
    if drift.evidence is not None:
        all_evs.append(drift.evidence)

    valid_count = sum(1 for m in meals_res if m.iauc_valid)
    summary = state["summary"]
    obs = AgentObservationOut(
        agent_name="pattern_agent",
        window_start=drift.window_start,
        window_end=drift.window_end,
        finding_summary=(
            f"Evaluated {len(meals_res)} meals ({valid_count} valid iAUC windows); "
            f"exploratory drift status is '{drift.status}'."
        ),
        evidence_items=all_evs[:15],
        observation_count=summary.observation_count,
        missingness_pct=summary.coverage.period_missingness_pct,
        deterministic_confidence=drift.deterministic_confidence,
        uncertainty_notes=list(drift.uncertainty_notes),
    )
    return {
        "meal_responses": meals_res,
        "drift": drift,
        "observations": [*state.get("observations", []), obs],
        "evidence_items": [*state.get("evidence_items", []), *all_evs],
    }


def _medication_context_node(state: InvestigationGraphState) -> dict[str, Any]:
    meds_res = compute_medication_pattern_summary(
        state["medications"],
        state["medication_events"],
    )
    summary = state["summary"]
    obs = AgentObservationOut(
        agent_name="medication_context_agent",
        window_start=summary.window_start,
        window_end=summary.window_end,
        finding_summary=(
            f"{meds_res.active_regimen_count} active regimen(s), {meds_res.total_events} event(s), "
            f"adherence_computable={meds_res.adherence_computable}."
        ),
        evidence_items=[],
        observation_count=meds_res.total_events,
        missingness_pct=0.0 if meds_res.adherence_computable else 100.0,
        deterministic_confidence=1.0 if meds_res.adherence_computable else 0.35,
        uncertainty_notes=list(meds_res.uncertainty_notes),
    )
    return {
        "meds_summary": meds_res,
        "observations": [*state.get("observations", []), obs],
    }


def _synthesizer_node(state: InvestigationGraphState) -> dict[str, Any]:
    if state.get("simulate_bad_draft"):
        bad_text = (
            "Your glucose spiked to 312 mg/dL because your lunch caused by insulin resistance "
            "proves that you should increase your dose immediately (statistically significant, p < 0.01)."
        )
        return {
            "draft": {
                "patient_summary": bad_text,
                "clinician_summary": bad_text,
                "clinician_questions": ["Should the patient increase their dose?"],
                "hypotheses": [{"title": "Simulated unsafe draft", "confidence": 0.0}],
            },
            "execution_mode": "deterministic_fallback",
            "model_used": "simulated_unsafe_draft_demo",
            "fallback_reason": "simulated_bad_draft_for_verifier_demo",
        }

    prev_rep = state.get("verifier_report")
    repair_feedback = prev_rep.failed_details if (prev_rep and not prev_rep.passed) else None
    attempts = state.get("repair_attempts", 0)
    if repair_feedback is not None:
        attempts += 1

    draft, exec_mode, model_used, fallback_reason = synthesize_narrative(
        mode=state.get("mode", "auto"),
        cohort_type=state["cohort_type"],
        dataset_label=state.get("dataset_label", state["cohort_type"]),
        summary=state["summary"],
        meal_responses=state["meal_responses"],
        drift=state["drift"],
        meds=state["meds_summary"],
        evidence_items=state["evidence_items"],
        repair_feedback=repair_feedback,
    )
    return {
        "draft": draft,
        "execution_mode": exec_mode,
        "model_used": model_used,
        "fallback_reason": fallback_reason,
        "repair_attempts": attempts,
    }


def _verifier_node(state: InvestigationGraphState) -> dict[str, Any]:
    draft = state["draft"]
    summary = state["summary"]
    meds = state["meds_summary"]
    extra_nums: list[float] = [
        float(summary.coverage.period_coverage_pct),
        float(len([m for m in state["meal_responses"] if m.iauc_valid])),
        float(meds.active_regimen_count),
        float(meds.unknown_count),
    ]
    if meds.observed_taken_pct is not None:
        extra_nums.append(float(meds.observed_taken_pct))
    if summary.mean_glucose_mg_dl is not None:
        extra_nums.extend(
            [
                float(summary.mean_glucose_mg_dl),
                float(summary.tir_pct or 0.0),
                float(summary.tbr_pct or 0.0),
                float(summary.tar_pct or 0.0),
            ]
        )

    rep = verify_agent_draft(
        patient_text=draft.get("patient_summary", ""),
        clinician_text=draft.get("clinician_summary", ""),
        evidence_items=state["evidence_items"],
        meal_responses=state["meal_responses"],
        drift_summary=state["drift"],
        extra_grounded_numbers=extra_nums,
        repair_attempts=state.get("repair_attempts", 0),
    )
    return {"verifier_report": rep}


def _route_after_verifier(state: InvestigationGraphState) -> str:
    rep = state["verifier_report"]
    if rep.passed or state.get("simulate_bad_draft") or state.get("repair_attempts", 0) >= 1:
        return END
    return "synthesizer"


def _build_investigation_graph():
    builder = StateGraph(InvestigationGraphState)
    builder.add_node("supervisor", _supervisor_node)
    builder.add_node("data_quality", _data_quality_node)
    builder.add_node("pattern", _pattern_node)
    builder.add_node("medication_context", _medication_context_node)
    builder.add_node("synthesizer", _synthesizer_node)
    builder.add_node("verifier", _verifier_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "data_quality")
    builder.add_edge("data_quality", "pattern")
    builder.add_edge("pattern", "medication_context")
    builder.add_edge("medication_context", "synthesizer")
    builder.add_edge("synthesizer", "verifier")
    builder.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {"synthesizer": "synthesizer", END: END},
    )
    return builder.compile()


_COMPILED_GRAPH = _build_investigation_graph()


def run_investigation_graph(
    *,
    patient_id: str,
    cohort_type: str,
    dataset_label: str,
    readings: list[GlucoseReading],
    meals: list[Meal],
    medications: list[Medication],
    medication_events: list[MedicationEvent],
    mode: Literal["auto", "gemini", "deterministic_fallback"] = "auto",
    allowed_provenances: list[str] | None = None,
    baseline_method: Literal["nearest_anchor", "pre_window_median"] = "nearest_anchor",
    device_id: str | None = None,
    simulate_bad_draft: bool = False,
) -> InvestigationGraphState:
    """Execute the read-only LangGraph investigation pipeline and return final state."""
    initial_state: InvestigationGraphState = {
        "patient_id": patient_id,
        "cohort_type": cohort_type,
        "dataset_label": dataset_label,
        "mode": mode,
        "allowed_provenances": allowed_provenances,
        "baseline_method": baseline_method,
        "device_id": device_id,
        "simulate_bad_draft": simulate_bad_draft,
        "readings": readings,
        "meals": meals,
        "medications": medications,
        "medication_events": medication_events,
    }
    return _COMPILED_GRAPH.invoke(initial_state)
