import re
from typing import Sequence

from app.schemas.analytics import DriftSummaryOut, EvidenceItem, MealResponseItem
from app.schemas.investigations import GLYCEMIC_THRESHOLDS, VerifierReportOut

# Named threshold rules: (threshold_field, numeric_value, required_context_regex)
THRESHOLD_CONTEXT_RULES: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    (
        "target_range_low_mg_dl",
        GLYCEMIC_THRESHOLDS.target_range_low_mg_dl,
        re.compile(r"target\s+range|below\s+range|\bTIR\b|\bTBR\b|70\s*[-–]\s*180\s*mg/dL|<\s*70\s*mg/dL", re.I),
    ),
    (
        "target_range_high_mg_dl",
        GLYCEMIC_THRESHOLDS.target_range_high_mg_dl,
        re.compile(r"target\s+range|above\s+range|\bTIR\b|\bTAR\b|70\s*[-–]\s*180\s*mg/dL|>\s*180\s*mg/dL", re.I),
    ),
    (
        "hypo_level2_lt_mg_dl",
        GLYCEMIC_THRESHOLDS.hypo_level2_lt_mg_dl,
        re.compile(r"level\s*2|severe\s+hypo|<\s*54\s*mg/dL|below\s+54", re.I),
    ),
    (
        "hyper_level2_gt_mg_dl",
        GLYCEMIC_THRESHOLDS.hyper_level2_gt_mg_dl,
        re.compile(r"level\s*2|>\s*250\s*mg/dL|above\s+250", re.I),
    ),
    (
        "clinical_guidance_min_days",
        float(GLYCEMIC_THRESHOLDS.clinical_guidance_min_days),
        re.compile(r"14\s*[-\s]?day|days|\bAGP\b|clinical\s+guidance", re.I),
    ),
    (
        "engineering_coverage_threshold_pct",
        GLYCEMIC_THRESHOLDS.engineering_coverage_threshold_pct,
        re.compile(r"70\s*%\s*(?:engineering|coverage|wear|threshold)|(?:coverage|wear|threshold)\s*(?:of|at|is)?\s*70\s*%", re.I),
    ),
    (
        "iauc_pre_meal_window_min",
        GLYCEMIC_THRESHOLDS.iauc_pre_meal_window_min,
        re.compile(r"min|minute|pre-meal|anchor|gap", re.I),
    ),
    (
        "iauc_post_meal_window_min",
        GLYCEMIC_THRESHOLDS.iauc_post_meal_window_min,
        re.compile(r"min|minute|post-meal|window", re.I),
    ),
    (
        "iauc_min_post_readings",
        float(GLYCEMIC_THRESHOLDS.iauc_min_post_readings),
        re.compile(r"reading|post-meal|minimum", re.I),
    ),
    (
        "iauc_min_post_span_min",
        GLYCEMIC_THRESHOLDS.iauc_min_post_span_min,
        re.compile(r"min|minute|span|post-meal", re.I),
    ),
    (
        "drift_min_delta_mg_dl",
        GLYCEMIC_THRESHOLDS.drift_min_delta_mg_dl,
        re.compile(r"mg/dL|drift|shift", re.I),
    ),
)

CAUSAL_OVERCLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcaused\s+by\b", re.I),
    re.compile(r"\bproves\s+that\b", re.I),
    re.compile(r"\bdefinitely\s+due\s+to\b", re.I),
    re.compile(r"\bdirectly\s+resulted\s+from\b", re.I),
    re.compile(r"\bstatistically\s+significant\b", re.I),
    re.compile(r"\bp-value\b", re.I),
    re.compile(r"\bp\s*<\s*0\.\d+", re.I),
)

PRESCRIPTIVE_OVERCLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bincrease\s+your\s+dose\b", re.I),
    re.compile(r"\bdecrease\s+your\s+dose\b", re.I),
    re.compile(r"\bstop\s+taking\b", re.I),
    re.compile(r"\bchange\s+your\s+medication\b", re.I),
    re.compile(r"\bprescribe\b", re.I),
)

UPWARD_EXCURSION_WORDS = re.compile(r"\b(spike|spiked|surge|surged|elevation|elevated|rose|rise)\b", re.I)
DOWNWARD_WORDS = re.compile(r"\b(drop|dropped|decline|declined|decrease|decreased|downward)\b", re.I)
UPWARD_DRIFT_WORDS = re.compile(r"\b(increase|increased|rise|rose|upward)\b", re.I)

NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:(?<!\d)-)?\d+(?:\.\d+)?)(?![A-Za-z0-9_]|\.\d)")


def _collect_evidence_numbers(evidence_items: Sequence[EvidenceItem]) -> set[float]:
    nums: set[float] = set()
    for ev in evidence_items:
        for val in (ev.baseline_value, ev.current_value, ev.delta, ev.missingness_pct):
            if val is not None:
                nums.add(round(float(val), 2))
                nums.add(round(float(val), 1))
                nums.add(round(float(val), 0))
        nums.add(float(ev.observation_count))
        if ev.expected_observation_count is not None:
            nums.add(float(ev.expected_observation_count))
    return nums


def verify_agent_draft(
    *,
    patient_text: str,
    clinician_text: str,
    evidence_items: Sequence[EvidenceItem],
    meal_responses: Sequence[MealResponseItem] = (),
    drift_summary: DriftSummaryOut | None = None,
    extra_grounded_numbers: Sequence[float] = (),
    repair_attempts: int = 0,
) -> VerifierReportOut:
    """Deterministic safety gate enforcing Decision C & 02_pre_day4_agent_safety_spec.md."""
    combined = f"{patient_text}\n{clinician_text}".strip()
    checks_run = [
        "named_threshold_numeric_grounding",
        "unit_consistency",
        "direction_contradiction",
        "causal_overclaim",
        "prescriptive_overclaim",
        "provenance_disclosure",
    ]
    failed_reasons: list[str] = []
    failed_details: list[str] = []
    named_thresholds_used: list[str] = []
    ungrounded_numbers: list[str] = []

    if not combined:
        failed_reasons.append("empty_draft")
        failed_details.append("Draft narrative is empty.")

    # 1. Named-threshold & EvidenceItem numeric grounding
    evidence_nums = _collect_evidence_numbers(evidence_items)
    for extra_n in extra_grounded_numbers:
        evidence_nums.add(round(float(extra_n), 2))
        evidence_nums.add(round(float(extra_n), 1))
        evidence_nums.add(round(float(extra_n), 0))

    # Ignore version strings like v1.6.0, ISO dates like 2023-01-01, and IDs like ST2D-1001 / SYNTH-DEMO-001
    sanitized_text = re.sub(r"\bv\d+\.\d+\.\d+\b", " ", combined)
    sanitized_text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", sanitized_text)
    sanitized_text = re.sub(r"\b[A-Za-z][A-Za-z0-9-]*-\d+\b", " ", sanitized_text)

    for match in NUMBER_TOKEN_RE.finditer(sanitized_text):
        raw_num_str = match.group(1)
        try:
            num_val = float(raw_num_str)
        except ValueError:
            continue

        # Check direct EvidenceItem grounding first
        is_ev_grounded = any(
            abs(num_val - ev_n) <= 0.15 or abs(abs(num_val) - abs(ev_n)) <= 0.15
            for ev_n in evidence_nums
        )
        if is_ev_grounded:
            continue

        # Otherwise, MUST match a named GlycemicThresholds field WITH local context
        start = max(0, match.start() - 45)
        end = min(len(sanitized_text), match.end() + 45)
        local_ctx = sanitized_text[start:end]

        matched_field: str | None = None
        for field_name, thresh_val, ctx_re in THRESHOLD_CONTEXT_RULES:
            if abs(num_val - thresh_val) <= 1e-6 and ctx_re.search(local_ctx):
                matched_field = field_name
                break

        if matched_field is not None:
            if matched_field not in named_thresholds_used:
                named_thresholds_used.append(matched_field)
        else:
            ungrounded_numbers.append(raw_num_str)

    if ungrounded_numbers:
        failed_reasons.append("numeric_ungrounded")
        failed_details.append(
            f"Ungrounded or bare uncontextualized numbers detected: {sorted(set(ungrounded_numbers))}"
        )

    # 2. Unit consistency checks
    has_iauc = any(ev.metric_name == "postprandial_iauc_mg_dl_min" for ev in evidence_items)
    if has_iauc:
        for m in re.finditer(r"\biAUC\b(?:[^.\n]|\.\d){0,60}", combined, re.I):
            seg = m.group(0)
            if "mmol/L" in seg or ("mg/dL" in seg and "mg/dL*min" not in seg):
                if "unit_mismatch" not in failed_reasons:
                    failed_reasons.append("unit_mismatch")
                failed_details.append(f"iAUC reported with invalid unit in: {seg!r}")

    if re.search(r"\bmean\s+glucose\b(?:[^.\n]|\.\d){0,40}\bmmol/L\b", combined, re.I):
        if "unit_mismatch" not in failed_reasons:
            failed_reasons.append("unit_mismatch")
        failed_details.append("Mean glucose reported in mmol/L instead of verified mg/dL.")

    # 3. Direction contradiction checks
    if meal_responses:
        valid_meals = [m for m in meal_responses if m.iauc_valid]
        if valid_meals and all(m.excursion_direction == "postprandial_decline" for m in valid_meals):
            if UPWARD_EXCURSION_WORDS.search(combined):
                failed_reasons.append("direction_contradiction")
                failed_details.append(
                    "Narrative uses upward-excursion language ('spike'/'surge'/'rise') when all valid meals are postprandial_decline."
                )

    if drift_summary is not None:
        if drift_summary.status == "upward_drift" and re.search(
            r"\bdrift\b[^.\n]{0,40}\b(drop|decline|decrease|downward)\b", combined, re.I
        ):
            if "direction_contradiction" not in failed_reasons:
                failed_reasons.append("direction_contradiction")
            failed_details.append("Drift described as downward when deterministic status is upward_drift.")
        elif drift_summary.status == "downward_drift" and re.search(
            r"\bdrift\b[^.\n]{0,40}\b(increase|rise|upward)\b", combined, re.I
        ):
            if "direction_contradiction" not in failed_reasons:
                failed_reasons.append("direction_contradiction")
            failed_details.append("Drift described as upward when deterministic status is downward_drift.")
        elif drift_summary.status == "insufficient_data" and re.search(
            r"\b(upward_drift|downward_drift|upward\s+drift|downward\s+drift)\b", combined, re.I
        ):
            if "direction_contradiction" not in failed_reasons:
                failed_reasons.append("direction_contradiction")
            failed_details.append("Drift direction claimed when deterministic status is insufficient_data.")

    # 4. Causal & statistical overclaim checks
    for pat in CAUSAL_OVERCLAIM_PATTERNS:
        m = pat.search(combined)
        if m:
            if "causal_overclaim" not in failed_reasons:
                failed_reasons.append("causal_overclaim")
            failed_details.append(f"Causal or inferential overclaim detected: {m.group(0)!r}")
            break

    # 5. Prescriptive overclaim checks
    for pat in PRESCRIPTIVE_OVERCLAIM_PATTERNS:
        m = pat.search(combined)
        if m:
            if "prescriptive_overclaim" not in failed_reasons:
                failed_reasons.append("prescriptive_overclaim")
            failed_details.append(f"Prescriptive medication advice detected: {m.group(0)!r}")
            break

    # 6. Provenance disclosure check
    used_provs: set[str] = set()
    for ev in evidence_items:
        for prov_key, cnt in ev.provenance_counts.items():
            if cnt > 0:
                used_provs.add(prov_key)
    if "dataset_documented" in used_provs and "dataset_documented" not in combined:
        failed_reasons.append("missing_provenance_disclosure")
        failed_details.append("Narrative must disclose 'dataset_documented' provenance when used.")
    if "archive_aligned" in used_provs and "archive_aligned" not in combined:
        if "missing_provenance_disclosure" not in failed_reasons:
            failed_reasons.append("missing_provenance_disclosure")
        failed_details.append("Narrative must disclose 'archive_aligned' provenance when used.")

    passed = len(failed_reasons) == 0
    return VerifierReportOut(
        passed=passed,
        verification_status="passed" if passed else "rejected",
        checks_run=checks_run,
        failed_reasons=failed_reasons,
        failed_details=failed_details,
        named_thresholds_used=sorted(named_thresholds_used),
        ungrounded_numbers=sorted(set(ungrounded_numbers)),
        repair_attempts=repair_attempts,
    )
