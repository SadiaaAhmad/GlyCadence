from datetime import datetime, timezone
from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import run_investigation_graph
from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import (
    AgentObservation,
    DoctorReport,
    GlucoseReading,
    Investigation,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
    User,
)
from app.schemas.analytics import EvidenceItem
from app.schemas.investigations import (
    AgentObservationOut,
    DoctorReportOut,
    InvestigationRunCreate,
    InvestigationRunOut,
    VerifierReportOut,
)

router = APIRouter(prefix="/patients/{patient_id}/investigations", tags=["Investigations"])


def _dataset_label_for_patient(patient: Patient) -> tuple[bool, str]:
    is_research = patient.cohort_type == "research_participant"
    if patient.source_dataset == "shanghai_t2dm":
        return is_research, f"ShanghaiT2DM v3 Research Cohort ({patient.external_id or patient.id})"
    if patient.source_dataset == "cgmacros":
        return is_research, f"CGMacros Research Cohort ({patient.external_id or patient.id})"
    if patient.cohort_type == "synthetic_demo":
        return False, f"Synthetic Demo ({patient.external_id or patient.display_name})"
    return is_research, patient.display_name


def _serialize_investigation(
    inv: Investigation,
    patient: Patient,
    obs_rows: list[AgentObservation],
    doc_row: DoctorReport | None,
) -> InvestigationRunOut:
    is_research, dataset_label = _dataset_label_for_patient(patient)
    audit_notes = inv.safety_audit_notes if isinstance(inv.safety_audit_notes, dict) else {}
    exec_mode = audit_notes.get("execution_mode", "deterministic_fallback")
    model_used = audit_notes.get("model_used", "deterministic_template_v1")
    verifier_raw = audit_notes.get("verifier_report")
    verifier_rep = VerifierReportOut(**verifier_raw) if isinstance(verifier_raw, dict) else None

    all_evs: list[EvidenceItem] = []
    obs_outs: list[AgentObservationOut] = []
    for o in obs_rows:
        parsed_evs = [EvidenceItem(**e) for e in (o.evidence_items or []) if isinstance(e, dict)]
        all_evs.extend(parsed_evs)
        obs_outs.append(
            AgentObservationOut(
                agent_name=o.agent_name,
                window_start=o.window_start,
                window_end=o.window_end,
                finding_summary=o.finding_summary,
                evidence_items=parsed_evs,
                observation_count=o.observation_count,
                missingness_pct=o.missingness_pct,
                deterministic_confidence=o.deterministic_confidence,
                uncertainty_notes=list(o.uncertainty_notes or []),
            )
        )

    doc_out: DoctorReportOut | None = None
    if doc_row is not None:
        rp = doc_row.report_payload or {}
        doc_out = DoctorReportOut(
            id=doc_row.id,
            investigation_id=doc_row.investigation_id,
            patient_id=doc_row.patient_id,
            cohort_type=doc_row.cohort_type,
            period_start=doc_row.period_start,
            period_end=doc_row.period_end,
            safety_passed=doc_row.safety_passed,
            is_safe_to_display=bool(doc_row.safety_passed),
            execution_mode=rp.get("execution_mode", exec_mode),
            model_used=rp.get("model_used", model_used),
            clinician_questions=list(doc_row.clinician_questions or []),
            report_payload=rp,
            safety_audit_notes=doc_row.safety_audit_notes if isinstance(doc_row.safety_audit_notes, dict) else None,
            created_at=doc_row.created_at,
        )

    return InvestigationRunOut(
        id=inv.id,
        patient_id=inv.patient_id,
        cohort_type=inv.cohort_type,
        is_research_dataset=is_research,
        dataset_label=dataset_label,
        status=inv.status,  # type: ignore[arg-type]
        progress_pct=inv.progress_pct,
        current_step=inv.current_step,
        trigger_type=inv.trigger_type,
        execution_mode=exec_mode,
        model_used=model_used,
        window_start=inv.window_start,
        window_end=inv.window_end,
        primary_summary_patient=inv.primary_summary_patient,
        primary_summary_clinician=inv.primary_summary_clinician,
        hypotheses=list(inv.hypotheses or []) if isinstance(inv.hypotheses, list) else [],
        conflicting_evidence=list(inv.conflicting_evidence or []) if isinstance(inv.conflicting_evidence, list) else [],
        missing_context=list(inv.missing_context or []) if isinstance(inv.missing_context, list) else [],
        deterministic_confidence=inv.deterministic_confidence,
        safety_passed=bool(inv.safety_passed),
        safety_audit_notes=audit_notes or None,
        verifier_report=verifier_rep,
        observations=obs_outs,
        doctor_report=doc_out,
        evidence_items=all_evs,
        created_at=inv.created_at,
        completed_at=inv.completed_at,
    )


@router.post("", response_model=InvestigationRunOut, status_code=status.HTTP_201_CREATED)
def create_investigation(
    patient_id: uuid.UUID,
    payload: InvestigationRunCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InvestigationRunOut:
    # Read-only patient access enforces cohort isolation (research_participant requires researcher/admin)
    patient = require_patient_access(patient_id, current_user, db, write=False)
    if payload.simulate_bad_draft and current_user.role not in {"researcher", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="simulate_bad_draft demo mode is restricted to researcher or admin roles.",
        )
    is_research, dataset_label = _dataset_label_for_patient(patient)

    readings = list(
        db.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.patient_id == patient.id)
            .order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )
    meals = list(
        db.scalars(
            select(Meal).where(Meal.patient_id == patient.id).order_by(Meal.logged_at.asc())
        ).all()
    )
    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id)).all())
    med_events = list(
        db.scalars(
            select(MedicationEvent)
            .where(MedicationEvent.patient_id == patient.id)
            .order_by(MedicationEvent.event_time.asc())
        ).all()
    )

    state = run_investigation_graph(
        patient_id=str(patient.id),
        cohort_type=patient.cohort_type,
        dataset_label=dataset_label,
        readings=readings,
        meals=meals,
        medications=meds,
        medication_events=med_events,
        mode=payload.mode,
        allowed_provenances=payload.allowed_provenances,
        baseline_method=payload.baseline_method,
        device_id=payload.device_id,
        simulate_bad_draft=payload.simulate_bad_draft,
    )

    summary = state["summary"]
    verifier_rep = state["verifier_report"]
    draft = state["draft"]
    exec_mode = state["execution_mode"]
    model_used = state["model_used"]
    obs_list = state["observations"]
    all_evs = state["evidence_items"]
    now = datetime.now(timezone.utc)

    audit_notes_payload: dict[str, Any] = {
        "execution_mode": exec_mode,
        "model_used": model_used,
        "fallback_reason": state.get("fallback_reason"),
        "verifier_report": verifier_rep.model_dump(mode="json"),
        "is_research_dataset": is_research,
        "dataset_label": dataset_label,
    }

    inv = Investigation(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        status="completed",
        progress_pct=100,
        current_step="verifier",
        trigger_type=payload.trigger_type,
        window_start=summary.window_start,
        window_end=summary.window_end,
        primary_summary_patient=draft.get("patient_summary") if verifier_rep.passed else None,
        primary_summary_clinician=draft.get("clinician_summary") if verifier_rep.passed else None,
        hypotheses=draft.get("hypotheses") or [],
        conflicting_evidence=[],
        missing_context=list(summary.coverage.uncertainty_notes),
        deterministic_confidence=summary.coverage.deterministic_confidence,
        safety_passed=verifier_rep.passed,
        safety_audit_notes=audit_notes_payload,
        completed_at=now,
    )
    db.add(inv)
    db.flush()

    obs_rows: list[AgentObservation] = []
    for obs in obs_list:
        row = AgentObservation(
            patient_id=patient.id,
            cohort_type=patient.cohort_type,
            investigation_id=inv.id,
            agent_name=obs.agent_name,
            window_start=obs.window_start,
            window_end=obs.window_end,
            finding_summary=obs.finding_summary,
            evidence_items=[e.model_dump(mode="json") for e in obs.evidence_items],
            observation_count=obs.observation_count,
            missingness_pct=obs.missingness_pct,
            deterministic_confidence=obs.deterministic_confidence,
            uncertainty_notes=obs.uncertainty_notes,
        )
        db.add(row)
        obs_rows.append(row)

    doc_payload: dict[str, Any] = {
        "execution_mode": exec_mode,
        "model_used": model_used,
        "is_research_dataset": is_research,
        "dataset_label": dataset_label,
        "allowed_provenances": summary.allowed_provenances,
        "provenance_counts": {
            "native": summary.native_observation_count,
            "dataset_documented": summary.dataset_documented_observation_count,
            "archive_aligned": summary.archive_aligned_observation_count,
            "interpolated": summary.interpolated_observation_count,
            "derived": summary.derived_observation_count,
            "unknown": summary.unknown_observation_count,
        },
        "mean_glucose_mg_dl": summary.mean_glucose_mg_dl,
        "tir_pct": summary.tir_pct,
        "tbr_pct": summary.tbr_pct,
        "tar_pct": summary.tar_pct,
        "period_coverage_pct": summary.coverage.period_coverage_pct,
        "patient_summary": draft.get("patient_summary") if verifier_rep.passed else None,
        "clinician_summary": draft.get("clinician_summary") if verifier_rep.passed else None,
        "rejected_draft_preview": draft.get("patient_summary") if not verifier_rep.passed else None,
    }
    doc_row = DoctorReport(
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        investigation_id=inv.id,
        period_start=summary.window_start,
        period_end=summary.window_end,
        report_payload=doc_payload,
        clinician_questions=draft.get("clinician_questions") or [],
        safety_passed=verifier_rep.passed,
        safety_audit_notes=audit_notes_payload,
    )
    db.add(doc_row)
    db.flush()

    # Audit log stores ONLY IDs, execution metadata, and evidence checksums (never API keys or patient free text)
    evidence_checksums = sorted({ev.source_record_set_checksum for ev in all_evs if ev.source_record_set_checksum})
    record_audit_event(
        db,
        action="create_log",
        resource_type="investigation",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(inv.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
            "execution_mode": exec_mode,
            "model_used": model_used,
            "safety_passed": verifier_rep.passed,
            "failed_reasons": verifier_rep.failed_reasons,
            "evidence_checksums": evidence_checksums[:20],
            "doctor_report_id": str(doc_row.id),
        },
    )
    db.commit()
    db.refresh(inv)
    db.refresh(doc_row)

    return _serialize_investigation(inv, patient, obs_rows, doc_row)


@router.get("", response_model=list[InvestigationRunOut])
def list_investigations(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[InvestigationRunOut]:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    invs = list(
        db.scalars(
            select(Investigation)
            .where(Investigation.patient_id == patient.id)
            .order_by(Investigation.created_at.desc())
        ).all()
    )
    out: list[InvestigationRunOut] = []
    for inv in invs:
        obs_rows = list(
            db.scalars(
                select(AgentObservation).where(AgentObservation.investigation_id == inv.id)
            ).all()
        )
        doc_row = db.scalar(
            select(DoctorReport).where(DoctorReport.investigation_id == inv.id)
        )
        out.append(_serialize_investigation(inv, patient, obs_rows, doc_row))
    return out


@router.get("/{investigation_id}", response_model=InvestigationRunOut)
def get_investigation(
    patient_id: uuid.UUID,
    investigation_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InvestigationRunOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    inv = db.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id,
            Investigation.patient_id == patient.id,
        )
    )
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "investigation_not_found", "message": "Investigation not found."},
        )
    obs_rows = list(
        db.scalars(
            select(AgentObservation).where(AgentObservation.investigation_id == inv.id)
        ).all()
    )
    doc_row = db.scalar(
        select(DoctorReport).where(DoctorReport.investigation_id == inv.id)
    )
    record_audit_event(
        db,
        action="read_records",
        resource_type="investigation",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(inv.id),
        request=request,
        context_metadata={
            "cohort_type": patient.cohort_type,
            "actor_role": current_user.role,
        },
    )
    db.commit()
    return _serialize_investigation(inv, patient, obs_rows, doc_row)
