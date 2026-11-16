"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { apiClient, getStoredToken, setStoredToken } from "@/services/api";
import type { PatientSummary } from "@/types/glycadence";

interface PatientContextValue {
  token: string | null;
  patients: PatientSummary[];
  activePatient: PatientSummary | null;
  activePatientId: string;
  setActivePatientId: (id: string) => void;
  reloadPatients: () => Promise<void>;
  logout: () => void;
  dark: boolean;
  toggleDark: () => void;
}

const PatientContext = createContext<PatientContextValue | null>(null);

export function usePatientContext(): PatientContextValue {
  const ctx = useContext(PatientContext);
  if (!ctx) throw new Error("usePatientContext must be used inside PatientProvider");
  return ctx;
}

export function PatientProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [activePatientId, setActivePatientIdState] = useState<string>("");
  const [dark, setDark] = useState(false);

  // Auth form state
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    setToken(getStoredToken());
    const savedTheme = window.localStorage.getItem("glycadence_saffron_theme");
    const isDark = savedTheme === "dark";
    setDark(isDark);
    document.documentElement.classList.toggle("dark", isDark);
    setReady(true);

    const onUnauthorized = () => {
      setToken(null);
      setPatients([]);
      setActivePatientIdState("");
    };
    window.addEventListener("glycadence:unauthorized", onUnauthorized);
    return () => window.removeEventListener("glycadence:unauthorized", onUnauthorized);
  }, []);

  const toggleDark = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", next);
      window.localStorage.setItem("glycadence_saffron_theme", next ? "dark" : "light");
      return next;
    });
  }, []);

  const reloadPatients = useCallback(async () => {
    if (!getStoredToken()) return;
    try {
      const list = await apiClient.listPatients();
      setPatients(list);
      const savedPid = window.localStorage.getItem("glycadence_active_patient_id");
      if (savedPid && list.some((p) => p.id === savedPid)) {
        setActivePatientIdState(savedPid);
      } else if (list.length > 0) {
        setActivePatientIdState(list[0].id);
      }
    } catch {
      // ignore if token expired
    }
  }, []);

  useEffect(() => {
    if (token) {
      void reloadPatients();
    }
  }, [token, reloadPatients]);

  const setActivePatientId = useCallback((id: string) => {
    setActivePatientIdState(id);
    window.localStorage.setItem("glycadence_active_patient_id", id);
  }, []);

  const logout = useCallback(() => {
    setStoredToken(null);
    setToken(null);
    setPatients([]);
    setActivePatientIdState("");
  }, []);

  async function handleAuth(e: React.FormEvent) {
    e.preventDefault();
    setAuthBusy(true);
    setAuthError(null);
    try {
      if (authMode === "register") {
        await apiClient.register(email, password);
      }
      const tok = await apiClient.login(email, password);
      setToken(tok);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setAuthBusy(false);
    }
  }

  const activePatient = patients.find((p) => p.id === activePatientId) ?? null;

  if (!ready) return null;

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 bg-[var(--bg-page)]">
        <div className="gc-card w-full max-w-md p-7">
          <div className="inline-flex items-center gap-1.5 rounded-full bg-[#FF4D4D]/12 px-3 py-1 text-xs font-semibold text-[#FF4D4D]">
            <Sparkles className="h-3.5 w-3.5" />
            GlyCadence Companion
          </div>
          <h1 className="font-display text-2xl font-semibold mt-3">
            {authMode === "login" ? "Welcome back" : "Create your account"}
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Warm, everyday diabetes support tailored to your meals, medicines, and routines.
          </p>

          <form onSubmit={handleAuth} className="mt-5 space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="amina@example.com"
                className="w-full rounded-[14px] border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2.5 text-sm focus:border-[#FF4D4D] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                className="w-full rounded-[14px] border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2.5 text-sm focus:border-[#FF4D4D] focus:outline-none"
              />
            </div>

            {authError && (
              <div className="rounded-xl bg-[#8E2C5A]/12 border border-[#8E2C5A]/30 px-3 py-2 text-sm text-[#8E2C5A]">
                {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={authBusy}
              className="w-full rounded-[14px] bg-[#FF4D4D] py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[#e84141] disabled:opacity-60"
            >
              {authBusy ? "Signing in..." : authMode === "login" ? "Sign In" : "Register & Sign In"}
            </button>

            <button
              type="button"
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="w-full text-center text-sm text-[var(--text-muted)] underline hover:text-[var(--text-ink)]"
            >
              {authMode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <PatientContext.Provider
      value={{
        token,
        patients,
        activePatient,
        activePatientId,
        setActivePatientId,
        reloadPatients,
        logout,
        dark,
        toggleDark,
      }}
    >
      {children}
    </PatientContext.Provider>
  );
}
