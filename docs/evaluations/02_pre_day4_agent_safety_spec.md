# Pre-Day 4 Agent Safety & Verifier Specification (Decision C)

**Status:** Specification only (approved Day 3 Decision C; implementation deferred to Day 4 on branch `day4-demo`).  
**Scope:** Deterministic grounding, numeric/threshold attribution, unit/direction consistency, and non-causal language rules for the Day 4 Verifier Agent.

---

## 1. Named-Threshold Numeric Grounding (No Bare Whitelisted Numbers)

The Day 4 Verifier MUST NOT whitelist bare numeric literals (e.g., `70`, `180`, `54`, `250`, `14`, `70.0`). Every numeric value appearing in an agent-generated narrative or summary MUST satisfy one of two strict conditions:

1. **Direct Evidence-Item Grounding:** The number matches an observed metric value (`current_value`, `baseline_value`, `delta`, `observation_count`, `expected_observation_count`, `missingness_pct`, or rounded equivalents within documented tolerance) on an `EvidenceItem` returned by the deterministic analytics tools for that exact patient and window.
2. **Named Clinical/Engineering Threshold Field:** The number is explicitly mapped to a named field on the structured `GlycemicThresholds` reference schema, and the narrative cites the threshold's clinical/engineering context:

```python
class GlycemicThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_range_low_mg_dl: float = 70.0
    target_range_high_mg_dl: float = 180.0
    hypo_level1_lt_mg_dl: float = 70.0
    hypo_level2_lt_mg_dl: float = 54.0
    hyper_level1_gt_mg_dl: float = 180.0
    hyper_level2_gt_mg_dl: float = 250.0
    clinical_guidance_min_days: int = 14
    engineering_coverage_threshold_pct: float = 70.0
    iauc_pre_meal_window_min: float = 30.0
    iauc_post_meal_window_min: float = 180.0
    iauc_min_post_readings: int = 5
    iauc_min_post_span_min: float = 120.0
    iauc_max_consecutive_gap_min: float = 30.0
    drift_min_delta_mg_dl: float = 10.0
```

**Enforcement rule:** A bare number like `"70"` without its threshold role (e.g., `"70% engineering coverage threshold"` vs `"70 mg/dL target range lower bound"`) is rejected by the Verifier. Each whitelisted constant is checked alongside its unit/context (`mg/dL`, `%`, `days`, `min`) and mapped to its named `GlycemicThresholds` field in the Verifier audit trace.

---

## 2. Unit & Direction Contradiction Checks

The Verifier MUST run deterministic contradiction checks comparing every narrative claim against the structured `EvidenceItem` and analytics output fields:

### 2.1 Unit Consistency
- **`postprandial_iauc_mg_dl_min`:** Must use `mg/dL*min` (never `mg/dL` or `mmol/L`).
- **Glucose concentrations (`mean_glucose_mg_dl`, `pre_meal_baseline_glucose_mg_dl`, `postprandial_peak_excursion_mg_dl`, `exploratory_glucose_window_shift_mg_dl`):** Must match `mg/dL` (or explicitly converted `mmol/L` only when labeled as converted from `mg/dL` using `18.0182`). Swapping `mg/dL` and `mmol/L` or `mg/dL*min` and `mg/dL` fails verification.
- **Percentages (`tir_pct`, `tbr_pct`, `tar_pct`, `cv_pct`, `period_coverage_pct`):** Must use `%`.

### 2.2 Direction Consistency
- **Meal responses (`MealResponseItem`):**
  - When `excursion_direction == "postprandial_decline"` (or `excursion_delta_mg_dl < 0`), the narrative MUST NOT contain upward-excursion terms (`"spike"`, `"surge"`, `"elevation"`, `"rose"`, `"rise"`, `"increased"`).
  - When `excursion_direction == "positive_excursion"` (or `excursion_delta_mg_dl > 0`), the narrative MUST NOT describe the post-meal peak as a `"drop"` or `"decline"`.
  - When `iauc_valid is False`, the narrative MUST NOT report a numeric iAUC value and MUST disclose the rejection reason(s).
- **Glucose drift (`DriftSummaryOut`):**
  - When `status == "upward_drift"` (`delta_mg_dl >= 10.0`), the narrative MUST NOT describe the shift as a `"drop"`, `"decline"`, or `"decrease"`.
  - When `status == "downward_drift"` (`delta_mg_dl <= -10.0`), the narrative MUST NOT describe the shift as an `"increase"`, `"rise"`, or `"upward"`.
  - When `status == "insufficient_data"`, the narrative MUST NOT report a baseline/recent mean or drift direction.
- **Date-shifted & assumed-timezone disclosures:**
  - When `calendar_date_comparable is False` (`date_shifted_relative`), cross-dataset calendar-date comparisons are forbidden.
  - When `provenance_counts.get("dataset_documented", 0) > 0` or `provenance_counts.get("archive_aligned", 0) > 0`, the provenance tier disclosure must be preserved.

---

## 3. Causal Language & Statistical Overclaim Checks

CGM observations are observational and serially autocorrelated. The Verifier MUST reject any narrative containing causal or inferential overclaims, including (case-insensitive):

- Causal claims: `"caused by"`, `"causes "`, `"proves that"`, `"proven to"`, `"definitely due to"`, `"directly resulted from"`, `"confirming that [meal/medication] caused"`
- Statistical significance claims on exploratory drift: `"statistically significant"`, `"statistical significance"`, `"p-value"`, `"p <"`, `"p="`, `"significant difference"` (unless explicitly qualified as `"not establishing statistical significance"`)
- Prescription / dosing directives: `"increase your dose"`, `"stop taking"`, `"prescribe"`, `"change your medication"`, `"take X units"` (agents are strictly read-only, non-prescriptive, and must defer clinical decisions to a qualified clinician).

**Fallback behavior on Verifier rejection:**  
If the Verifier rejects a drafted narrative (after at most 1 deterministic repair pass), the endpoint MUST return `verification_status="rejected"` (or a safe deterministic template summary citing only verified `EvidenceItem` values) and log the failed check codes (`numeric_ungrounded`, `unit_mismatch`, `direction_contradiction`, `causal_overclaim`) to `audit_logs`.
