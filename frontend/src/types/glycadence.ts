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

export interface HeroGlucoseCard {
  latest_mg_dl?: number | null;
  trend?: string;
  tir_pct?: number | null;
  nocturnal_lows?: number;
  safe_nights?: number;
}

export interface TodayOverview {
  patient_id: string;
  display_name: string;
  cohort_type: CohortType;
  greeting_line: string;
  hero: HeroGlucoseCard;
  next_up: { slot: string; title: string; window: string; recipe_id?: string | null }[];
  featured_suggestion: string;
  featured_recipe: {
    recipe_id: string;
    name: string;
    slot: string;
    image_url: string;
    carbs_g: number;
    sugar_g: number;
    fibre_g: number;
    gl_band: string;
  } | null;
  wellbeing_note: string;
  med_note: string;
}

export interface GlucoseReadingPoint {
  recorded_at: string;
  glucose_mg_dl: number;
  provenance: string;
}

export interface TimelineMarker {
  id: string;
  kind: "meal" | "medication";
  timestamp: string;
  label: string;
  sublabel?: string | null;
  meal_id?: string | null;
}

export interface GlucoseReadingsResponse {
  patient_id: string;
  target_low_mg_dl: number;
  target_high_mg_dl: number;
  latest_glucose_mg_dl: number | null;
  latest_recorded_at: string | null;
  trend_arrow: string;
  source_summary: string;
  readings: GlucoseReadingPoint[];
  markers: TimelineMarker[];
}

export interface DailyPatternHour {
  hour: number;
  label: string;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  sample_count: number;
}

export interface DailyPatternResponse {
  patient_id: string;
  days: number;
  target_low_mg_dl: number;
  target_high_mg_dl: number;
  hours: DailyPatternHour[];
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
  coverage: {
    period_coverage_pct: number;
    daily_coverage_pct_median: number | null;
  };
}

export interface MealResponseItem {
  meal_id: string;
  logged_at: string;
  meal_type: string;
  description: string;
  carbs_g: number | null;
  pre_meal_glucose_mg_dl: number | null;
  peak_post_meal_glucose_mg_dl: number | null;
  excursion_delta_mg_dl: number | null;
  excursion_direction: string;
  iauc_mg_dl_min: number | null;
  iauc_valid: boolean;
  rejection_reasons: string[];
}

export interface IngredientItem {
  name: string;
  name_ur?: string | null;
  grams: number;
  source_reference?: string | null;
}

export interface RecipeNutrition {
  carbs_g: number;
  sugar_g: number;
  fibre_g: number;
  protein_g: number;
  fat_g: number;
  kcal: number;
  estimated_gl: number;
  gl_band: string;
}

export interface RecipeOut {
  id: string;
  slug: string;
  name: string;
  cuisine: string;
  slot: string;
  cost_tier: string;
  prep_min: number;
  servings: number;
  steps: string[];
  image_url: string;
  image_license: string;
  image_is_illustration: boolean;
  tags: string[];
  guidance_note: string;
  ingredients: IngredientItem[];
  nutrition: RecipeNutrition;
}

export interface MealDetailOut {
  meal_id?: string | null;
  recipe: RecipeOut;
  logged_at?: string | null;
  meal_type: string;
  recommended_time_window: string;
  best_time_reason: string;
  personal_history: {
    times_observed: number;
    avg_rise_mg_dl?: number | null;
    avg_peak_mg_dl?: number | null;
    avg_baseline_mg_dl?: number | null;
    estimated_return_minutes?: number | null;
    curve_points: { offset_min: number; glucose_mg_dl: number }[];
    summary_text: string;
  };
  what_it_may_mean: string[];
  health_education_source: string;
  confidence_pct?: number;
  confidence_label?: string;
}

export interface MealPlanResponse {
  patient_id: string;
  slots: {
    slot: string;
    suggested_window: string;
    reason_chip: string;
    recommended_recipes: RecipeOut[];
  }[];
}

export interface ChatSessionOut {
  id: string;
  patient_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string | null;
}

export interface ChatMessageOut {
  id: string;
  session_id: string;
  role: "patient" | "cadie";
  content: string;
  intents: string[];
  cards: Record<string, unknown>[];
  safety_passed: boolean | null;
  created_at: string;
}

export interface ChatTurnResponse {
  session_id: string;
  patient_message: ChatMessageOut;
  cadie_message: ChatMessageOut;
  helpers_used: {
    helper: string;
    agent: string;
    status: string;
    summary: string;
    duration_ms: number;
    data_used: Record<string, unknown>;
  }[];
  memories_added: string[];
  execution_mode: string;
  verifier_report: Record<string, unknown>;
}

export interface MemoryFact {
  id: string;
  fact_type: string;
  fact_text: string;
  confidence: string;
  created_at: string;
}

export interface MedicinesSummaryResponse {
  patient_id: string;
  medications: {
    id: string;
    name: string;
    drug_class: string | null;
    dose: string | null;
    schedule: string | null;
    plain_explanation: string;
    hypo_risk: boolean;
    units_on_hand: number | null;
    days_left: number | null;
  }[];
  recent_events: {
    id: string;
    medication_id: string | null;
    event_time: string;
    status: string;
    notes: string | null;
  }[];
  adaptive_questions?: { id: string; category: string; question: string; reason: string }[];
  agent_summary: {
    findings: { id: string; kind: string; rendered_text: string }[];
  };
  glucose_context?: string[];
}

export interface WellbeingSummaryResponse {
  patient_id: string;
  checkins: {
    id: string;
    logged_at: string;
    stress_score: number | null;
    fatigue_score: number | null;
    sleep_hours: number | null;
    sleep_quality: number | null;
    illness_flag: boolean | null;
    mood_notes: string | null;
  }[];
  adaptive_questions?: { id: string; category: string; question: string; reason: string }[];
  agent_summary: {
    findings: { id: string; kind: string; rendered_text: string }[];
    cards: { type: string; items?: string[] }[];
  };
}

export interface VisitReportResponse {
  patient_id: string;
  display_name: string;
  personal_summary: string[];
  metrics: HeroGlucoseCard;
  medications: string[];
  questions: { question: string; why: string }[];
  clinician_appendix: Record<string, unknown>;
}

export interface PatientPreferencesOut {
  patient_id: string;
  vegetarian: boolean;
  budget_tier: "low" | "medium" | "high";
  city: string;
  gentle_mode: boolean;
  target_low_mg_dl: number;
  target_high_mg_dl: number;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
}

export interface InvestigationRun {
  id: string;
  patient_id: string;
  cohort_type: CohortType;
  is_research_dataset: boolean;
  dataset_label: string;
  execution_mode: "gemini" | "deterministic_fallback";
  model_used: string;
  fallback_reason: string | null;
  primary_summary_patient: string | null;
  primary_summary_clinician: string | null;
  safety_passed: boolean;
  verifier_report: {
    passed: boolean;
    verification_status: string;
    failed_reasons: string[];
    failed_details?: string[];
    details: string[];
    named_thresholds_used: Record<string, string>;
    checked_provenances: string[];
  };
  observations: AgentObservationOut[];
  cross_signal_findings?: string[];
  evidence_items: EvidenceItem[];
  doctor_report: {
    is_safe_to_display: boolean;
    clinician_questions: string[];
  } | null;
  trace?: {
    node: string;
    started_at: string;
    ended_at: string;
    status: string;
    summary: string;
    evidence_count: number;
  }[];
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

export interface DriftSummary {
  patient_id: string;
  cohort_type: CohortType;
  status: string;
  direction: string;
  early_mean_mg_dl: number | null;
  late_mean_mg_dl: number | null;
  delta_mg_dl: number | null;
  exploratory_note: string;
  evidence?: EvidenceItem;
}

export interface AgentObservationOut {
  agent_name: string;
  observation_type: string;
  finding_summary: string;
  confidence: number;
  evidence_refs: string[];
}
