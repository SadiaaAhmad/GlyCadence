from typing import Sequence

from app.models import Medication, MedicationEvent
from app.schemas.analytics import MedicationPatternSummaryOut


def compute_medication_pattern_summary(
    medications: Sequence[Medication | dict],
    events: Sequence[MedicationEvent | dict],
    *,
    native_only: bool = True,
) -> MedicationPatternSummaryOut:
    """Summarize prescribed regimens and recorded medication events without fabricating adherence.

    Non-negotiable rule: Clinical-record medication notations with ``status = 'unknown'``
    (such as ShanghaiT2DM medication columns) are never counted as ``taken`` or ``missed``.
    """
    active_regimens = 0
    for m in medications:
        is_act = m.get("is_active", True) if isinstance(m, dict) else m.is_active
        if is_act:
            active_regimens += 1

    taken = 0
    missed = 0
    delayed = 0
    unknown = 0

    for ev in events:
        status = (ev.get("status") if isinstance(ev, dict) else ev.status) or "unknown"
        if status == "taken":
            taken += 1
        elif status == "missed":
            missed += 1
        elif status == "delayed":
            delayed += 1
        else:
            unknown += 1

    total = len(events)
    known_adherence_events = taken + missed + delayed
    adherence_computable = known_adherence_events > 0
    observed_taken_pct = (
        round((taken / known_adherence_events) * 100.0, 2) if adherence_computable else None
    )

    notes: list[str] = []
    if unknown > 0:
        notes.append(
            f"{unknown} medication event(s) have status='unknown' (clinical record notation without timestamped adherence verification) and are excluded from adherence percentages."
        )
    if not adherence_computable:
        notes.append(
            "No patient-verified taken/missed medication events recorded; adherence rate is not computable from prescription records alone."
        )

    return MedicationPatternSummaryOut(
        active_regimen_count=active_regimens,
        total_events=total,
        taken_count=taken,
        missed_count=missed,
        delayed_count=delayed,
        unknown_count=unknown,
        adherence_computable=adherence_computable,
        observed_taken_pct=observed_taken_pct,
        native_only=native_only,
        include_non_native=not native_only,
        provenance_filter_mode="native_only" if native_only else "include_non_native",
        uncertainty_notes=notes,
    )
