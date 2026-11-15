export type CohortType = "research_participant" | "synthetic_demo" | "app_user";

export interface PatientSummary {
  id: string;
  cohort_type: CohortType;
  external_id: string | null;
  display_name: string;
  diabetes_type: string;
  timezone: string | null;
  source_dataset: string;
  retention_policy: string;
}

export interface EvidenceItem {
  evidence_id: string;
  metric_name: string;
  value: number | string | null;
  unit: string | null;
  calculation_version: string;
  source_dataset: string | null;
  allowed_provenances: string[];
  provenance_counts: Record<string, number>;
  source_record_set_checksum: string;
  uncertainty_notes: string[];
}

export interface CoverageReport {
  period_coverage_pct: number;
  daily_coverage_pct_median: number | null;
  total_cgm_observations: number;
  deterministic_confidence: number;
  uncertainty_notes: string[];
  provenance_counts: Record<string, number>;
}

export interface GlucoseSummary {
  patient_id: string;
  cohort_type: CohortType;
  window_start: string;
  window_end: string;
  mean_glucose_mg_dl: number | null;
  sd_glucose_mg_dl: number | null;
  cv_pct: number | null;
  tir_pct: number | null;
  tbr_pct: number | null;
  tar_pct: number | null;
  native_observation_count: number;
  dataset_documented_observation_count: number;
  archive_aligned_observation_count: number;
  interpolated_observation_count: number;
  derived_observation_count: number;
  unknown_observation_count: number;
  coverage: CoverageReport;
  evidence: EvidenceItem[];
}

export interface MealResponseItem {
  meal_id: string;
  logged_at: string;
  meal_type: string;
  description: string;
  carbs_g: number | null;
  baseline_glucose_mg_dl: number | null;
  peak_glucose_mg_dl: number | null;
  excursion_mg_dl: number | null;
  excursion_direction: "positive" | "flat" | "negative" | "insufficient_data";
  iauc_mg_dl_min: number | null;
  validity: "valid" | "insufficient_data";
  rejection_reason: string | null;
  evidence: EvidenceItem;
}

export interface DriftSummary {
  patient_id: string;
  cohort_type: CohortType;
  status: "ok" | "insufficient_data";
  direction: "upward" | "downward" | "stable" | "insufficient_data";
  early_mean_mg_dl: number | null;
  late_mean_mg_dl: number | null;
  delta_mg_dl: number | null;
  exploratory_note: string;
  evidence: EvidenceItem;
}

export interface VerifierReport {
  passed: boolean;
  verification_status: "passed" | "rejected";
  failed_reasons: string[];
  details: string[];
  named_thresholds_used: Record<string, string>;
  checked_provenances: string[];
  repair_attempted: boolean;
}

export interface AgentObservationOut {
  agent_name: string;
  observation_type: string;
  finding_summary: string;
  confidence: number;
  evidence_refs: string[];
}

export interface DoctorReportOut {
  id: string;
  investigation_id: string;
  is_safe_to_display: boolean;
  safety_passed: boolean;
  clinician_questions: string[];
  report_payload: Record<string, unknown>;
}

export interface InvestigationRun {
  id: string;
  patient_id: string;
  cohort_type: CohortType;
  is_research_dataset: boolean;
  dataset_label: string;
  status: string;
  trigger_type: string;
  execution_mode: "gemini" | "deterministic_fallback";
  model_used: string;
  fallback_reason: string | null;
  window_start: string | null;
  window_end: string | null;
  primary_summary_patient: string | null;
  primary_summary_clinician: string | null;
  hypotheses: string[];
  missing_context: string[];
  deterministic_confidence: number | null;
  safety_passed: boolean;
  verifier_report: VerifierReport;
  observations: AgentObservationOut[];
  doctor_report: DoctorReportOut | null;
  evidence_items: EvidenceItem[];
  created_at: string;
  completed_at: string | null;
}
