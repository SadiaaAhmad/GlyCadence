import React from "react";
import Link from "next/link";
import { ArrowRight, BrainCircuit, Layers, ShieldCheck, Sparkles } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SystemStatusCard } from "@/components/dashboard/SystemStatusCard";
import { SampleGlucosePreview } from "@/components/charts/SampleGlucosePreview";

export default function OverviewPage() {
  return (
    <div className="space-y-8">
      {/* Apple-style Hero */}
      <section className="rounded-3xl border border-slate-200/80 bg-gradient-to-br from-white via-slate-50/70 to-[#FFF1F1]/40 p-8 sm:p-10 shadow-sm dark:border-slate-800 dark:from-slate-900 dark:via-slate-900 dark:to-rose-950/20">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#FF4D4D]/25 bg-[#FFF1F1] px-3.5 py-1 text-xs font-semibold text-[#FF4D4D] dark:bg-rose-950/60">
              <Sparkles className="h-3.5 w-3.5" />
              Evidence-Grounded Longitudinal Companion
            </div>
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 dark:text-white leading-tight">
              <span className="text-[#0F4C5C] dark:text-teal-300">Gly</span>
              <span className="text-[#FF4D4D]">Cadence</span> — Clarity for every glucose, meal, and wellbeing signal.
            </h1>
            <p className="text-base text-slate-600 dark:text-slate-300 leading-relaxed">
              Deterministic analytics compute every metric with strict provenance tracking. Our LangGraph multi-agent pipeline and safety verifier ensure every clinician-ready summary is grounded, non-causal, and transparent.
            </p>
            <div className="flex flex-wrap gap-3 pt-1">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-2xl bg-[#0F4C5C] px-5 py-3 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0c3d4a] hover:shadow-md"
              >
                <BrainCircuit className="h-4 w-4" />
                Open Intelligence Dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/architecture"
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-800 shadow-xs transition-all hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
              >
                <Layers className="h-4 w-4 text-[#FF4D4D]" />
                View 4-Layer Architecture
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:min-w-[280px]">
            <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 dark:border-slate-800 dark:bg-slate-900/90">
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Safety Gate</div>
              <div className="mt-1 flex items-center gap-1.5 text-sm font-bold text-emerald-700 dark:text-emerald-400">
                <ShieldCheck className="h-4 w-4" />
                Verifier Active
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 dark:border-slate-800 dark:bg-slate-900/90">
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Agent Graph</div>
              <div className="mt-1 text-sm font-bold text-slate-900 dark:text-white">6 Specialists</div>
            </div>
            <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 dark:border-slate-800 dark:bg-slate-900/90">
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Cohorts</div>
              <div className="mt-1 text-sm font-bold text-slate-900 dark:text-white">Isolated DB</div>
            </div>
            <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 dark:border-slate-800 dark:bg-slate-900/90">
              <div className="text-xs font-medium text-slate-500 dark:text-slate-400">Provenance</div>
              <div className="mt-1 text-sm font-bold text-[#FF4D4D]">SHA-256</div>
            </div>
          </div>
        </div>
      </section>

      <SystemStatusCard />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Glucose Rhythm Preview</CardTitle>
              <Badge variant="neutral">70–180 mg/dL Target</Badge>
            </div>
            <CardDescription>
              Interactive CGM &amp; meal-response analytics powered by deterministic backend calculations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SampleGlucosePreview />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Design Principles</CardTitle>
            <CardDescription>
              Built for clinical safety, transparency, and patient empathy.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
            <div className="rounded-2xl bg-slate-50/90 p-3.5 border border-slate-200/70 dark:bg-slate-800/60 dark:border-slate-700/70">
              <div className="font-semibold text-slate-900 dark:text-white mb-0.5">Code Computes, LLM Synthesizes</div>
              TIR, TBR, TAR, CV, and meal iAUC are computed deterministically before any LLM runs.
            </div>
            <div className="rounded-2xl bg-[#FFF1F1]/70 p-3.5 border border-[#FF4D4D]/20 text-slate-700 dark:bg-rose-950/30 dark:border-rose-900/50 dark:text-slate-200">
              <div className="font-semibold text-[#FF4D4D] mb-0.5">Neutral &amp; Non-Causal</div>
              Meal and wellbeing insights report co-occurrence only — never judgmental or prescriptive.
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
