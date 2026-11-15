import React from "react";
import Link from "next/link";
import { ArrowRight, Bot, Cpu, Database, Layers, ShieldCheck, Sparkles } from "lucide-react";
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
          className="inline-flex items-center gap-2 rounded-2xl bg-[#FF4D4D] px-5 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-[#e63e3e] transition-colors"
        >
          Run Live Investigation
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Visual SVG Pipeline Flow Diagram */}
      <Card className="overflow-hidden border-slate-200/80 dark:border-slate-700/50">
        <CardHeader>
          <CardTitle className="text-base">LangGraph Execution Topology</CardTitle>
          <CardDescription>
            Parallel fan-out from Data Quality to 4 specialist nodes, converging into Cross-Signal Orchestration and the Safety Verifier Gate.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="w-full overflow-x-auto">
            <svg
              viewBox="0 0 920 330"
              className="w-full min-w-[680px] h-auto"
              role="img"
              aria-label="GlyCadence 4-layer multi-agent pipeline diagram"
            >
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />
                </marker>
                <marker id="arrow-emerald" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
                </marker>
              </defs>

              {/* Layer 1 */}
              <rect x="20" y="120" width="165" height="90" rx="16" fill="#0F4C5C" />
              <text x="102" y="152" textAnchor="middle" fill="#ffffff" fontSize="13" fontWeight="700">1. Supervisor &amp;</text>
              <text x="102" y="170" textAnchor="middle" fill="#ffffff" fontSize="13" fontWeight="700">Data Quality</text>
              <text x="102" y="192" textAnchor="middle" fill="#cbd5e1" fontSize="10">Cohort + SHA-256</text>

              {/* Fan-out connectors */}
              <path d="M 185 165 L 245 50" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 185 165 L 245 125" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 185 165 L 245 205" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 185 165 L 245 280" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />

              {/* Layer 2: 4 Parallel Specialists */}
              <rect x="250" y="20" width="185" height="58" rx="14" fill="#1e293b" stroke="#334155" strokeWidth="1.5" />
              <text x="342" y="45" textAnchor="middle" fill="#f8fafc" fontSize="12" fontWeight="700">pattern_watcher</text>
              <text x="342" y="63" textAnchor="middle" fill="#94a3b8" fontSize="10">TIR / TBR / TAR / Drift</text>

              <rect x="250" y="96" width="185" height="58" rx="14" fill="#1e293b" stroke="#334155" strokeWidth="1.5" />
              <text x="342" y="121" textAnchor="middle" fill="#f8fafc" fontSize="12" fontWeight="700">diet_nutrition</text>
              <text x="342" y="139" textAnchor="middle" fill="#94a3b8" fontSize="10">Meal iAUC (Neutral)</text>

              <rect x="250" y="174" width="185" height="58" rx="14" fill="#1e293b" stroke="#334155" strokeWidth="1.5" />
              <text x="342" y="199" textAnchor="middle" fill="#f8fafc" fontSize="12" fontWeight="700">medication_analyst</text>
              <text x="342" y="217" textAnchor="middle" fill="#94a3b8" fontSize="10">Logged Events Only</text>

              <rect x="250" y="250" width="185" height="58" rx="14" fill="#1e293b" stroke="#334155" strokeWidth="1.5" />
              <text x="342" y="275" textAnchor="middle" fill="#f8fafc" fontSize="12" fontWeight="700">wellbeing_companion</text>
              <text x="342" y="293" textAnchor="middle" fill="#94a3b8" fontSize="10">Co-Occurrence Counts</text>

              {/* Fan-in connectors */}
              <path d="M 435 50 L 495 165" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 435 125 L 495 165" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 435 205 L 495 165" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />
              <path d="M 435 280 L 495 165" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />

              {/* Layer 3 */}
              <rect x="500" y="80" width="190" height="72" rx="14" fill="#FF4D4D" />
              <text x="595" y="110" textAnchor="middle" fill="#ffffff" fontSize="12" fontWeight="700">cross_signal_orchestrator</text>
              <text x="595" y="130" textAnchor="middle" fill="#ffe4e6" fontSize="10">Grounded Co-Occurrence</text>

              <path d="M 595 152 L 595 182" stroke="#64748b" strokeWidth="2" fill="none" markerEnd="url(#arrow)" />

              <rect x="500" y="188" width="190" height="72" rx="14" fill="#0F4C5C" />
              <text x="595" y="218" textAnchor="middle" fill="#ffffff" fontSize="12" fontWeight="700">appointment_preparer</text>
              <text x="595" y="238" textAnchor="middle" fill="#cbd5e1" fontSize="10">Gemini / Fallback + Questions</text>

              <path d="M 690 224 L 740 165" stroke="#10b981" strokeWidth="2.5" fill="none" markerEnd="url(#arrow-emerald)" />

              {/* Layer 4 */}
              <rect x="745" y="115" width="155" height="100" rx="16" fill="#065f46" stroke="#10b981" strokeWidth="2" />
              <text x="822" y="148" textAnchor="middle" fill="#ffffff" fontSize="13" fontWeight="700">4. Verifier Gate</text>
              <text x="822" y="168" textAnchor="middle" fill="#a7f3d0" fontSize="10">Max 1 Repair Loop</text>
              <text x="822" y="188" textAnchor="middle" fill="#d1fae5" fontSize="10">is_safe_to_display</text>
            </svg>
          </div>
        </CardContent>
      </Card>

      {/* Layer Cards */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="border-slate-200/80 dark:border-slate-700/50">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Database className="h-5 w-5 text-[#0F4C5C] dark:text-teal-300" />
                Layer 1 — Supervisor &amp; Data Quality
              </CardTitle>
              <Badge variant="neutral">Deterministic</Badge>
            </div>
            <CardDescription>
              Cohort isolation, allowed provenance tiers, coverage &gt;= 70%, and SHA-256 EvidenceItem checksums.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-slate-200/80 dark:border-slate-700/50">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Layers className="h-5 w-5 text-[#FF4D4D]" />
                Layer 2 — 4 Parallel Specialists
              </CardTitle>
              <Badge variant="neutral">Parallel Fan-Out</Badge>
            </div>
            <CardDescription>
              pattern_watcher, diet_nutrition (neutral wording), medication_analyst, and wellbeing_companion (co-occurrence only).
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-slate-200/80 dark:border-slate-700/50">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-[#FF4D4D]" />
                Layer 3 — Orchestrator &amp; Preparer
              </CardTitle>
              <div className="flex gap-1.5">
                <Badge variant="default" className="gap-1"><Bot className="h-3 w-3" /> Gemini</Badge>
                <Badge variant="neutral" className="gap-1"><Cpu className="h-3 w-3" /> Fallback</Badge>
              </div>
            </div>
            <CardDescription>
              Links co-occurring signals and drafts patient/clinician summaries plus 3–5 suggested visit questions.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-emerald-900 dark:text-emerald-300">
                <ShieldCheck className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                Layer 4 — Safety Verifier Gate
              </CardTitle>
              <Badge variant="default">Max 1 Repair</Badge>
            </div>
            <CardDescription>
              Blocks ungrounded numbers, wrong-metric matches, unit/direction contradictions, causal/prescriptive language, and judgmental food wording.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}
