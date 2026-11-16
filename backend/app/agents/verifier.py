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
    re.compile(r"\bled\s+to\b", re.I),
    re.compile(r"\bresulted\s+in\b", re.I),
    re.compile(r"\bdrove\b", re.I),
    re.compile(r"\bdriven\s+by\b", re.I),
    re.compile(r"\bresponsible\s+for\b", re.I),
    re.compile(r"\bconfirm(?:s|ed)?\s+that\b", re.I),
    re.compile(r"\bdemonstrates\s+that\b", re.I),
    re.compile(r"\bsignificant(?:ly)?\s+(?:higher|lower|difference|effect)\b", re.I),
)

PRESCRIPTIVE_OVERCLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bincrease\s+your\s+dose\b", re.I),
    re.compile(r"\bdecrease\s+your\s+dose\b", re.I),
    re.compile(r"\bstop\s+taking\b", re.I),
    re.compile(r"\bchange\s+your\s+medication\b", re.I),
    re.compile(r"\bprescribe\b", re.I),
    re.compile(
        r"\b(?:raise|lower|adjust|titrate|double|halve)\s+(?:your|the)\s+(?:insulin|metformin|dose|dosage|medication|meds)\b",
        re.I,
    ),
    re.compile(r"\b(?:start|begin|resume|discontinue)\s+taking\b", re.I),
    re.compile(r"\byou\s+should\s+(?:take|use|add|skip|avoid|raise|lower)\b", re.I),
    re.compile(r"\bconsider\s+(?:raising|lowering|increasing|decreasing|stopping|starting)\b", re.I),
)

UPWARD_EXCURSION_WORDS = re.compile(
    r"\b(spike|spiked|surge|surged|elevation|elevated|rose|rise|climbed|climb|went\s+up|jump|jumped|higher\s+after)\b",
    re.I,
)
DOWNWARD_WORDS = re.compile(r"\b(drop|dropped|decline|declined|decrease|decreased|downward)\b", re.I)
UPWARD_DRIFT_WORDS = re.compile(r"\b(increase|increased|rise|rose|upward|climbed|went\s+up)\b", re.I)

NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])((?:(?<!\d)-)?\d+(?:\.\d+)?)(?![A-Za-z0-9_]|\.\d)")

# Metric-specific grounding rules: (family_name, context_regex, allowed_evidence_metric_names)
METRIC_CONTEXT_SPECS: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = (
    (
        "tir",
        re.compile(r"\b(TIR|time\s+in\s+range)\b", re.I),
        ("time_in_range_70_180_pct", "time_in_range_pct", "tir_pct"),
    ),
    (
        "tbr",
        re.compile(r"\b(TBR|time\s+below\s+range)\b", re.I),
        ("time_below_range_lt_70_pct", "time_below_range_level2_lt_54_pct", "time_below_range_pct", "tbr_pct"),
    ),
    (
        "tar",
        re.compile(r"\b(TAR|time\s+above\s+range)\b", re.I),
        ("time_above_range_gt_180_pct", "time_above_range_level2_gt_250_pct", "time_above_range_pct", "tar_pct"),
    ),
    ("cv", re.compile(r"\b(CV|coefficient\s+of\s+variation)\b", re.I), ("glucose_cv_pct", "cv_pct")),
    ("sd", re.compile(r"\b(SD|standard\s+deviation)\b", re.I), ("sd_glucose_mg_dl",)),
    (
        "coverage",
        re.compile(r"\b(coverage|wear\s+time)\b", re.I),
        ("period_coverage_pct", "daily_coverage_pct_median", "cgm_period_coverage_pct"),
    ),
    ("missingness", re.compile(r"\b(missingness|missing)\b", re.I), ("__missingness__",)),
    ("iauc", re.compile(r"\b(iAUC|incremental\s+area)\b", re.I), ("postprandial_iauc_mg_dl_min",)),
    (
        "excursion",
        re.compile(r"\b(excursion|delta|peak|pre-meal|post-meal)\b", re.I),
        (
            "postprandial_excursion_mg_dl",
            "postprandial_iauc_mg_dl_min",
            "exploratory_glucose_window_shift_mg_dl",
            "exploratory_glucose_drift",
        ),
    ),
    (
        "drift",
        re.compile(r"\b(drift|baseline\s+mean|recent\s+mean|early\s+mean|late\s+mean|shift)\b", re.I),
        ("exploratory_glucose_window_shift_mg_dl", "exploratory_glucose_drift"),
    ),
    (
        "mean_glucose",
        re.compile(r"\b(mean\s+glucose|average\s+glucose)\b", re.I),
        ("mean_glucose_mg_dl", "exploratory_glucose_window_shift_mg_dl", "exploratory_glucose_drift"),
    ),
    (
        "adherence",
        re.compile(r"\b(adherence|taken\s+rate|regimen)\b", re.I),
        ("medication_adherence_rate", "medication_taken_rate"),
    ),
    (
        "obs_count",
        re.compile(r"\b(reading|readings|observation|observations|expected|sample|samples)\b", re.I),
        ("__obs_count__",),
    ),
)
EXTRA_SUMMARY_CONTEXT_RE = re.compile(
    r"\b(meal|meals|window|windows|regimen|regimens|notation|notations|day|days|excursion|delta|iAUC|taken\s+rate|active|coverage)\b",
    re.I,
)


def _collect_metric_evidence_map(evidence_items: Sequence[EvidenceItem]) -> dict[str, set[float]]:
    by_metric: dict[str, set[float]] = {}
    for ev in evidence_items:
        bucket = by_metric.setdefault(ev.metric_name, set())
        for val in (ev.baseline_value, ev.current_value, ev.delta):
            if val is not None:
                bucket.add(round(float(val), 2))
                bucket.add(round(float(val), 1))
                bucket.add(round(float(val), 0))
        if ev.missingness_pct is not None:
            miss_bucket = by_metric.setdefault("__missingness__", set())
            miss_bucket.add(round(float(ev.missingness_pct), 2))
            miss_bucket.add(round(float(ev.missingness_pct), 1))
        obs_bucket = by_metric.setdefault("__obs_count__", set())
        obs_bucket.add(float(ev.observation_count))
        if ev.expected_observation_count is not None:
            obs_bucket.add(float(ev.expected_observation_count))
    return by_metric


def _clause_around(text: str, start_idx: int, end_idx: int) -> str:
    left_bound = max(0, start_idx - 55)
    right_bound = min(len(text), end_idx + 40)
    left_seg = text[left_bound:start_idx]
    right_seg = text[end_idx:right_bound]
    # Trim at sentence/clause delimiters so previous metrics do not bleed in
    for sep in (";", "\n", ". ", ", "):
        if sep in left_seg:
            left_seg = left_seg.rsplit(sep, 1)[-1]
        if sep in right_seg:
            right_seg = right_seg.split(sep, 1)[0]
    return f"{left_seg}{text[start_idx:end_idx]}{right_seg}"


JUDGMENTAL_FOOD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(good|bad|unhealthy|healthy|toxic|harmful|safe|unsafe|forbidden|junk|cheat)\s+(food|foods|meal|meals|carbs|snack|snacks|diet)\b", re.I),
    re.compile(r"\b(food|foods|meal|meals)\s+(?:is|are|was|were)\s+(bad|good|unhealthy|healthy|toxic|unsafe|safe)\b", re.I),
)
WELLBEING_CAUSAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(stress|fatigue|sleep|illness)\s+(?:caused|triggered|drove|elevated|spiked|worsened)\b", re.I),
)


def _matches_any(num_val: float, candidates: set[float]) -> bool:
    return any(abs(num_val - c) <= 0.15 or abs(abs(num_val) - abs(c)) <= 0.15 for c in candidates)


def verify_agent_draft(
    *,
    patient_text: str,
    clinician_text: str,
    evidence_items: Sequence[EvidenceItem],
    meal_responses: Sequence[MealResponseItem] = (),
    drift_summary: DriftSummaryOut | None = None,
    extra_grounded_numbers: Sequence[float] = (),
    extra_agent_texts: Sequence[str] = (),
    repair_attempts: int = 0,
) -> VerifierReportOut:
    """Deterministic safety gate enforcing Decision C & 02_pre_day4_agent_safety_spec.md."""
    combined = f"{patient_text}\n{clinician_text}".strip()
    specialist_combined = "\n".join(t for t in extra_agent_texts if t).strip()
    all_language_text = f"{combined}\n{specialist_combined}".strip()
    checks_run = [
        "named_threshold_numeric_grounding",
        "unit_consistency",
        "direction_contradiction",
        "causal_overclaim",
        "prescriptive_overclaim",
        "provenance_disclosure",
        "neutral_food_wording",
        "wellbeing_cooccurrence_only",
    ]
    failed_reasons: list[str] = []
    failed_details: list[str] = []
    named_thresholds_used: list[str] = []
    ungrounded_numbers: list[str] = []

    if not combined:
        failed_reasons.append("empty_draft")
        failed_details.append("Draft narrative is empty.")

    # 1. Metric-specific EvidenceItem & named-threshold numeric grounding
    by_metric = _collect_metric_evidence_map(evidence_items)
    excursion_bucket = by_metric.setdefault("postprandial_excursion_mg_dl", set())
    for mr in meal_responses:
        for val in (mr.excursion_delta_mg_dl, mr.pre_meal_glucose_mg_dl, mr.peak_post_meal_glucose_mg_dl):
            if val is not None:
                excursion_bucket.add(round(float(val), 2))
                excursion_bucket.add(round(float(val), 1))
                excursion_bucket.add(round(float(val), 0))
    extra_nums_set: set[float] = set()
    for extra_n in extra_grounded_numbers:
        extra_nums_set.add(round(float(extra_n), 2))
        extra_nums_set.add(round(float(extra_n), 1))
        extra_nums_set.add(round(float(extra_n), 0))

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

        start = max(0, match.start() - 45)
        end = min(len(sanitized_text), match.end() + 45)
        local_ctx = sanitized_text[start:end]
        clause_ctx = _clause_around(sanitized_text, match.start(), match.end())

        # A. Named GlycemicThresholds check first (70, 180, 54, 250, 14, 70% threshold)
        matched_field: str | None = None
        for field_name, thresh_val, ctx_re in THRESHOLD_CONTEXT_RULES:
            if abs(num_val - thresh_val) <= 1e-6 and ctx_re.search(local_ctx):
                matched_field = field_name
                break
        if matched_field is not None:
            if matched_field not in named_thresholds_used:
                named_thresholds_used.append(matched_field)
            continue

        # B. Metric-specific EvidenceItem grounding
        matched_metric_names: list[str] = []
        for _, m_ctx_re, m_names in METRIC_CONTEXT_SPECS:
            if m_ctx_re.search(clause_ctx):
                matched_metric_names.extend(m_names)

        if matched_metric_names:
            metric_candidates: set[float] = set()
            for mn in matched_metric_names:
                metric_candidates.update(by_metric.get(mn, set()))
                if mn == "postprandial_iauc_mg_dl_min":
                    for k, vals in by_metric.items():
                        if k.endswith("postprandial_iauc_mg_dl_min"):
                            metric_candidates.update(vals)
            if _matches_any(num_val, metric_candidates):
                continue
            # Also allow extra_grounded_numbers ONLY for excursion/adherence/iauc summary counts
            if EXTRA_SUMMARY_CONTEXT_RE.search(clause_ctx) and _matches_any(num_val, extra_nums_set):
                continue
            ungrounded_numbers.append(raw_num_str)
            continue

        # C. Unlabeled summary counts (e.g. "18 valid meal windows", "1 active regimen(s)")
        if EXTRA_SUMMARY_CONTEXT_RE.search(clause_ctx) and _matches_any(num_val, extra_nums_set):
            continue

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
    for pat in (*CAUSAL_OVERCLAIM_PATTERNS, *WELLBEING_CAUSAL_PATTERNS, re.compile(r"\b(caused|causes)\s+(?:a|your|the|my)?\s*(?:sugar|glucose|blood\s+sugar)?\s*(?:spike|rise|drop|crash|excursion)\b", re.I)):
        m = pat.search(all_language_text)
        if m:
            if "causal_overclaim" not in failed_reasons:
                failed_reasons.append("causal_overclaim")
            failed_details.append(f"Causal or inferential overclaim detected: {m.group(0)!r}")
            break

    # 5. Prescriptive overclaim checks
    for pat in PRESCRIPTIVE_OVERCLAIM_PATTERNS:
        m = pat.search(all_language_text)
        if m:
            if "prescriptive_overclaim" not in failed_reasons:
                failed_reasons.append("prescriptive_overclaim")
            failed_details.append(f"Prescriptive medication advice detected: {m.group(0)!r}")
            break

    # 5b. Neutral food wording check (diet_nutrition + draft)
    for pat in JUDGMENTAL_FOOD_PATTERNS:
        m = pat.search(all_language_text)
        if m:
            if "judgmental_food_wording" not in failed_reasons:
                failed_reasons.append("judgmental_food_wording")
            failed_details.append(f"Non-neutral food label detected: {m.group(0)!r}")
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


MEDICATION_DOSE_CHANGE_PATTERNS = (
    re.compile(
        r"\b(take|use|inject|increase|decrease|reduce|double|half)\s+(\d+(?:\.\d+)?)\s*(mg|mcg|units?|u\b|tablets?|pills?)",
        re.I,
    ),
    re.compile(
        r"\b(change|switch|adjust)\s+(your\s+)?(dose|dosage|medication|insulin|gliclazide|metformin)\s+to\b",
        re.I,
    ),
)


def verify_chat_reply(
    *,
    reply_text: str,
    allowed_numbers: set[float],
    allowed_regimen_dose_tokens: set[str] | None = None,
    urgent_triggered: bool = False,
    nutrient_values: set[float] | None = None,
    timing_windows: set[str] | None = None,
    evidence_items: Sequence[EvidenceItem] = (),
    repair_attempts: int = 0,
) -> VerifierReportOut:
    """Phase P4 verifier extension for CADIE chat replies, meal details, timing, medications, and urgent alerts."""
    checks_run = [
        "chat_numeric_grounding",
        "meal_detail_nutrient_grounding",
        "timing_guidance_check",
        "medication_dose_safety",
        "urgent_language_check",
        "causal_overclaim",
        "prescriptive_overclaim",
        "judgmental_food_wording",
    ]
    failed_reasons: list[str] = []
    failed_details: list[str] = []
    ungrounded_numbers: list[str] = []

    permitted: set[float] = set(allowed_numbers)
    if nutrient_values:
        permitted.update(nutrient_values)
    for ev in evidence_items:
        for nv in _extract_evidence_numbers(ev):
            permitted.add(nv)
    permitted.update({2.0, 3.0, 4.0, 5.0, 12.0, 14.0, 15.0, 24.0, 30.0, 36.0, 54.0, 70.0, 180.0, 250.0, 300.0})

    sanitized_for_nums = re.sub(r"\b\d{1,2}:\d{2}\b", " ", reply_text)
    chat_num_re = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])")
    for m in chat_num_re.finditer(sanitized_for_nums):
        raw_num = m.group(0)
        try:
            num = float(raw_num)
        except ValueError:
            continue
        if num in permitted or any(abs(num - p) <= 0.6 for p in permitted):
            continue
        if "numeric_ungrounded" not in failed_reasons:
            failed_reasons.append("numeric_ungrounded")
        ungrounded_numbers.append(raw_num)
        failed_details.append(f"Number {raw_num!r} in chat reply did not match computed specialist outputs.")

    for pat in (*CAUSAL_OVERCLAIM_PATTERNS, *WELLBEING_CAUSAL_PATTERNS, re.compile(r"\b(caused|causes)\s+(?:a|your|the|my)?\s*(?:sugar|glucose|blood\s+sugar)?\s*(?:spike|rise|drop|crash|excursion)\b", re.I)):
        m = pat.search(reply_text)
        if m:
            if "causal_overclaim" not in failed_reasons:
                failed_reasons.append("causal_overclaim")
            failed_details.append(f"Causal claim detected: {m.group(0)!r}")
            break

    for pat in PRESCRIPTIVE_OVERCLAIM_PATTERNS:
        m = pat.search(reply_text)
        if m:
            if "prescriptive_overclaim" not in failed_reasons:
                failed_reasons.append("prescriptive_overclaim")
            failed_details.append(f"Prescriptive medication claim detected: {m.group(0)!r}")
            break

    for pat in JUDGMENTAL_FOOD_PATTERNS:
        m = pat.search(reply_text)
        if m:
            if "judgmental_food_wording" not in failed_reasons:
                failed_reasons.append("judgmental_food_wording")
            failed_details.append(f"Judgmental food wording detected: {m.group(0)!r}")
            break

    allowed_doses = {d.lower() for d in (allowed_regimen_dose_tokens or set())}
    for pat in MEDICATION_DOSE_CHANGE_PATTERNS:
        m = pat.search(reply_text)
        if m:
            phrase = m.group(0).lower()
            if not any(d in phrase for d in allowed_doses) or any(
                w in phrase for w in ("increase", "decrease", "reduce", "double", "half", "change", "switch", "adjust", "take ", "inject ")
            ):
                if "medication_dose_unsafe" not in failed_reasons:
                    failed_reasons.append("medication_dose_unsafe")
                failed_details.append(f"Unsafe medication dosing language: {m.group(0)!r}")
                break

    if timing_windows is not None and timing_windows:
        clock_mentions = re.findall(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", reply_text, re.I)
        if clock_mentions:
            norm_reply = reply_text.lower()
            joined = " ".join(timing_windows).lower()
            unmatched = [c for c in clock_mentions if c.lower() not in joined and "general guidance" not in norm_reply]
            if unmatched and "ungrounded_timing" not in failed_reasons:
                failed_reasons.append("ungrounded_timing")
                failed_details.append(f"Timing mention {unmatched!r} missing timing planner basis or 'general guidance' label.")

    if urgent_triggered:
        low_txt = reply_text.lower()
        if "15" not in low_txt or ("emergency" not in low_txt and "urgent" not in low_txt and "doctor" not in low_txt):
            failed_reasons.append("missing_urgent_guidance")
            failed_details.append("Urgent alert fired; reply must include 15-15 guidance and emergency/clinician contact.")

    passed = len(failed_reasons) == 0
    return VerifierReportOut(
        passed=passed,
        verification_status="passed" if passed else "rejected",
        checks_run=checks_run,
        failed_reasons=failed_reasons,
        failed_details=failed_details,
        named_thresholds_used=["ADA TIR 70-180 mg/dL", "Hypo <70 mg/dL", "IDF-DAR fasting rules"],
        ungrounded_numbers=sorted(set(ungrounded_numbers)),
        repair_attempts=repair_attempts,
    )
