import type {
  DriftSummary,
  GlucoseSummary,
  InvestigationRun,
  MealResponseItem,
  PatientSummary,
} from "@/types/glycadence";
import type { DatabaseHealthResponse, HealthResponse } from "@/types/health";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8010";

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

async function fetchJson<T>(
  path: string,
  options: RequestInit = {},
  allow503 = false
): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!res.ok && !(allow503 && res.status === 503)) {
    let detail = `API request failed (${res.status})`;
    try {
      const errBody = (await res.json()) as { detail?: string };
      if (errBody?.detail) detail = `${errBody.detail} (${res.status})`;
    } catch {
      // ignore non-json error body
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const apiClient = {
  getHealth: () => fetchJson<HealthResponse>("/api/v1/health"),
  getDatabaseHealth: () => fetchJson<DatabaseHealthResponse>("/api/v1/health/db", {}, true),

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

  getAnalyticsSummary: (patientId: string) =>
    fetchJson<GlucoseSummary>(`/api/v1/patients/${patientId}/analytics/summary`),

  getMealResponses: (patientId: string) =>
    fetchJson<MealResponseItem[]>(`/api/v1/patients/${patientId}/analytics/meal-responses`),

  getDrift: (patientId: string) =>
    fetchJson<DriftSummary>(`/api/v1/patients/${patientId}/analytics/drift`),

  listInvestigations: (patientId: string) =>
    fetchJson<InvestigationRun[]>(`/api/v1/patients/${patientId}/investigations`),

  runInvestigation: (
    patientId: string,
    payload: { mode?: "auto" | "gemini" | "deterministic_fallback"; simulate_bad_draft?: boolean } = {}
  ) =>
    fetchJson<InvestigationRun>(`/api/v1/patients/${patientId}/investigations`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getInvestigation: (patientId: string, investigationId: string) =>
    fetchJson<InvestigationRun>(`/api/v1/patients/${patientId}/investigations/${investigationId}`),
};
