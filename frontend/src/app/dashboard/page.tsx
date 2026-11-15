"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  LogOut,
  Play,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiClient, getStoredToken, setStoredToken } from "@/services/api";
import type {
  DriftSummary,
  GlucoseSummary,
  InvestigationRun,
  MealResponseItem,
  PatientSummary,
} from "@/types/glycadence";

function fmtNum(val: number | null | undefined, digits = 1, suffix = ""): string {
  if (val === null || val === undefined || Number.isNaN(val)) return "—";
  return `${val.toFixed(digits)}${suffix}`;
}

export default function DashboardPage() {
  const router = useRouter();
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
  const [loadingData, setLoadingData] = useState(false);
  const [runningAction, setRunningAction] = useState<"normal" | "bad_draft" | null>(null);
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
    setLoadingData(true);
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
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoadingData(false);
    }
  }, []);

  useEffect(() => {
    if (token && selectedPatientId) {
      void loadPatientData(selectedPatientId);
    }
  }, [token, selectedPatientId, loadPatientData]);

  async function handleAuthSubmit(e: React.FormEvent) {
    e.preventDefault();
    setAuthError(null);
    setAuthBusy(true);
    try {
      if (authMode === "register") {
        await apiClient.register(email, password);
      }
      const tok = await apiClient.login(email, password);
      setToken(tok);
      setPassword("");
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
    setSelectedPatientId("");
    setSummary(null);
    setMeals([]);
    setDrift(null);
    setInvestigations([]);
  }

  async function handleRunInvestigation(simulateBadDraft: boolean) {
    if (!selectedPatientId) return;
    setRunningAction(simulateBadDraft ? "bad_draft" : "normal");
    setDataError(null);
    try {
      const run = await apiClient.runInvestigation(selectedPatientId, {
        mode: "auto",
        simulate_bad_draft: simulateBadDraft,
      });
      setInvestigations((prev) => [run, ...prev]);
      router.push(`/investigations/${run.id}?patientId=${selectedPatientId}`);
    } catch (err) {
      setDataError(err instanceof Error ? err.message : "Investigation failed");
    } finally {
      setRunningAction(null);
    }
  }

  const selectedPatient = patients.find((p) => p.id === selectedPatientId) ?? null;

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              GlyCadence Intelligence Dashboard
            </h1>
            <p className="text-sm text-slate-600">
              Deterministic CGM analytics, provenance coverage, and safety-verified agent investigations.
            </p>
          </div>
          {token && (
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign Out
            </button>
          )}
        </div>

        {!token ? (
          <Card className="max-w-md">
            <CardHeader>
              <CardTitle>{authMode === "login" ? "Sign in to GlyCadence" : "Create Account"}</CardTitle>
              <CardDescription>
                Use a researcher account for ShanghaiT2DM v3 + SYNTH-DEMO-001, or a standard account for SYNTH-DEMO-001.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleAuthSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Email</label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="researcher@example.com"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-[#0F4C5C] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-[#0F4C5C] focus:outline-none"
                  />
                </div>
                {authError && (
                  <p className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                    {authError}
                  </p>
                )}
                <button
                  type="submit"
                  disabled={authBusy}
                  className="w-full rounded-xl bg-[#0F4C5C] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#0c3c49] disabled:opacity-60"
                >
                  {authBusy ? "Authenticating..." : authMode === "login" ? "Sign In" : "Register & Sign In"}
                </button>
                <button
                  type="button"
                  onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
                  className="w-full text-xs text-slate-600 hover:text-slate-900 underline"
                >
                  {authMode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
                </button>
              </form>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Patient / Cohort Selector + Investigation Triggers */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                  <div className="space-y-1">
                    <CardTitle className="text-base">Active Cohort &amp; Subject</CardTitle>
                    <CardDescription>
                      Primary demo path: ShanghaiT2DM v3 (researcher role). Secondary path: SYNTH-DEMO-001.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2.5">
                    <select
                      aria-label="Select subject"
                      value={selectedPatientId}
                      onChange={(e) => setSelectedPatientId(e.target.value)}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-900 focus:border-[#0F4C5C] focus:outline-none"
                    >
                      {patients.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name} ({p.source_dataset} • {p.cohort_type})
                        </option>
                      ))}
                    </select>

                    <button
                      type="button"
                      disabled={!selectedPatientId || runningAction !== null}
                      onClick={() => void handleRunInvestigation(false)}
                      className="inline-flex items-center gap-2 rounded-xl bg-[#0F4C5C] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0c3c49] disabled:opacity-60"
                    >
                      <Play className="h-4 w-4" />
                      {runningAction === "normal" ? "Running..." : "Run Investigation"}
                    </button>

                    <button
                      type="button"
                      disabled={!selectedPatientId || runningAction !== null}
                      onClick={() => void handleRunInvestigation(true)}
                      className="inline-flex items-center gap-2 rounded-xl border border-rose-300 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-100 disabled:opacity-60"
                    >
                      <ShieldAlert className="h-4 w-4" />
                      {runningAction === "bad_draft" ? "Testing Verifier..." : "Demo: Trigger Rejected Bad Draft"}
                    </button>
                  </div>
                </div>
              </CardHeader>

              {selectedPatient?.cohort_type === "research_participant" && (
                <CardContent className="pt-0">
                  <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/90 px-3.5 py-2.5 text-xs text-amber-950">
                    <Database className="h-4 w-4 shrink-0 mt-0.5 text-amber-700" />
                    <div>
                      <span className="font-semibold">Research Dataset — Read-Only:</span>{" "}
                      Source <code className="font-mono">{selectedPatient.source_dataset}</code> (
                      {selectedPatient.external_id ?? selectedPatient.id}). CGM readings carry{" "}
                      <code className="font-mono">dataset_documented</code> provenance per published
                      archive documentation and cannot be mutated by app tracking endpoints.
                    </div>
                  </div>
                </CardContent>
              )}
            </Card>

            {dataError && (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                {dataError}
              </div>
            )}

            {loadingData ? (
              <div className="text-sm text-slate-600 py-8">Loading deterministic analytics...</div>
            ) : (
              <>
                {/* Glycemic Summary + Coverage & Provenance */}
                {summary && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                    <Card className="lg:col-span-2">
                      <CardHeader>
                        <CardTitle>Glycemic Summary</CardTitle>
                        <CardDescription>
                          Standard ADA consensus thresholds: TIR 70–180 mg/dL, TBR &lt;70 mg/dL, TAR &gt;180 mg/dL.
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                            <div className="text-xs text-slate-500">Mean Glucose</div>
                            <div className="text-xl font-bold text-slate-900 mt-1">
                              {fmtNum(summary.mean_glucose_mg_dl, 1, " mg/dL")}
                            </div>
                          </div>
                          <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3">
                            <div className="text-xs text-emerald-800">TIR (70–180)</div>
                            <div className="text-xl font-bold text-emerald-900 mt-1">
                              {fmtNum(summary.tir_pct, 1, "%")}
                            </div>
                          </div>
                          <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3">
                            <div className="text-xs text-rose-800">TBR (&lt;70)</div>
                            <div className="text-xl font-bold text-rose-900 mt-1">
                              {fmtNum(summary.tbr_pct, 1, "%")}
                            </div>
                          </div>
                          <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3">
                            <div className="text-xs text-amber-800">TAR (&gt;180)</div>
                            <div className="text-xl font-bold text-amber-900 mt-1">
                              {fmtNum(summary.tar_pct, 1, "%")}
                            </div>
                          </div>
                          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                            <div className="text-xs text-slate-500">CV%</div>
                            <div className="text-xl font-bold text-slate-900 mt-1">
                              {fmtNum(summary.cv_pct, 1, "%")}
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader>
                        <CardTitle>Coverage &amp; Provenance</CardTitle>
                        <CardDescription>
                          {summary.coverage.total_cgm_observations} CGM observations
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-600">Period coverage</span>
                          <span className="font-semibold text-slate-900">
                            {fmtNum(summary.coverage.period_coverage_pct, 1, "%")}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-600">Deterministic confidence</span>
                          <span className="font-semibold text-slate-900">
                            {fmtNum(summary.coverage.deterministic_confidence, 2)}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <Badge variant="default">native: {summary.native_observation_count}</Badge>
                          <Badge variant="coral">
                            dataset_documented: {summary.dataset_documented_observation_count}
                          </Badge>
                          <Badge variant="neutral">
                            archive_aligned: {summary.archive_aligned_observation_count}
                          </Badge>
                          <Badge variant="neutral">unknown: {summary.unknown_observation_count}</Badge>
                        </div>
                        {summary.coverage.uncertainty_notes.length > 0 && (
                          <ul className="text-xs text-slate-600 space-y-1 pt-1 border-t border-slate-100">
                            {summary.coverage.uncertainty_notes.slice(0, 3).map((n, i) => (
                              <li key={i}>• {n}</li>
                            ))}
                          </ul>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* Meal iAUC + Exploratory Drift */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                  <Card className="lg:col-span-2">
                    <CardHeader>
                      <CardTitle>Meal Post-Prandial iAUC &amp; Excursions</CardTitle>
                      <CardDescription>
                        Incremental area under the curve (mg/dL·min) with explicit validity gating.
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      {meals.length === 0 ? (
                        <p className="text-sm text-slate-500">No meal logs recorded for this subject.</p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-left text-xs">
                            <thead>
                              <tr className="border-b border-slate-200 text-slate-500">
                                <th className="py-2 pr-3 font-medium">Meal</th>
                                <th className="py-2 pr-3 font-medium">Carbs</th>
                                <th className="py-2 pr-3 font-medium">Baseline</th>
                                <th className="py-2 pr-3 font-medium">Peak</th>
                                <th className="py-2 pr-3 font-medium">Excursion</th>
                                <th className="py-2 pr-3 font-medium">iAUC (mg/dL·min)</th>
                                <th className="py-2 font-medium">Status</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {meals.slice(0, 10).map((m) => (
                                <tr key={m.meal_id}>
                                  <td className="py-2 pr-3 font-medium text-slate-900">
                                    {m.meal_type}: {m.description}
                                  </td>
                                  <td className="py-2 pr-3">{m.carbs_g !== null ? `${m.carbs_g}g` : "—"}</td>
                                  <td className="py-2 pr-3">{fmtNum(m.baseline_glucose_mg_dl, 1)}</td>
                                  <td className="py-2 pr-3">{fmtNum(m.peak_glucose_mg_dl, 1)}</td>
                                  <td className="py-2 pr-3">
                                    {fmtNum(m.excursion_mg_dl, 1)} ({m.excursion_direction})
                                  </td>
                                  <td className="py-2 pr-3">{fmtNum(m.iauc_mg_dl_min, 1)}</td>
                                  <td className="py-2">
                                    <Badge variant={m.validity === "valid" ? "default" : "neutral"}>
                                      {m.validity}
                                    </Badge>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle>Exploratory Drift</CardTitle>
                      <CardDescription>Early-half vs late-half mean glucose</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      {drift ? (
                        <>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-600">Status / Direction</span>
                            <Badge variant="neutral">
                              {drift.status} • {drift.direction}
                            </Badge>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-600">Early Mean</span>
                            <span className="font-medium">{fmtNum(drift.early_mean_mg_dl, 1, " mg/dL")}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-600">Late Mean</span>
                            <span className="font-medium">{fmtNum(drift.late_mean_mg_dl, 1, " mg/dL")}</span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-slate-600">Delta</span>
                            <span className="font-semibold">{fmtNum(drift.delta_mg_dl, 1, " mg/dL")}</span>
                          </div>
                          <p className="text-xs text-slate-500 pt-2 border-t border-slate-100">
                            {drift.exploratory_note}
                          </p>
                        </>
                      ) : (
                        <p className="text-xs text-slate-500">No drift summary available.</p>
                      )}
                    </CardContent>
                  </Card>
                </div>

                {/* Recent Investigations */}
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <BrainCircuit className="h-5 w-5 text-[#0F4C5C]" />
                      Recent Investigation Runs
                    </CardTitle>
                    <CardDescription>
                      Every run reports its exact execution_mode, model_used, and Verifier safety gate status.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {investigations.length === 0 ? (
                      <p className="text-sm text-slate-500">
                        No investigations run yet for this subject. Click &ldquo;Run Investigation&rdquo; above.
                      </p>
                    ) : (
                      <div className="space-y-2.5">
                        {investigations.map((inv) => (
                          <Link
                            key={inv.id}
                            href={`/investigations/${inv.id}?patientId=${selectedPatientId}`}
                            className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-xl border border-slate-200 p-3.5 hover:bg-slate-50 transition-colors"
                          >
                            <div className="space-y-1">
                              <div className="flex flex-wrap items-center gap-2">
                                {inv.safety_passed ? (
                                  <Badge variant="default" className="gap-1">
                                    <CheckCircle2 className="h-3 w-3" /> Verifier Passed
                                  </Badge>
                                ) : (
                                  <Badge variant="coral" className="gap-1">
                                    <AlertTriangle className="h-3 w-3" /> Verifier Rejected
                                  </Badge>
                                )}
                                <Badge variant="neutral">mode: {inv.execution_mode}</Badge>
                                <Badge variant="neutral">model: {inv.model_used}</Badge>
                                {inv.is_research_dataset && (
                                  <Badge variant="neutral">Research Dataset (Read-Only)</Badge>
                                )}
                              </div>
                              <div className="text-xs text-slate-600">
                                Run <code className="font-mono">{inv.id}</code> • {inv.dataset_label}
                              </div>
                            </div>
                            <span className="inline-flex items-center gap-1 text-xs font-semibold text-[#0F4C5C]">
                              Inspect Report <ArrowRight className="h-3.5 w-3.5" />
                            </span>
                          </Link>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
