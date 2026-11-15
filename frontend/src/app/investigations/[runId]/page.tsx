"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  FileCheck2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiClient, getStoredToken } from "@/services/api";
import type { InvestigationRun } from "@/types/glycadence";

function formatDurationMs(startIso: string, endIso: string): string {
  const s = Date.parse(startIso);
  const e = Date.parse(endIso);
  if (Number.isNaN(s) || Number.isNaN(e)) return "—";
  const ms = Math.max(0, e - s);
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function InvestigationDetailContent() {
  const params = useParams<{ runId: string }>();
  const searchParams = useSearchParams();
  const runId = params?.runId;
  const queryPatientId = searchParams.get("patientId");

  const [run, setRun] = useState<InvestigationRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      if (!runId) return;
      const token = getStoredToken();
      if (!token) {
        setError("Please sign in on the Intelligence Dashboard to inspect this investigation.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        if (queryPatientId) {
          const data = await apiClient.getInvestigation(queryPatientId, runId);
          setRun(data);
        } else {
          const patients = await apiClient.listPatients();
          let found: InvestigationRun | null = null;
          for (const p of patients) {
            try {
              found = await apiClient.getInvestigation(p.id, runId);
              break;
            } catch {
              // try next accessible patient
            }
          }
          if (!found) {
            throw new Error("Investigation run not found among accessible patients.");
          }
          setRun(found);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load investigation");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [runId, queryPatientId]);

  const traceSteps = run?.trace ?? [];
  const crossSignals = run?.cross_signal_findings ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[#0F4C5C] dark:text-teal-300 hover:underline"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Intelligence Dashboard
        </Link>
      </div>

      {loading && <p className="text-sm text-slate-600 dark:text-slate-400">Loading investigation run...</p>}

      {error && (
        <Card className="border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/30">
          <CardContent className="pt-6 text-sm text-rose-800 dark:text-rose-200">{error}</CardContent>
        </Card>
      )}

      {run && (
        <>
          {/* Execution Mode & Model Attribution Banner */}
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                  <CardTitle className="text-xl">Investigation Run Report</CardTitle>
                  <CardDescription>
                    Run ID <code className="font-mono">{run.id}</code> • {run.dataset_label}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={run.execution_mode === "gemini" ? "default" : "neutral"} className="gap-1">
                    {run.execution_mode === "gemini" ? (
                      <Bot className="h-3.5 w-3.5" />
                    ) : (
                      <Cpu className="h-3.5 w-3.5" />
                    )}
                    execution_mode: {run.execution_mode}
                  </Badge>
                  <Badge variant="neutral">model_used: {run.model_used}</Badge>
                  {run.is_research_dataset && (
                    <Badge variant="coral" className="gap-1">
                      <Database className="h-3.5 w-3.5" />
                      Research Dataset (Read-Only)
                    </Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            {run.execution_mode === "deterministic_fallback" && (
              <CardContent className="pt-0">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
                  <span className="font-semibold">Deterministic Template Fallback (Not AI-Generated):</span>{" "}
                  This report was assembled deterministically using{" "}
                  <code className="font-mono">{run.model_used}</code>
                  {run.fallback_reason ? ` (${run.fallback_reason})` : ""}. It is never labeled as AI-generated.
                </div>
              </CardContent>
            )}
          </Card>

          {/* Verifier Safety Gate */}
          <Card
            className={
              run.safety_passed
                ? "border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20"
                : "border-rose-300 bg-rose-50/60 dark:border-rose-900 dark:bg-rose-950/30"
            }
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {run.safety_passed ? (
                  <>
                    <ShieldCheck className="h-5 w-5 text-emerald-700 dark:text-emerald-400" />
                    Verifier Gate: PASSED
                  </>
                ) : (
                  <>
                    <ShieldAlert className="h-5 w-5 text-rose-700 dark:text-rose-400" />
                    Verifier Gate: REJECTED (Unsafe Draft Blocked)
                  </>
                )}
              </CardTitle>
              <CardDescription>
                Named glycemic thresholds &amp; provenance rules enforced before surfacing any narrative.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              {!run.safety_passed && (
                <div className="rounded-2xl border border-rose-200 bg-white p-3.5 space-y-1.5 dark:border-rose-900 dark:bg-slate-900">
                  <div className="font-semibold text-rose-900 dark:text-rose-300">
                    Blocked Reasons: {run.verifier_report.failed_reasons.join(", ")}
                  </div>
                  <ul className="space-y-1 text-rose-800 dark:text-rose-200">
                    {run.verifier_report.details.map((d, idx) => (
                      <li key={idx}>• {d}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                {Object.entries(run.verifier_report.named_thresholds_used).map(([k, v]) => (
                  <Badge key={k} variant="neutral">
                    {k}: {v}
                  </Badge>
                ))}
              </div>
              <div className="text-slate-600 dark:text-slate-400">
                Checked provenances:{" "}
                <code className="font-mono">{run.verifier_report.checked_provenances.join(", ")}</code>
              </div>
            </CardContent>
          </Card>

          {/* Doctor Report & Patient Summary (Strictly Safety-Gated) */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileCheck2 className="h-5 w-5 text-[#0F4C5C] dark:text-teal-300" />
                Doctor Visit Report &amp; Patient Summary
              </CardTitle>
              <CardDescription>
                is_safe_to_display: {String(Boolean(run.doctor_report?.is_safe_to_display))}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!run.safety_passed || !run.doctor_report?.is_safe_to_display ? (
                <div className="flex items-start gap-2.5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
                  <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5 text-rose-700 dark:text-rose-400" />
                  <div>
                    <div className="font-semibold">Narrative Suppressed by Safety Verifier</div>
                    <p className="text-xs mt-1 text-rose-800 dark:text-rose-300">
                      This draft failed grounding/safety verification (<code>is_safe_to_display=false</code>).
                      Unverified numeric, causal, or prescriptive claims are never displayed to patients or clinicians.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Patient Summary
                    </div>
                    <p className="text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                      {run.primary_summary_patient}
                    </p>
                  </div>

                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Clinician Summary
                    </div>
                    <p className="text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                      {run.primary_summary_clinician}
                    </p>
                  </div>

                  {run.doctor_report.clinician_questions.length > 0 && (
                    <div className="space-y-2 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-800/40">
                      <div className="text-xs font-semibold uppercase tracking-wide text-[#0F4C5C] dark:text-teal-300">
                        Suggested Patient Questions for Clinician Visit
                      </div>
                      <ul className="list-disc pl-5 text-sm text-slate-700 dark:text-slate-200 space-y-1.5">
                        {run.doctor_report.clinician_questions.map((q, i) => (
                          <li key={i}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          {/* Cross-Signal Findings */}
          {crossSignals.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Sparkles className="h-4 w-4 text-[#FF4D4D]" />
                  Cross-Signal Co-Occurrence Findings
                </CardTitle>
                <CardDescription>
                  Deterministic correlations across glucose, meals, medications, and wellbeing in the same window.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {crossSignals.map((item, idx) => (
                  <div
                    key={idx}
                    className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3 text-xs text-slate-700 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-200"
                  >
                    {item}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Agent Trace Timeline */}
          {traceSteps.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Activity className="h-4 w-4 text-[#0F4C5C] dark:text-teal-300" />
                  Agent Execution Trace Timeline
                </CardTitle>
                <CardDescription>
                  Per-node execution order, status, timing, and grounded evidence count.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {traceSteps.map((step, idx) => (
                  <div
                    key={`${step.node}-${idx}`}
                    className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 rounded-2xl border border-slate-200/80 bg-slate-50/60 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-800/40"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <CheckCircle2
                          className={
                            step.status === "rejected"
                              ? "h-4 w-4 text-rose-600"
                              : "h-4 w-4 text-emerald-600 dark:text-emerald-400"
                          }
                        />
                        <span className="font-mono font-semibold text-slate-900 dark:text-white">
                          {step.node}
                        </span>
                        <Badge variant={step.status === "rejected" ? "coral" : "neutral"}>
                          {step.status}
                        </Badge>
                      </div>
                      <p className="text-slate-600 dark:text-slate-300 pl-6">{step.summary}</p>
                    </div>
                    <div className="flex items-center gap-3 pl-6 sm:pl-0 shrink-0 text-slate-500 dark:text-slate-400">
                      <span className="inline-flex items-center gap-1 font-mono">
                        <Clock className="h-3.5 w-3.5" />
                        {formatDurationMs(step.started_at, step.ended_at)}
                      </span>
                      <Badge variant="neutral">{step.evidence_count} evidence</Badge>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Agent Observations & Evidence Grounding */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Specialist Agent Observations</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {run.observations.map((obs, idx) => (
                  <div
                    key={idx}
                    className="rounded-2xl border border-slate-200/80 p-3.5 text-xs space-y-1 dark:border-slate-800"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-900 dark:text-white">
                        {obs.agent_name} ({obs.observation_type})
                      </span>
                      <Badge variant="neutral">conf: {obs.confidence.toFixed(2)}</Badge>
                    </div>
                    <p className="text-slate-700 dark:text-slate-300">{obs.finding_summary}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Evidence Grounding Drawer</CardTitle>
                <CardDescription>
                  Deterministic EvidenceItem records &amp; SHA-256 source_record_set_checksums
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2.5 max-h-96 overflow-y-auto">
                {run.evidence_items.map((ev) => (
                  <div
                    key={ev.evidence_id}
                    className="rounded-2xl border border-slate-200/80 p-3.5 text-xs space-y-1 dark:border-slate-800"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900 dark:text-white">{ev.metric_name}</span>
                      <span className="font-mono text-slate-700 dark:text-slate-300">
                        {ev.value !== null ? `${ev.value} ${ev.unit ?? ""}` : "null"}
                      </span>
                    </div>
                    <div className="text-slate-500 dark:text-slate-400 font-mono truncate">
                      checksum: {ev.source_record_set_checksum}
                    </div>
                    <div className="text-slate-500 dark:text-slate-400">
                      provenances: {ev.allowed_provenances.join(", ")} • v{ev.calculation_version}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

export default function InvestigationDetailPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-600">Loading investigation...</div>}>
      <InvestigationDetailContent />
    </Suspense>
  );
}
