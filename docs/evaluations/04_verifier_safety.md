# Day 4 Evaluation — Deterministic Verifier Safety Gate & Known Limitations

## 1. Architecture Role
In GlyCadence's Day 4 pipeline (`supervisor -> data_quality -> pattern -> medication_context -> synthesizer -> verifier`):
- **Deterministic code computes** all glycemic metrics (`TIR`, `TBR`, `TAR`, `CV%`, `iAUC`, `coverage`, `exploratory drift`, `medication adherence`), provenance counts, and SHA-256 `source_record_set_checksum`s.
- **The LLM (or deterministic template fallback) only synthesizes** human-readable `patient_summary`, `clinician_summary`, and `clinician_questions`.
- **`verify_agent_draft()` acts as a deterministic first-line safety gate** before any narrative can set `DoctorReport.is_safe_to_display = True`.

## 2. Implemented Guardrails (Verified in `backend/tests/test_agent_safety.py`)
1. **Metric-Specific Numeric Grounding (`numeric_ungrounded`)**
   - Every numeric token in `patient_summary` and `clinician_summary` is checked within its local clause (`;`, `\n`, `. `, `, ` boundaries) against:
     - Named `GlycemicThresholds` rules with required clinical context (`70`, `180`, `54`, `250`, `14` days, `70%` engineering coverage).
     - The specific `EvidenceItem` metric family named in that clause (`time_in_range_70_180_pct`, `time_below_range_lt_70_pct`, `time_above_range_gt_180_pct`, `mean_glucose_mg_dl`, `glucose_cv_pct`, `postprandial_iauc_mg_dl_min`, `exploratory_glucose_window_shift_mg_dl`, etc.).
     - `observation_count` and `expected_observation_count` are isolated to observation-count contexts (`readings`, `observations`, `samples`) and cannot ground glycemic metrics.
     - Correct numbers attached to the wrong metric (e.g., `"TIR 142.0%"` when `142.0` is `mean_glucose_mg_dl`) are rejected.
2. **Unit Consistency (`unit_mismatch`)**
   - Blocks `iAUC` reported in `mmol/L` or `mg/dL` (must be `mg/dL*min`) and `mean glucose` reported in `mmol/L`.
3. **Direction Contradiction (`direction_contradiction`)**
   - Blocks upward-excursion phrasing (`spike`, `surge`, `rose`, `climbed`, `went up`, `higher after`) when all valid meals are `postprandial_decline`, and blocks drift direction contradictions or directional claims when `drift.status == "insufficient_data"`.
4. **Causal & Statistical Overclaim (`causal_overclaim`)**
   - Blocks `caused by`, `proves that`, `definitely due to`, `led to`, `resulted in`, `drove`, `driven by`, `statistically significant`, `p-value`, `p < 0.05`, etc.
5. **Prescriptive Overclaim (`prescriptive_overclaim`)**
   - Blocks `increase/decrease your dose`, `stop taking`, `raise/lower/adjust/titrate your insulin/metformin`, `you should take/raise/lower`, `consider raising/lowering/...`, `prescribe`.
6. **Provenance Disclosure (`missing_provenance_disclosure`)**
   - Requires explicit mention of `dataset_documented` or `archive_aligned` whenever rows with those provenances are included.
7. **Demo Mode RBAC (`simulate_bad_draft`)**
   - `POST /api/v1/patients/{patient_id}/investigations` with `simulate_bad_draft=True` skips the repair loop for live UI demonstration and is restricted to `researcher` and `admin` roles (`403 Forbidden` for standard `patient` users).

## 3. Known Limitations (First-Line Gate Scope)
- **Regex & clause-window heuristics:** Causal, prescriptive, and direction checks use regular expressions over a bounded clause window. Novel paraphrases or multi-sentence indirect implications outside the pattern list can evade a regex-only gate.
- **Numeric tolerance (`±0.15`):** Allows minor rounding differences (e.g., `142.0` vs `142.1`), which means a number within `0.15` of the *same* metric's rounded value is accepted.
- **Not a semantic NLI / clinical-judge verifier:** The deterministic gate guarantees structural and first-line grounding hygiene ("blocks numbers that do not match their attached metric in the evidence"), not full semantic entailment. Adding an NLI or secondary LLM-as-a-judge pass is left as future work.
