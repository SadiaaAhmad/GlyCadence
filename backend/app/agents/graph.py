from datetime import datetime, timezone
import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.llm import synthesize_narrative
from app.agents.verifier import verify_agent_draft
from app.analytics import (
    compute_glucose_drift,
    compute_glucose_summary,
    compute_medication_pattern_summary,
    evaluate_meal_responses,
)
from app.models import GlucoseReading, Meal, Medication, MedicationEvent, WellbeingRecord
from app.schemas.analytics import (
    DriftSummaryOut,
    EvidenceItem,
    GlucoseSummaryOut,
    MealResponseItem,
    MedicationPatternSummaryOut,
)
from app.schemas.investigations import AgentObservationOut, AgentTraceStep, VerifierReportOut


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    wellbeing_records: list[WellbeingRecord]
    summary: GlucoseSummaryOut
    meal_responses: list[MealResponseItem]
    drift: DriftSummaryOut
    meds_summary: MedicationPatternSummaryOut
    wellbeing_summary_text: str
    wellbeing_days_logged: int
    diet_summary_text: str
    cross_signal_findings: list[str]
    observations: Annotated[list[AgentObservationOut], operator.add]
    evidence_items: Annotated[list[EvidenceItem], operator.add]
    trace: Annotated[list[AgentTraceStep], operator.add]
    draft: dict[str, Any]
    execution_mode: Literal["gemini", "deterministic_fallback"]
    model_used: str
    fallback_reason: str | None
    verifier_report: VerifierReportOut
    repair_attempts: int


def _supervisor_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    ended = _utc_now()
    step = AgentTraceStep(
        node="supervisor",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=f"Dispatched investigation for {state['dataset_label']} ({state['cohort_type']}).",
        evidence_count=0,
    )
    return {
        "repair_attempts": 0,
        "trace": [step],
    }


def _data_quality_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    summary = compute_glucose_summary(
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        device_id=state.get("device_id"),
    )
    cov = summary.coverage
    finding = (
        f"Analyzed {summary.observation_count} CGM readings (coverage {cov.period_coverage_pct}%, "
        f"missingness {cov.period_missingness_pct}%, allowed_provenances={cov.allowed_provenances})."
    )
    obs = AgentObservationOut(
        agent_name="data_quality",
        window_start=cov.window_start,
        window_end=cov.window_end,
        finding_summary=finding,
        evidence_items=list(summary.evidence_items),
        observation_count=summary.observation_count,
        missingness_pct=cov.period_missingness_pct,
        deterministic_confidence=cov.deterministic_confidence,
        uncertainty_notes=list(cov.uncertainty_notes),
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="data_quality",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=finding,
        evidence_count=len(summary.evidence_items),
    )
    return {
        "summary": summary,
        "observations": [obs],
        "evidence_items": list(summary.evidence_items),
        "trace": [step],
    }


def _pattern_watcher_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    summary = state["summary"]
    drift = compute_glucose_drift(
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        device_id=state.get("device_id"),
    )
    evs: list[EvidenceItem] = [drift.evidence] if drift.evidence is not None else []
    finding = (
        f"Mean glucose {summary.mean_glucose_mg_dl} mg/dL (TIR {summary.tir_pct}%, CV {summary.cv_pct}%); "
        f"exploratory drift vs personal baseline is '{drift.status}'."
    )
    obs = AgentObservationOut(
        agent_name="pattern_watcher",
        window_start=drift.window_start,
        window_end=drift.window_end,
        finding_summary=finding,
        evidence_items=evs,
        observation_count=summary.observation_count,
        missingness_pct=summary.coverage.period_missingness_pct,
        deterministic_confidence=drift.deterministic_confidence,
        uncertainty_notes=list(drift.uncertainty_notes),
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="pattern_watcher",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=finding,
        evidence_count=len(evs),
    )
    return {
        "drift": drift,
        "observations": [obs],
        "evidence_items": evs,
        "trace": [step],
    }


def _diet_nutrition_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    meals_res = evaluate_meal_responses(
        state["meals"],
        state["readings"],
        allowed_provenances=state.get("allowed_provenances"),
        baseline_method=state.get("baseline_method", "nearest_anchor"),
        device_id=state.get("device_id"),
    )
    meal_evs: list[EvidenceItem] = []
    valid_meals: list[MealResponseItem] = []
    for mr in meals_res:
        if mr.iauc_valid:
            valid_meals.append(mr)
            if mr.evidence_items:
                meal_evs.extend(mr.evidence_items)

    higher_resp = [m for m in valid_meals if (m.excursion_delta_mg_dl or 0.0) >= 30.0]
    lower_resp = [m for m in valid_meals if (m.excursion_delta_mg_dl or 0.0) < 30.0]
    if valid_meals:
        diet_text = (
            f"Evaluated {len(valid_meals)} valid meal window(s): "
            f"Higher observed glucose response (based on {len(higher_resp)} logged meals); "
            f"Lower observed glucose response (based on {len(lower_resp)} logged meals)."
        )
    else:
        diet_text = f"Evaluated {len(meals_res)} logged meals; 0 had sufficient post-meal CGM coverage for iAUC."

    summary = state["summary"]
    obs = AgentObservationOut(
        agent_name="diet_nutrition",
        window_start=summary.window_start,
        window_end=summary.window_end,
        finding_summary=diet_text,
        evidence_items=meal_evs[:15],
        observation_count=len(meals_res),
        missingness_pct=0.0 if valid_meals else 100.0,
        deterministic_confidence=0.85 if valid_meals else 0.3,
        uncertainty_notes=["Neutral descriptive meal response summary only; not dietary advice."],
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="diet_nutrition",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=diet_text,
        evidence_count=len(meal_evs),
    )
    return {
        "meal_responses": meals_res,
        "diet_summary_text": diet_text,
        "observations": [obs],
        "evidence_items": meal_evs,
        "trace": [step],
    }


def _medication_analyst_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    meds_res = compute_medication_pattern_summary(
        state["medications"],
        state["medication_events"],
    )
    summary = state["summary"]
    finding = (
        f"{meds_res.active_regimen_count} active regimen(s), {meds_res.total_events} event(s), "
        f"adherence_computable={meds_res.adherence_computable}."
    )
    obs = AgentObservationOut(
        agent_name="medication_analyst",
        window_start=summary.window_start,
        window_end=summary.window_end,
        finding_summary=finding,
        evidence_items=[],
        observation_count=meds_res.total_events,
        missingness_pct=0.0 if meds_res.adherence_computable else 100.0,
        deterministic_confidence=1.0 if meds_res.adherence_computable else 0.35,
        uncertainty_notes=list(meds_res.uncertainty_notes),
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="medication_analyst",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=finding,
        evidence_count=0,
    )
    return {
        "meds_summary": meds_res,
        "observations": [obs],
        "trace": [step],
    }


def _wellbeing_companion_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    records = state.get("wellbeing_records") or []
    summary = state["summary"]
    if not records:
        wb_text = "No wellbeing check-ins logged in this window."
        days_logged = 0
    else:
        logged_days = {r.logged_at.date() for r in records}
        high_stress_days = {r.logged_at.date() for r in records if r.stress_score is not None and r.stress_score >= 4}
        high_fatigue_days = {r.logged_at.date() for r in records if r.fatigue_score is not None and r.fatigue_score >= 4}
        short_sleep_days = {
            r.logged_at.date()
            for r in records
            if (r.sleep_hours is not None and r.sleep_hours < 6.0)
            or (r.sleep_quality is not None and r.sleep_quality <= 2)
        }
        illness_days = {r.logged_at.date() for r in records if r.illness_flag is True}
        days_logged = len(logged_days)
        wb_text = (
            f"Wellbeing co-occurrence summary ({days_logged} day(s) with check-ins): "
            f"elevated stress (>=4/5) on {len(high_stress_days)} day(s), "
            f"elevated fatigue (>=4/5) on {len(high_fatigue_days)} day(s), "
            f"short/low-quality sleep on {len(short_sleep_days)} day(s), "
            f"illness flagged on {len(illness_days)} day(s). Co-occurrence only; not causal."
        )

    obs = AgentObservationOut(
        agent_name="wellbeing_companion",
        window_start=summary.window_start,
        window_end=summary.window_end,
        finding_summary=wb_text,
        evidence_items=[],
        observation_count=len(records),
        missingness_pct=0.0 if records else 100.0,
        deterministic_confidence=0.8 if records else 0.25,
        uncertainty_notes=["Wellbeing check-ins reflect self-reported co-occurrence only, never causation."],
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="wellbeing_companion",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=wb_text,
        evidence_count=0,
    )
    return {
        "wellbeing_summary_text": wb_text,
        "wellbeing_days_logged": days_logged,
        "observations": [obs],
        "trace": [step],
    }


def _cross_signal_orchestrator_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    summary = state["summary"]
    drift = state["drift"]
    meals_res = state.get("meal_responses", [])
    meds_res = state["meds_summary"]
    wb_days = state.get("wellbeing_days_logged", 0)
    all_evs = state.get("evidence_items", [])

    findings: list[str] = []
    if drift.evidence is not None and drift.status in {"upward_drift", "downward_drift"}:
        findings.append(
            f"Glycemic window shift ({drift.status}, delta {drift.delta_mg_dl} mg/dL, "
            f"evidence={drift.evidence.metric_name}) observed during monitoring window."
        )
    elif summary.mean_glucose_mg_dl is not None:
        findings.append(
            f"Mean glucose {summary.mean_glucose_mg_dl} mg/dL (TIR {summary.tir_pct}%) with drift status '{drift.status}'."
        )

    valid_meals = [m for m in meals_res if m.iauc_valid]
    if valid_meals:
        top = max(valid_meals, key=lambda m: abs(m.excursion_delta_mg_dl or 0.0))
        findings.append(
            f"Post-meal glucose excursion (delta {top.excursion_delta_mg_dl} mg/dL, iAUC {top.iauc_mg_dl_min} mg/dL*min) "
            f"co-occurred across {len(valid_meals)} valid meal window(s)."
        )

    if wb_days > 0:
        findings.append(
            f"Wellbeing check-ins logged on {wb_days} day(s) within the same monitoring window (co-occurrence only)."
        )

    if meds_res.active_regimen_count > 0:
        findings.append(
            f"{meds_res.active_regimen_count} active medication regimen(s) recorded in the same window "
            f"(adherence_computable={meds_res.adherence_computable})."
        )

    summary_line = " | ".join(findings) if findings else "Insufficient overlapping signals in window."
    obs = AgentObservationOut(
        agent_name="cross_signal_orchestrator",
        window_start=summary.window_start,
        window_end=summary.window_end,
        finding_summary=summary_line,
        evidence_items=all_evs[:6],
        observation_count=len(findings),
        missingness_pct=summary.coverage.period_missingness_pct,
        deterministic_confidence=summary.coverage.deterministic_confidence,
        uncertainty_notes=["Co-occurring signals within the same window do not imply causality."],
    )
    ended = _utc_now()
    step = AgentTraceStep(
        node="cross_signal_orchestrator",
        started_at=started,
        ended_at=ended,
        status="completed",
        summary=summary_line,
        evidence_count=len(all_evs),
    )
    return {
        "cross_signal_findings": findings,
        "observations": [obs],
        "trace": [step],
    }


def _appointment_preparer_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    if state.get("simulate_bad_draft"):
        bad_text = (
            "Your glucose spiked to 312 mg/dL because your lunch caused by insulin resistance "
            "proves that you should increase your dose immediately (statistically significant, p < 0.01)."
        )
        ended = _utc_now()
        step = AgentTraceStep(
            node="appointment_preparer",
            started_at=started,
            ended_at=ended,
            status="completed",
            summary="Generated simulated unsafe draft for Verifier demo.",
            evidence_count=0,
        )
        return {
            "draft": {
                "patient_summary": bad_text,
                "clinician_summary": bad_text,
                "clinician_questions": ["Should we adjust my dose?"],
                "hypotheses": [{"title": "Simulated unsafe draft", "confidence": 0.0}],
            },
            "execution_mode": "deterministic_fallback",
            "model_used": "simulated_unsafe_draft_demo",
            "fallback_reason": "simulated_bad_draft_for_verifier_demo",
            "trace": [step],
        }

    prev_rep = state.get("verifier_report")
    repair_feedback = prev_rep.failed_details if (prev_rep and not prev_rep.passed) else None
    attempts = state.get("repair_attempts", 0)
    if repair_feedback is not None:
        attempts += 1

    draft, exec_mode, model_used, fallback_reason = synthesize_narrative(
        mode=state.get("mode", "auto"),
        cohort_type=state["cohort_type"],
        dataset_label=state["dataset_label"],
        summary=state["summary"],
        meal_responses=state.get("meal_responses", []),
        drift=state["drift"],
        meds=state["meds_summary"],
        evidence_items=state["evidence_items"],
        repair_feedback=repair_feedback,
    )

    # Ensure 3-5 neutral, non-prescriptive suggested patient questions
    questions = list(draft.get("clinician_questions") or [])
    default_questions = [
        "How do my observed Time in Range and post-meal glucose patterns align with my personal targets?",
        "Given my sensor coverage and logged meal responses, which meal timings would be most helpful to review together?",
        "Are there any patterns in my wellbeing check-ins or medication timing worth discussing at this visit?",
        "What additional context or logs would be most useful before our next check-in?",
    ]
    for dq in default_questions:
        if len(questions) >= 3:
            break
        if dq not in questions:
            questions.append(dq)
    draft["clinician_questions"] = questions[:5]

    ended = _utc_now()
    step = AgentTraceStep(
        node="appointment_preparer",
        started_at=started,
        ended_at=ended,
        status="repaired" if repair_feedback is not None else "completed",
        summary=f"Synthesized report ({exec_mode}, model={model_used}, questions={len(draft['clinician_questions'])}).",
        evidence_count=len(state.get("evidence_items", [])),
    )
    return {
        "draft": draft,
        "execution_mode": exec_mode,
        "model_used": model_used,
        "fallback_reason": fallback_reason,
        "repair_attempts": attempts,
        "trace": [step],
    }


def _verifier_node(state: InvestigationGraphState) -> dict[str, Any]:
    started = _utc_now()
    draft = state["draft"]
    summary = state["summary"]
    meds = state["meds_summary"]
    extra_nums: list[float] = [
        float(summary.coverage.period_coverage_pct),
        float(len([m for m in state.get("meal_responses", []) if m.iauc_valid])),
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

    extra_agent_texts = [
        state.get("diet_summary_text", ""),
        state.get("wellbeing_summary_text", ""),
        *state.get("cross_signal_findings", []),
    ]
    rep = verify_agent_draft(
        patient_text=draft.get("patient_summary", ""),
        clinician_text=draft.get("clinician_summary", ""),
        evidence_items=state["evidence_items"],
        meal_responses=state.get("meal_responses", []),
        drift_summary=state["drift"],
        extra_grounded_numbers=extra_nums,
        extra_agent_texts=extra_agent_texts,
        repair_attempts=state.get("repair_attempts", 0),
    )
    ended = _utc_now()
    will_repair = (not rep.passed) and (not state.get("simulate_bad_draft")) and (state.get("repair_attempts", 0) < 1)
    step = AgentTraceStep(
        node="verifier",
        started_at=started,
        ended_at=ended,
        status="completed" if rep.passed else ("repaired" if will_repair else "rejected"),
        summary=f"Verifier {rep.verification_status} (failed={rep.failed_reasons or 'none'}).",
        evidence_count=len(state.get("evidence_items", [])),
    )
    return {"verifier_report": rep, "trace": [step]}


def _route_after_verifier(state: InvestigationGraphState) -> str:
    rep = state["verifier_report"]
    if rep.passed or state.get("simulate_bad_draft") or state.get("repair_attempts", 0) >= 1:
        return END
    return "appointment_preparer"


def _build_investigation_graph():
    builder = StateGraph(InvestigationGraphState)
    builder.add_node("supervisor", _supervisor_node)
    builder.add_node("data_quality", _data_quality_node)
    builder.add_node("pattern_watcher", _pattern_watcher_node)
    builder.add_node("diet_nutrition", _diet_nutrition_node)
    builder.add_node("medication_analyst", _medication_analyst_node)
    builder.add_node("wellbeing_companion", _wellbeing_companion_node)
    builder.add_node("cross_signal_orchestrator", _cross_signal_orchestrator_node)
    builder.add_node("appointment_preparer", _appointment_preparer_node)
    builder.add_node("verifier", _verifier_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "data_quality")

    # Parallel fan-out from data_quality to all 4 specialist agents
    builder.add_edge("data_quality", "pattern_watcher")
    builder.add_edge("data_quality", "diet_nutrition")
    builder.add_edge("data_quality", "medication_analyst")
    builder.add_edge("data_quality", "wellbeing_companion")

    # Fan-in to cross_signal_orchestrator -> appointment_preparer -> verifier
    builder.add_edge("pattern_watcher", "cross_signal_orchestrator")
    builder.add_edge("diet_nutrition", "cross_signal_orchestrator")
    builder.add_edge("medication_analyst", "cross_signal_orchestrator")
    builder.add_edge("wellbeing_companion", "cross_signal_orchestrator")
    builder.add_edge("cross_signal_orchestrator", "appointment_preparer")
    builder.add_edge("appointment_preparer", "verifier")
    builder.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {"appointment_preparer": "appointment_preparer", END: END},
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
    wellbeing_records: list[WellbeingRecord] | None = None,
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
        "wellbeing_records": wellbeing_records or [],
    }
    return _COMPILED_GRAPH.invoke(initial_state)
