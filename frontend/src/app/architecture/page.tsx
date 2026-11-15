import React from "react";
import Link from "next/link";
import { ArrowDown, ArrowRight, Bot, Cpu, Database, Layers, ShieldCheck, Sparkles } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function ArchitecturePage() {
  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Badge variant="coral" className="mb-2">CS325 Multi-Agent Architecture</Badge>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            4-Layer Evidence-Grounded Pipeline
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Deterministic code computes every metric; LangGraph specialists analyze signals in parallel; Gemini synthesizes; the Verifier enforces safety.
          </p>
        </div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 rounded-2xl bg-[#0F4C5C] px-4 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-[#0c3d4a] transition-colors"
        >
          Run Live Investigation
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Layer 1 */}
      <Card className="border-slate-200/90">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5 text-[#0F4C5C] dark:text-teal-300" />
              Layer 1 — Supervisor &amp; Data Quality Gate
            </CardTitle>
            <Badge variant="neutral">Deterministic</Badge>
          </div>
          <CardDescription>
            Cohort isolation (research_participant vs synthetic_demo), allowed provenance tiers, coverage &gt;= 70%, and SHA-256 EvidenceItem checksums.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-800/50">
            <div className="font-semibold text-sm text-slate-900 dark:text-white">supervisor</div>
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
              Validates cohort &amp; provenance policy and initializes per-node execution trace.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-800/50">
            <div className="font-semibold text-sm text-slate-900 dark:text-white">data_quality</div>
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
              Audits CGM sensor coverage, provenance counts (native, dataset_documented, archive_aligned), and uncertainty notes.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-center text-slate-400">
        <ArrowDown className="h-5 w-5" />
      </div>

      {/* Layer 2 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-5 w-5 text-[#FF4D4D]" />
              Layer 2 — Parallel Specialist Agents
            </CardTitle>
            <Badge variant="neutral">4 Parallel Branches</Badge>
          </div>
          <CardDescription>
            Each specialist operates strictly on pre-computed deterministic analytics and emits grounded observations.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              name: "pattern_watcher",
              desc: "TIR/TBR/TAR/CV summary + exploratory early-vs-late personal baseline drift.",
            },
            {
              name: "diet_nutrition",
              desc: "Meal iAUC responses with neutral wording only — never good/bad food labels.",
            },
            {
              name: "medication_analyst",
              desc: "Logged medication events & timing; never infers non-adherence.",
            },
            {
              name: "wellbeing_companion",
              desc: "Stress, fatigue, sleep & illness check-in counts; co-occurrence only, never causal.",
            },
          ].map((agent) => (
            <div
              key={agent.name}
              className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-800/50"
            >
              <div className="font-mono text-xs font-semibold text-[#0F4C5C] dark:text-teal-300">
                {agent.name}
              </div>
              <p className="mt-1.5 text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                {agent.desc}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex justify-center text-slate-400">
        <ArrowDown className="h-5 w-5" />
      </div>

      {/* Layer 3 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-[#FF4D4D]" />
              Layer 3 — Cross-Signal Orchestrator &amp; Appointment Preparer
            </CardTitle>
            <div className="flex gap-2">
              <Badge variant="default" className="gap-1">
                <Bot className="h-3 w-3" /> Gemini
              </Badge>
              <Badge variant="neutral" className="gap-1">
                <Cpu className="h-3 w-3" /> Fallback
              </Badge>
            </div>
          </div>
          <CardDescription>
            Correlates co-occurring signals in the same window and drafts patient/clinician summaries + 3–5 suggested questions.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-800/50">
            <div className="font-semibold text-sm text-slate-900 dark:text-white">cross_signal_orchestrator</div>
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
              Deterministic co-occurrence synthesis linking glucose drift, meal responses, and wellbeing days grounded in EvidenceItems.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-800/50">
            <div className="font-semibold text-sm text-slate-900 dark:text-white">appointment_preparer</div>
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
              Uses Gemini (or transparent deterministic template fallback) to draft summaries and 3–5 clinician discussion questions.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-center text-slate-400">
        <ArrowDown className="h-5 w-5" />
      </div>

      {/* Layer 4 */}
      <Card className="border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-emerald-900 dark:text-emerald-300">
              <ShieldCheck className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              Layer 4 — Deterministic Safety Verifier Gate (Max 1 Repair)
            </CardTitle>
            <Badge variant="default">First-Line Safety Gate</Badge>
          </div>
          <CardDescription>
            Blocks ungrounded numbers, wrong-metric cross-matches, unit/direction contradictions, causal/prescriptive overclaims, judgmental food wording, and missing dataset_documented provenance disclosures before setting is_safe_to_display=true.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
