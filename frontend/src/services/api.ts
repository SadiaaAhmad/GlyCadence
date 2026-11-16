import type {
  ChatMessageOut,
  ChatSessionOut,
  ChatTurnResponse,
  DailyPatternResponse,
  GlucoseReadingsResponse,
  GlucoseSummary,
  InvestigationRun,
  MealDetailOut,
  MealPlanResponse,
  MealResponseItem,
  MedicinesSummaryResponse,
  MemoryFact,
  PatientPreferencesOut,
  PatientSummary,
  RecipeOut,
  TodayOverview,
  VisitReportResponse,
  WellbeingSummaryResponse,
} from "@/types/glycadence";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8010";

const TOKEN_STORAGE_KEY = "glycadence_access_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const resp = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (resp.status === 401 && !path.startsWith("/api/v1/auth/")) {
    setStoredToken(null);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("glycadence:unauthorized"));
    }
  }
  if (!resp.ok) {
    let message = `Request failed (${resp.status})`;
    try {
      const errBody = await resp.json();
      if (typeof errBody?.detail === "string") message = errBody.detail;
      else if (typeof errBody?.detail?.message === "string") message = errBody.detail.message;
    } catch {
      // ignore non-json
    }
    throw new Error(message);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const apiClient = {
  getHealth: () =>
    fetchJson<{ status: "ok"; service: string; version: string; environment: string; timestamp: string }>(
      "/api/v1/health"
    ),
  getDatabaseHealth: () =>
    fetchJson<{
      status: "ok" | "unavailable";
      database: "connected" | "database_not_configured" | "unsupported_database_version" | "database_unavailable";
      min_required_major_version: number;
      detected_major_version: number;
      timestamp: string;
    }>("/api/v1/health/db"),
  getDrift: (pid: string) =>
    fetchJson<{ status: string; exploratory_note: string }>(`/api/v1/patients/${pid}/analytics/drift`),
  listInvestigations: (pid: string) =>
    fetchJson<InvestigationRun[]>(`/api/v1/patients/${pid}/investigations`),
  login: async (email: string, password: string): Promise<string> => {
    const data = await fetchJson<{ access_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setStoredToken(data.access_token);
    return data.access_token;
  },

  register: async (email: string, password: string): Promise<void> => {
    await fetchJson("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  listPatients: () => fetchJson<PatientSummary[]>("/api/v1/patients"),
  getTodayOverview: (pid: string) => fetchJson<TodayOverview>(`/api/v1/patients/${pid}/overview`),
  getAnalyticsSummary: (pid: string) =>
    fetchJson<GlucoseSummary>(`/api/v1/patients/${pid}/analytics/summary?native_only=false&include_non_native=true`),
  getMealResponses: (pid: string) =>
    fetchJson<MealResponseItem[]>(`/api/v1/patients/${pid}/analytics/meal-responses?native_only=false&include_non_native=true`),
  getGlucoseReadings: (pid: string, days = 7) =>
    fetchJson<GlucoseReadingsResponse>(`/api/v1/patients/${pid}/glucose/readings?days=${days}`),
  getDailyPattern: (pid: string, days = 14) =>
    fetchJson<DailyPatternResponse>(`/api/v1/patients/${pid}/glucose/daily-pattern?days=${days}`),

  listRecipes: (params: { slot?: string; vegetarian?: boolean; budget?: string; q?: string } = {}) => {
    const sp = new URLSearchParams();
    if (params.slot) sp.set("slot", params.slot);
    if (params.vegetarian) sp.set("vegetarian", "true");
    if (params.budget) sp.set("budget", params.budget);
    if (params.q) sp.set("q", params.q);
    const qs = sp.toString();
    return fetchJson<RecipeOut[]>(`/api/v1/recipes${qs ? `?${qs}` : ""}`);
  },
  getRecipeDetail: (recipeId: string, pid?: string) =>
    fetchJson<MealDetailOut>(`/api/v1/recipes/${recipeId}${pid ? `?patient_id=${pid}` : ""}`),
  getMealPlan: (pid: string) => fetchJson<MealPlanResponse>(`/api/v1/patients/${pid}/meals/plan`),
  getPatientMealDetail: (pid: string, mealId: string) =>
    fetchJson<MealDetailOut>(`/api/v1/patients/${pid}/meals/${mealId}`),

  listChatSessions: (pid: string, q?: string) =>
    fetchJson<ChatSessionOut[]>(`/api/v1/patients/${pid}/chat/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createChatSession: (pid: string, title?: string) =>
    fetchJson<ChatSessionOut>(`/api/v1/patients/${pid}/chat/sessions`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  getChatMessages: (pid: string, sid: string) =>
    fetchJson<ChatMessageOut[]>(`/api/v1/patients/${pid}/chat/sessions/${sid}/messages`),
  sendChatMessage: (pid: string, sid: string, content: string, mode: "auto" | "gemini" | "deterministic_fallback" = "auto") =>
    fetchJson<ChatTurnResponse>(`/api/v1/patients/${pid}/chat/sessions/${sid}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, mode }),
    }),

  listMemory: (pid: string) => fetchJson<MemoryFact[]>(`/api/v1/patients/${pid}/memory`),
  deleteMemory: (pid: string, memId: string) =>
    fetchJson<void>(`/api/v1/patients/${pid}/memory/${memId}`, { method: "DELETE" }),

  getMedicinesSummary: (pid: string) =>
    fetchJson<MedicinesSummaryResponse>(`/api/v1/patients/${pid}/medicines/summary`),
  logMedicine: (pid: string, medication_id: string, status: "taken" | "delayed" | "missed" | "skipped") =>
    fetchJson(`/api/v1/patients/${pid}/medicines/log`, {
      method: "POST",
      body: JSON.stringify({ medication_id, status }),
    }),

  getWellbeingSummary: (pid: string) =>
    fetchJson<WellbeingSummaryResponse>(`/api/v1/patients/${pid}/wellbeing/summary`),
  createCheckin: (
    pid: string,
    body: { stress_score: number; fatigue_score: number; sleep_hours: number; sleep_quality: number; illness_flag: boolean; mood_notes?: string }
  ) =>
    fetchJson(`/api/v1/patients/${pid}/wellbeing/checkins`, { method: "POST", body: JSON.stringify(body) }),
  scoreDDS2: (pid: string, body: { feeling_overwhelmed_1_to_6: number; failing_routine_1_to_6: number }) =>
    fetchJson<{ average_score: number; elevated_distress: boolean; message: string }>(
      `/api/v1/patients/${pid}/wellbeing/dds2`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  getRamadanPlan: (pid: string) => fetchJson<{ patient_id: string; roza: Record<string, unknown> }>(`/api/v1/patients/${pid}/fasting/plan`),
  postFastingRiskCheck: (pid: string, body: { egfr?: number; pregnant: boolean; extra_recent_hypos: number }) =>
    fetchJson<{ score: number; risk_tier: string; reasons: string[]; summary: string; break_fast_rules: string[] }>(
      `/api/v1/patients/${pid}/fasting/risk-check`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  getVisitReport: (pid: string) => fetchJson<VisitReportResponse>(`/api/v1/patients/${pid}/visit-report`),
  getExercisePlan: (pid: string) =>
    fetchJson<{ patient_id: string; mover: { findings: { id: string; rendered_text: string }[]; cards: Record<string, unknown>[] } }>(
      `/api/v1/patients/${pid}/exercise/plan`
    ),
  logExercise: (pid: string, body: { activity_type: string; duration_min: number; intensity: "low" | "moderate" | "vigorous" }) =>
    fetchJson(`/api/v1/patients/${pid}/exercise/log`, { method: "POST", body: JSON.stringify(body) }),
  getPreferences: (pid: string) => fetchJson<PatientPreferencesOut>(`/api/v1/patients/${pid}/preferences`),
  updatePreferences: (pid: string, body: Partial<PatientPreferencesOut>) =>
    fetchJson<PatientPreferencesOut>(`/api/v1/patients/${pid}/preferences`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  runInvestigation: (pid: string, payload: { mode?: "auto" | "gemini" | "deterministic_fallback"; simulate_bad_draft?: boolean } = {}) =>
    fetchJson<InvestigationRun>(`/api/v1/patients/${pid}/investigations`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getInvestigation: (pid: string, runId: string) =>
    fetchJson<InvestigationRun>(`/api/v1/patients/${pid}/investigations/${runId}`),
};
