import type { DatabaseHealthResponse, HealthResponse } from "@/types/health";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8010";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  const data = (await res.json()) as T;
  if (!res.ok && res.status !== 503) {
    throw new Error(`API request failed (${res.status})`);
  }
  return data;
}

export const apiClient = {
  getHealth: () => fetchJson<HealthResponse>("/api/v1/health"),
  getDatabaseHealth: () => fetchJson<DatabaseHealthResponse>("/api/v1/health/db"),
};
