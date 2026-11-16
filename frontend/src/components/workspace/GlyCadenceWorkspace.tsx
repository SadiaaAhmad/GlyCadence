"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  HeartPulse,
  Lightbulb,
  Loader2,
  LogOut,
  Pill,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Sun,
  Utensils,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiClient, getStoredToken, setStoredToken } from "@/services/api";
import type {
  DriftSummary,
  EvidenceItem,
  GlucoseSummary,
  InvestigationRun,
  MealResponseItem,
  PatientSummary,
} from "@/types/glycadence";

interface AgentCardSpec {
  key: string;
  traceNode: string;
  title: string;
  subtitle: string;
  accentClass: string;
  icon: React.ComponentType<{ className?: string }>;
}

const AGENT_CARDS: AgentCardSpec[] = [
  {
    key: "pattern",
    traceNode: "pattern_watcher",
    title: "Pattern Watcher Agent",
    subtitle: "Analyzing glucose trends & drift",
    accentClass: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
    icon: Activity,
  },
  {
    key: "diet",
    traceNode: "diet_nutrition",
    title: "Diet & Nutrition Agent",
    subtitle: "Evaluating meal responses & postprandial iAUC",
    accentClass: "bg-sky-500/20 text-sky-300 border-sky-500/40",
    icon: Utensils,
  },
  {
    key: "medication",
    traceNode: "medication_analyst",
    title: "Medication Analyst",
    subtitle: "Verifying regimen & logged events",
    accentClass: "bg-rose-500/20 text-rose-300 border-rose-500/40",
    icon: Pill,
  },
  {
    key: "wellbeing",
    traceNode: "wellbeing_companion",
    title: "Wellbeing Companion",
    subtitle: "Checking stress, fatigue & sleep check-ins",
    accentClass: "bg-teal-500/20 text-teal-300 border-teal-500/40",
    icon: HeartPulse,
  },
  {
    key: "verifier",
    traceNode: "verifier",
    title: "Deterministic Verifier Gate",
    subtitle: "Monitoring safety, grounding & non-causal rules",
    accentClass: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    icon: ShieldCheck,
  },
];

function fmt(val: number | null | undefined, digits = 1, suffix = ""): string {
  if (val === null || val === undefined || Number.isNaN(val)) return "—";
  return `${val.toFixed(digits)}${suffix}`;
}

function primaryProvenance(summary: GlucoseSummary | null): string {
  if (!summary) return "unknown";
  const counts = summary.coverage?.provenance_counts ?? {};
  const entries = Object.entries(counts).filter(([, c]) => c > 0);
  if (entries.length === 0) return "native";
  entries.sort((a, b) => b[1] - a[1]);
  return entries[0][0];
}

export function GlyCadenceWorkspace() {
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authBusy, setAuthBusy] = useState(false);

  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [selectedPatientId, setSelectedPatientId] = useState<string>("");
  const [summary, setSummary] = useState<GlucoseSummary | null>(null);
  const [meals, setMeals] = useState<MealResponseItem[]>([]);
  const [drift, setDrift] = useState<DriftSummary | null>(null);
  const [investigations, setInvestigations] = useState<InvestigationRun[]>([]);
  const [activeRun, setActiveRun] = useState<InvestigationRun | null>(null);

  const [chatInput, setChatInput] = useState("");
  const [lastQuestion, setLastQuestion] = useState(
    "How did my glucose trend recently, and what should I discuss at my next visit?"
  );
  const [runningMode, setRunningMode] = useState<"normal" | "bad_draft" | null>(null);
  const [animatedStage, setAnimatedStage] = useState<number>(5);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceItem | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);

  useEffect(() => {
    setToken(getStoredToken());
  }, []);

  const loadPatients = useCallback(async () => {
    setDataError(null);
    try {
      const list = await apiClient.listPatients();
      setPatients(list);
      if (list.length > 0) {
        setSelectedPatientId((prev) =>
          prev && list.some((p) => p.id === prev) ? prev : list[0].id
        );
      }
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Failed to load patients");
    }
  }, []);

  useEffect(() => {
    if (token) {
      void loadPatients();
    }
  }, [token, loadPatients]);

  const loadPatientData = useCallback(async (pid: string) => {
    if (!pid) return;
    setDataError(null);
    try {
      const [sumRes, mealsRes, driftRes, invRes] = await Promise.all([
        apiClient.getAnalyticsSummary(pid),
        apiClient.getMealResponses(pid),
        apiClient.getDrift(pid),
        apiClient.listInvestigations(pid),
      ]);
      setSummary(sumRes);
      setMeals(mealsRes);
      setDrift(driftRes);
      setInvestigations(invRes);
      setActiveRun(invRes.length > 0 ? invRes[0] : null);
      setAnimatedStage(5);
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Failed to load patient analytics");
    }
  }, []);

  useEffect(() => {
    if (token && selectedPatientId) {
      void loadPatientData(selectedPatientId);
    }
  }, [token, selectedPatientId, loadPatientData]);

  async function handleAuthSubmit(e: React.FormEvent) {
    e.preventDefault();
    setAuthBusy(true);
    setAuthError(null);
    try {
      if (authMode === "register") {
        await apiClient.register(email, password);
      }
      const accessToken = await apiClient.login(email, password);
      setToken(accessToken);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setAuthBusy(false);
    }
  }

  function handleLogout() {
    setStoredToken(null);
    setToken(null);
    setPatients([]);
    setSummary(null);
    setMeals([]);
    setDrift(null);
    setInvestigations([]);
    setActiveRun(null);
  }

  async function triggerInvestigation(simulateBadDraft: boolean, question?: string) {
    if (!selectedPatientId) return;
    if (question && question.trim()) {
      setLastQuestion(question.trim());
    }
    setRunningMode(simulateBadDraft ? "bad_draft" : "normal");
    setAnimatedStage(0);
    setDataError(null);

    const timer = window.setInterval(() => {
      setAnimatedStage((prev) => (prev < 4 ? prev + 1 : prev));
    }, 350);

    try {
      const created = await apiClient.runInvestigation(selectedPatientId, {
        mode: "auto",
        simulate_bad_draft: simulateBadDraft,
      });
      setActiveRun(created);
      setInvestigations((prev) => [created, ...prev]);
      setAnimatedStage(5);
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Investigation failed");
    } finally {
      window.clearInterval(timer);
      setRunningMode(null);
    }
  }

  async function handleChatSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = chatInput.trim();
    if (!q || !selectedPatientId || runningMode !== null) return;
    setChatInput("");
    await triggerInvestigation(false, q);
  }

  const selectedPatient = patients.find((p) => p.id === selectedPatientId) ?? null;

  // Build curved glucose chart series from real meal responses + summary baseline
  const glucoseChartData = useMemo(() => {
    const baseMean = summary?.mean_glucose_mg_dl ?? 124;
    const validMeals = meals.filter((m) => m.baseline_glucose_mg_dl !== null || m.peak_glucose_mg_dl !== null);
    if (validMeals.length > 0) {
      const pts: { label: string; glucose: number }[] = [];
      validMeals.slice(0, 6).forEach((m, idx) => {
        const dt = m.logged_at ? new Date(m.logged_at) : null;
        const timeStr =
          dt && !Number.isNaN(dt.getTime())
            ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : `Meal ${idx + 1}`;
        if (m.baseline_glucose_mg_dl !== null) {
          pts.push({ label: `${timeStr} pre`, glucose: Math.round(m.baseline_glucose_mg_dl) });
        }
        if (m.peak_glucose_mg_dl !== null) {
          pts.push({ label: `${timeStr} peak`, glucose: Math.round(m.peak_glucose_mg_dl) });
        }
      });
      if (pts.length >= 2) return pts;
    }
    return [
      { label: "6 AM", glucose: Math.round(baseMean - 14) },
      { label: "9 AM", glucose: Math.round(baseMean + 8) },
      { label: "12 PM", glucose: Math.round(baseMean + 18) },
      { label: "3 PM", glucose: Math.round(baseMean - 4) },
      { label: "6 PM", glucose: Math.round(baseMean + 11) },
      { label: "9 PM", glucose: Math.round(baseMean - 6) },
    ];
  }, [meals, summary]);

  const traceByNode = useMemo(() => {
    const map = new Map<string, { status: string; summary: string; evidence_count: number }>();
    for (const step of activeRun?.trace ?? []) {
      map.set(step.node, step);
    }
    return map;
  }, [activeRun]);

  if (!token) {
    return (
      <div className="min-h-[82vh] flex items-center justify-center px-4">
        <div className="w-full max-w-md rounded-2xl border border-slate-700/60 bg-[#162032] p-7 shadow-2xl">
          <div className="mb-5">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#FF4D4D]/15 px-3 py-1 text-xs font-semibold text-[#FF4D4D] border border-[#FF4D4D]/30">
              <Sparkles className="h-3.5 w-3.5" />
              GlyCadence Care Team
            </span>
            <h1 className="mt-3 text-2xl font-bold tracking-tight text-white">
              {authMode === "login" ? "Sign in to GlyCadence" : "Create GlyCadence Account"}
            </h1>
            <p className="mt-1 text-xs text-slate-400">
              Use a researcher account for ShanghaiT2DM v3 + SYNTH-DEMO-001, or register a standard account for SYNTH-DEMO-001.
            </p>
          </div>

          <form onSubmit={handleAuthSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="demo@glycadence.local"
                className="w-full rounded-xl border border-slate-700/70 bg-[#0F172A] px-3.5 py-2.5 text-sm text-white placeholder-[#94a3b8] focus:border-[#FF4D4D] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-slate-700/70 bg-[#0F172A] px-3.5 py-2.5 text-sm text-white placeholder-[#94a3b8] focus:border-[#FF4D4D] focus:outline-none"
              />
            </div>

            {authError && (
              <div className="rounded-xl border border-rose-500/40 bg-rose-950/50 px-3.5 py-2.5 text-xs text-rose-200">
                {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={authBusy}
              className="w-full rounded-xl bg-[#FF4D4D] px-4 py-2.5 text-sm font-bold text-white shadow-md transition-colors hover:bg-[#e63e3e] disabled:opacity-60"
            >
              {authBusy ? "Authenticating..." : authMode === "login" ? "Sign In" : "Register & Sign In"}
            </button>

            <button
              type="button"
              onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
              className="w-full text-center text-xs font-medium text-sky-300 hover:text-sky-200 underline"
            >
              {authMode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const prov = primaryProvenance(summary);

  return (
    <div className="space-y-6">
      {/* Top Bar: Patient Selector + Simulate Bad Draft + Sign Out */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedPatientId}
            onChange={(e) => setSelectedPatientId(e.target.value)}
            aria-label="Select patient subject"
            className="rounded-xl border border-slate-700/70 bg-[#162032] px-3.5 py-2 text-sm font-medium text-slate-100 focus:border-[#FF4D4D] focus:outline-none"
          >
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name} ({p.cohort_type})
              </option>
            ))}
          </select>

          {selectedPatient?.cohort_type === "research_participant" && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#FF4D4D]/40 bg-[#FF4D4D]/15 px-3 py-1 text-xs font-semibold text-[#FF4D4D]">
              <Database className="h-3.5 w-3.5" />
              Research Dataset (Read-Only)
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            disabled={runningMode !== null || !selectedPatientId}
            onClick={() => void triggerInvestigation(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-950/40 px-3.5 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-900/50 disabled:opacity-50 transition-colors"
          >
            <ShieldAlert className="h-4 w-4 text-[#FF4D4D]" />
            {runningMode === "bad_draft" ? "Simulating..." : "Simulate Bad Draft"}
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700/70 bg-[#162032] px-3.5 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign Out
          </button>
        </div>
      </div>

      {dataError && (
        <div className="rounded-2xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-xs text-rose-200">
          {dataError}
        </div>
      )}

      {/* ROW 1: Welcome & Interactive Care Team Chat (Left) + Your AI Agent Team (Right) */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* Chat with Your AI Care Team */}
        <section
          id="care-team-chat"
          className="xl:col-span-7 rounded-3xl border border-slate-700/60 bg-[#162032] p-6 flex flex-col justify-between shadow-lg"
        >
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="h-11 w-11 rounded-2xl bg-amber-500/15 border border-amber-400/30 flex items-center justify-center">
                  <Sun className="h-6 w-6 text-amber-400" />
                </div>
                <div>
                  <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-white">
                    Hello, {selectedPatient?.display_name?.split("—")[0]?.trim() || "Care Partner"}!
                  </h1>
                  <p className="text-xs sm:text-sm text-slate-400">
                    Your multi-agent diabetes care team is here to help.
                  </p>
                </div>
              </div>

              {activeRun && (
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 border border-sky-400/30 px-2.5 py-1 text-[11px] font-medium text-sky-300">
                    {activeRun.execution_mode === "gemini" ? (
                      <Bot className="h-3 w-3" />
                    ) : (
                      <Cpu className="h-3 w-3" />
                    )}
                    {activeRun.execution_mode}
                  </span>
                  <span className="rounded-full bg-slate-800 border border-slate-700 px-2.5 py-1 text-[11px] text-slate-300">
                    {activeRun.model_used}
                  </span>
                </div>
              )}
            </div>

            {/* User Question Bubble */}
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-sky-600 px-4 py-3 text-sm text-white shadow-sm">
                {lastQuestion}
              </div>
            </div>

            {/* Synthesized Response Bubble (Safety-Gated) */}
            <div className="rounded-2xl border border-slate-700/70 bg-[#1E293B] p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold text-sky-300 flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-[#FF4D4D]" />
                  Care Team Synthesis
                </span>

                {activeRun ? (
                  activeRun.safety_passed && activeRun.doctor_report?.is_safe_to_display ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 border border-emerald-500/40 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-300">
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Safety Verified
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 border border-rose-500/50 px-2.5 py-0.5 text-[11px] font-semibold text-rose-300">
                      <ShieldAlert className="h-3.5 w-3.5" />
                      Verifier Blocked ({activeRun.verifier_report.failed_reasons.join(", ")})
                    </span>
                  )
                ) : (
                  <span className="text-[11px] text-slate-400">Ask a question below to run agents</span>
                )}
              </div>

              {activeRun?.execution_mode === "deterministic_fallback" && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
                  Deterministic Template Fallback (Not AI-Generated) — assembled with {activeRun.model_used}.
                </div>
              )}

              {activeRun ? (
                activeRun.safety_passed && activeRun.doctor_report?.is_safe_to_display ? (
                  <div className="space-y-2 text-sm text-slate-200 leading-relaxed">
                    <p>{activeRun.primary_summary_patient}</p>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Link
                        href={`/investigations/${activeRun.id}?patientId=${selectedPatientId}`}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
                      >
                        View Full Report &amp; Trace
                      </Link>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-rose-500/40 bg-rose-950/40 p-3 text-xs text-rose-200 space-y-1">
                    <div className="font-semibold flex items-center gap-1.5">
                      <AlertTriangle className="h-4 w-4 text-[#FF4D4D]" />
                      Unsafe Draft Blocked (`is_safe_to_display=false`)
                    </div>
                    <p>
                      Blocked reasons: <code className="font-mono">{activeRun.verifier_report.failed_reasons.join(", ")}</code>
                    </p>
                  </div>
                )
              ) : (
                <p className="text-sm text-slate-400">
                  Type a question below or click Send to run all 5 specialist agents and the Safety Verifier.
                </p>
              )}
            </div>
          </div>

          {/* Interactive Chat Bar */}
          <form onSubmit={handleChatSubmit} className="mt-5 flex items-center gap-2.5">
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask anything about your diabetes care, meals, or trends..."
              className="flex-1 rounded-2xl border border-slate-700/70 bg-[#0F172A] px-4 py-3 text-sm text-white placeholder-[#94a3b8] focus:border-[#FF4D4D] focus:outline-none"
            />
            <button
              type="submit"
              disabled={runningMode !== null || !selectedPatientId}
              aria-label="Send question to AI Care Team"
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#FF4D4D] text-white shadow-md hover:bg-[#e63e3e] disabled:opacity-50 transition-colors"
            >
              {runningMode !== null ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </button>
          </form>
        </section>

        {/* Your AI Agent Team Real-Time Panel */}
        <section className="xl:col-span-5 rounded-3xl border border-slate-700/60 bg-[#162032] p-6 shadow-lg flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-white">Your AI Agent Team</h2>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                {runningMode ? "Running Agents..." : "All Systems Active"}
              </span>
            </div>

            <div className="space-y-3">
              {AGENT_CARDS.map((agent, idx) => {
                const Icon = agent.icon;
                const traceStep = traceByNode.get(agent.traceNode);
                const isRunning = runningMode !== null && animatedStage === idx;
                const isDone = runningMode === null ? Boolean(activeRun) : animatedStage > idx;
                const isRejected = agent.key === "verifier" && activeRun && !activeRun.safety_passed;

                return (
                  <div
                    key={agent.key}
                    className="rounded-2xl border border-slate-700/50 bg-[#1E293B]/80 p-3 flex items-center gap-3"
                  >
                    <div className={`h-9 w-9 shrink-0 rounded-xl border flex items-center justify-center ${agent.accentClass}`}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-white truncate">{agent.title}</span>
                        {isRunning ? (
                          <Loader2 className="h-4 w-4 shrink-0 text-sky-400 animate-spin" />
                        ) : isRejected ? (
                          <ShieldAlert className="h-4 w-4 shrink-0 text-[#FF4D4D]" />
                        ) : isDone ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                        ) : (
                          <span className="text-[10px] text-slate-400">Ready</span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400 truncate mt-0.5">
                        {traceStep ? traceStep.summary : agent.subtitle}
                      </p>
                      <div className="mt-1.5 h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className={`h-full transition-all duration-300 ${
                            isRejected
                              ? "bg-[#FF4D4D] w-full"
                              : isDone
                              ? "bg-emerald-400 w-full"
                              : isRunning
                              ? "bg-sky-400 w-2/3"
                              : "bg-slate-600 w-1/4"
                          }`}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Collaborative Analysis Complete + Key Insight */}
          <div className="mt-4 rounded-2xl border border-slate-700/60 bg-[#0F172A]/80 p-3.5 flex items-start gap-3">
            <div className="h-8 w-8 shrink-0 rounded-xl bg-amber-500/15 border border-amber-400/30 flex items-center justify-center">
              <Lightbulb className="h-4 w-4 text-amber-400" />
            </div>
            <div className="text-xs">
              <div className="font-semibold text-white">
                {activeRun
                  ? activeRun.safety_passed
                    ? "Collaborative Analysis Complete"
                    : "Safety Gate Blocked Unsafe Output"
                  : "Key Insight Ready"}
              </div>
              <p className="text-slate-400 mt-0.5 line-clamp-2">
                {activeRun?.cross_signal_findings?.[0] ??
                  drift?.exploratory_note ??
                  "Deterministic CGM, meal iAUC, and wellbeing signals are ready."}
              </p>
            </div>
          </div>
        </section>
      </div>

      {/* ROW 2: Interactive Glucose Dashboard + Meal Guidance + Doctor Discussion Points */}
      <div id="glucose-insights" className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Interactive Glucose Dashboard */}
        <section className="lg:col-span-5 rounded-3xl border border-slate-700/60 bg-[#162032] p-6 shadow-lg space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-white">Your Glucose Dashboard</h2>
              <p className="text-xs text-slate-400">Green band: 70–180 mg/dL target range</p>
            </div>
            <span className="rounded-full border border-indigo-400/30 bg-indigo-500/15 px-2.5 py-1 text-[11px] font-semibold text-indigo-300">
              {prov}
            </span>
          </div>

          {/* Stat Cards */}
          <div className="grid grid-cols-3 gap-2.5">
            <div className="rounded-2xl border border-slate-700/60 bg-[#1E293B] p-3">
              <div className="text-[11px] text-slate-400">Avg Glucose</div>
              <div className="text-lg font-bold text-white mt-0.5">
                {fmt(summary?.mean_glucose_mg_dl, 0)} <span className="text-[10px] text-slate-400">mg/dL</span>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-700/60 bg-[#1E293B] p-3">
              <div className="text-[11px] text-slate-400">Time in Range</div>
              <div className="text-lg font-bold text-emerald-400 mt-0.5">
                {fmt(summary?.tir_pct, 1, "%")}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-700/60 bg-[#1E293B] p-3">
              <div className="text-[11px] text-slate-400">Coverage</div>
              <div className="text-lg font-bold text-sky-300 mt-0.5">
                {fmt(summary?.coverage.period_coverage_pct, 0, "%")}
              </div>
            </div>
          </div>

          {/* Curved Recharts Glucose Chart */}
          <div className="h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={glucoseChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="glucoseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
                <XAxis dataKey="label" stroke="#94a3b8" fontSize={10} />
                <YAxis domain={[50, 240]} stroke="#94a3b8" fontSize={10} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "12px",
                    color: "#f8fafc",
                    fontSize: "12px",
                  }}
                />
                <ReferenceArea y1={70} y2={180} fill="#10b981" fillOpacity={0.12} />
                <Area
                  type="monotone"
                  dataKey="glucose"
                  stroke="#38bdf8"
                  strokeWidth={2.5}
                  fill="url(#glucoseFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        {/* Meal Guidance (Neutral Wording) */}
        <section className="lg:col-span-3 rounded-3xl border border-slate-700/60 bg-[#162032] p-6 shadow-lg space-y-3">
          <h2 className="text-base font-bold text-white">Meal Guidance</h2>
          <p className="text-xs text-slate-400">
            Neutral observed post-meal responses (based on logged meals).
          </p>
          <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
            {meals.length === 0 ? (
              <div className="rounded-2xl border border-slate-700/60 bg-[#1E293B] p-3.5 text-xs text-slate-400">
                No meal responses logged in this window.
              </div>
            ) : (
              meals.slice(0, 4).map((m) => (
                <div
                  key={m.meal_id}
                  className="rounded-2xl border border-slate-700/60 bg-[#1E293B] p-3 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-white truncate">{m.description}</span>
                    <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] text-sky-300">
                      {m.meal_type}
                    </span>
                  </div>
                  <div className="text-slate-300">
                    {m.validity === "valid"
                      ? `Observed peak ${fmt(m.peak_glucose_mg_dl, 0)} mg/dL • iAUC ${fmt(m.iauc_mg_dl_min, 0)}`
                      : `Insufficient post-meal window (${m.rejection_reason ?? "coverage"})`}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Verified Doctor Discussion Points & Evidence Drawer */}
        <section className="lg:col-span-4 rounded-3xl border border-slate-700/60 bg-[#162032] p-6 shadow-lg space-y-3">
          <h2 className="text-base font-bold text-white">Doctor Discussion Points</h2>
          <p className="text-xs text-slate-400">
            Click any EvidenceItem tag below to inspect its SHA-256 provenance.
          </p>

          {activeRun?.doctor_report?.is_safe_to_display &&
          activeRun.doctor_report.clinician_questions.length > 0 ? (
            <ul className="space-y-2 text-xs text-slate-200">
              {activeRun.doctor_report.clinician_questions.slice(0, 4).map((q, i) => (
                <li
                  key={i}
                  className="rounded-xl border border-slate-700/60 bg-[#1E293B] px-3 py-2 leading-relaxed"
                >
                  {q}
                </li>
              ))}
            </ul>
          ) : (
            <div className="rounded-xl border border-slate-700/60 bg-[#1E293B] p-3 text-xs text-slate-400">
              {activeRun && !activeRun.safety_passed
                ? "Discussion points suppressed because Verifier Gate rejected the draft."
                : "Run an investigation to generate safety-verified clinician questions."}
            </div>
          )}

          {activeRun && activeRun.evidence_items.length > 0 && (
            <div className="pt-1 space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                EvidenceItem Tags ({activeRun.evidence_items.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {activeRun.evidence_items.slice(0, 6).map((ev) => (
                  <button
                    key={ev.evidence_id}
                    type="button"
                    onClick={() => setSelectedEvidence(ev)}
                    className={`rounded-lg border px-2 py-1 text-[10px] font-mono transition-colors ${
                      selectedEvidence?.evidence_id === ev.evidence_id
                        ? "border-[#FF4D4D] bg-[#FF4D4D]/20 text-white"
                        : "border-slate-700 bg-[#0F172A] text-sky-300 hover:border-sky-400/50"
                    }`}
                  >
                    {ev.metric_name}
                  </button>
                ))}
              </div>
              {selectedEvidence && (
                <div className="rounded-xl border border-slate-700 bg-[#0F172A] p-2.5 text-[11px] font-mono text-slate-300 space-y-0.5">
                  <div>
                    value: {selectedEvidence.value ?? "null"} {selectedEvidence.unit ?? ""}
                  </div>
                  <div className="truncate">sha256: {selectedEvidence.source_record_set_checksum}</div>
                  <div>provenance: {selectedEvidence.allowed_provenances.join(", ")}</div>
                </div>
              )}
            </div>
          )}

          {investigations.length > 1 && (
            <div className="text-[11px] text-slate-400 pt-1">
              Recent runs: {investigations.length} stored for this subject.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
