"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Cpu,
  Database,
  FileCheck2,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { apiClient, getStoredToken } from "@/services/api";
import type { InvestigationRun } from "@/types/glycadence";

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[#0F4C5C] hover:underline"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Intelligence Dashboard
        </Link>
      </div>

      {loading && <p className="text-sm text-slate-600">Loading investigation run...</p>}

      {error && (
        <Card className="border-rose-200 bg-rose-50">
          <CardContent className="pt-6 text-sm text-rose-800">{error}</CardContent>
        </Card>
      )}

      {run && (
        <>
          {/* Execution Mode & Model Attribution Banner */}
          <Card>
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                  <CardTitle>Investigation Run Report</CardTitle>
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
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-xs text-slate-700">
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
              run.safety_passed ? "border-emerald-200 bg-emerald-50/40" : "border-rose-300 bg-rose-50/60"
            }
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {run.safety_passed ? (
                  <>
                    <ShieldCheck className="h-5 w-5 text-emerald-700" />
                    Verifier Gate: PASSED
                  </>
                ) : (
                  <>
                    <ShieldAlert className="h-5 w-5 text-rose-700" />
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
                <div className="rounded-xl border border-rose-200 bg-white p-3 space-y-1.5">
                  <div className="font-semibold text-rose-900">
                    Blocked Reasons: {run.verifier_report.failed_reasons.join(", ")}
                  </div>
                  <ul className="space-y-1 text-rose-800">
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
              <div className="text-slate-600">
                Checked provenances:{" "}
                <code className="font-mono">{run.verifier_report.checked_provenances.join(", ")}</code>
              </div>
            </CardContent>
          </Card>

          {/* Doctor Report & Patient Summary (Strictly Safety-Gated) */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileCheck2 className="h-5 w-5 text-[#0F4C5C]" />
                Doctor Visit Report &amp; Patient Summary
              </CardTitle>
              <CardDescription>
                is_safe_to_display: {String(Boolean(run.doctor_report?.is_safe_to_display))}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!run.safety_passed || !run.doctor_report?.is_safe_to_display ? (
                <div className="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
                  <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5 text-rose-700" />
                  <div>
                    <div className="font-semibold">Narrative Suppressed by Safety Verifier</div>
                    <p className="text-xs mt-1 text-rose-800">
                      This draft failed grounding/safety verification (<code>is_safe_to_display=false</code>).
                      Unverified numeric, causal, or prescriptive claims are never displayed to patients or clinicians.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Patient Summary
                    </div>
                    <p className="text-sm leading-relaxed text-slate-800">{run.primary_summary_patient}</p>
                  </div>

                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Clinician Summary
                    </div>
                    <p className="text-sm leading-relaxed text-slate-800">{run.primary_summary_clinician}</p>
                  </div>

                  {run.doctor_report.clinician_questions.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Questions for Clinician Discussion
                      </div>
                      <ul className="list-disc pl-5 text-sm text-slate-700 space-y-1">
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

          {/* Agent Observations & Evidence Grounding */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Specialist Agent Observations</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {run.observations.map((obs, idx) => (
                  <div key={idx} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-900">
                        {obs.agent_name} ({obs.observation_type})
                      </span>
                      <Badge variant="neutral">conf: {obs.confidence.toFixed(2)}</Badge>
                    </div>
                    <p className="text-slate-700">{obs.finding_summary}</p>
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
                  <div key={ev.evidence_id} className="rounded-xl border border-slate-200 p-3 text-xs space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900">{ev.metric_name}</span>
                      <span className="font-mono text-slate-700">
                        {ev.value !== null ? `${ev.value} ${ev.unit ?? ""}` : "null"}
                      </span>
                    </div>
                    <div className="text-slate-500 font-mono truncate">
                      checksum: {ev.source_record_set_checksum}
                    </div>
                    <div className="text-slate-500">
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
      <AppShell>
        <InvestigationDetailContent />
      </AppShell>
    </Suspense>
  );
}
