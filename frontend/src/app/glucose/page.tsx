"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MessageCircleHeart, ShieldCheck, Utensils } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type {
  DailyPatternResponse,
  GlucoseReadingsResponse,
  GlucoseSummary,
} from "@/types/glycadence";

export default function GlucosePage() {
  const router = useRouter();
  const { activePatientId } = usePatientContext();
  const [days, setDays] = useState<number>(7);
  const [readings, setReadings] = useState<GlucoseReadingsResponse | null>(null);
  const [pattern, setPattern] = useState<DailyPatternResponse | null>(null);
  const [summary, setSummary] = useState<GlucoseSummary | null>(null);

  useEffect(() => {
    if (!activePatientId) return;
    let cancelled = false;
    Promise.all([
      apiClient.getGlucoseReadings(activePatientId, days),
      apiClient.getDailyPattern(activePatientId, Math.max(days, 7)),
      apiClient.getAnalyticsSummary(activePatientId),
    ]).then(([rd, pt, sm]) => {
      if (cancelled) return;
      setReadings(rd);
      setPattern(pt);
      setSummary(sm);
    });
    return () => {
      cancelled = true;
    };
  }, [activePatientId, days]);

  const series = (readings?.readings ?? []).map((r) => ({
    label: new Date(r.recorded_at).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    glucose: r.glucose_mg_dl,
  }));

  const agpSeries = (pattern?.hours ?? []).map((h) => ({
    label: h.label,
    p10: h.p10,
    p25: h.p25,
    p50: h.p50,
    p75: h.p75,
    p90: h.p90,
  }));

  const tir = summary?.tir_pct ?? 0;
  const tbr = summary?.tbr_pct ?? 0;
  const tar = summary?.tar_pct ?? 0;
  const steadiness =
    summary?.cv_pct === null || summary?.cv_pct === undefined
      ? "—"
      : summary.cv_pct < 36
      ? "Steady"
      : "Somewhat variable";

  const mealMarkers = (readings?.markers ?? []).filter((m) => m.kind === "meal" && m.meal_id);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Glucose</h1>
          <p className="text-sm text-[var(--text-muted)]">
            {readings?.source_summary ?? "Your sensor readings and daily rhythm."}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {[1, 7, 14, 30].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-semibold border transition-colors ${
                days === d
                  ? "bg-[#2B1E2F] text-white border-[#2B1E2F] dark:bg-[#F2A93B] dark:text-[#2B1E2F]"
                  : "border-[var(--border-clay)] hover:bg-[var(--bg-muted)]"
              }`}
            >
              {d === 1 ? "Today" : `${d} days`}
            </button>
          ))}
        </div>
      </div>

      {/* Main Curve Card */}
      <section className="gc-card p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg font-semibold">Sensor Curve</h2>
          <button
            type="button"
            onClick={() => router.push(`/ask?q=${encodeURIComponent("Explain my glucose pattern this week")}`)}
            className="inline-flex items-center gap-1.5 rounded-[14px] bg-[#FF4D4D] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#e84141]"
          >
            <MessageCircleHeart className="h-3.5 w-3.5" />
            Explain this week
          </button>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="glucoseMainFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FF4D4D" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#FF4D4D" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#E9DCCB" opacity={0.5} />
              <XAxis dataKey="label" stroke="#9C8E9E" fontSize={10} minTickGap={45} />
              <YAxis domain={[45, 250]} stroke="#9C8E9E" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-card)",
                  borderColor: "var(--border-clay)",
                  borderRadius: "14px",
                  fontSize: "12px",
                }}
              />
              <ReferenceArea
                y1={readings?.target_low_mg_dl ?? 70}
                y2={readings?.target_high_mg_dl ?? 180}
                fill="#F2A93B"
                fillOpacity={0.18}
              />
              <Area
                type="monotone"
                dataKey="glucose"
                stroke="#FF4D4D"
                strokeWidth={2}
                fill="url(#glucoseMainFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Meal Event Pills linked to Meal Detail */}
        {mealMarkers.length > 0 && (
          <div className="space-y-1.5 pt-2 border-t border-[var(--border-clay)]">
            <div className="text-xs font-medium text-[var(--text-muted)]">
              Meals in this window (tap any meal to inspect recipe, sugar grams &amp; personal curve):
            </div>
            <div className="flex flex-wrap gap-2">
              {mealMarkers.slice(-8).map((m) => (
                <Link
                  key={m.id}
                  href={`/meals/${m.meal_id}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-1 text-xs hover:border-[#FF4D4D]"
                >
                  <Utensils className="h-3 w-3 text-[#F2A93B]" />
                  <span className="truncate max-w-[180px]">{m.label}</span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Summary Bar + Steadiness */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="gc-card p-5 space-y-2 md:col-span-2">
          <h3 className="font-display text-base font-semibold">Time in Range Breakdown</h3>
          <div className="h-4 w-full rounded-full overflow-hidden flex bg-[var(--bg-muted)]">
            <div style={{ width: `${tbr}%` }} className="bg-[#8E2C5A]" title={`Below target: ${tbr}%`} />
            <div style={{ width: `${tir}%` }} className="bg-[#F2A93B]" title={`In target: ${tir}%`} />
            <div style={{ width: `${tar}%` }} className="bg-[#C8553D]" title={`Above target: ${tar}%`} />
          </div>
          <div className="flex flex-wrap gap-4 text-xs tabular-nums pt-1">
            <span className="font-semibold text-[#8E2C5A]">▼ Below 70: {tbr.toFixed(1)}%</span>
            <span className="font-semibold text-[#9B630B] dark:text-[#F2A93B]">● In target 70–180: {tir.toFixed(1)}%</span>
            <span className="font-semibold text-[#C8553D]">▲ Above 180: {tar.toFixed(1)}%</span>
          </div>
        </div>

        <div className="gc-card p-5 flex flex-col justify-between">
          <div>
            <div className="text-xs text-[var(--text-muted)]">Average &amp; Steadiness</div>
            <div className="text-3xl font-bold tabular-nums mt-1">
              {summary?.mean_glucose_mg_dl ? Math.round(summary.mean_glucose_mg_dl) : "—"}{" "}
              <span className="text-xs font-normal text-[var(--text-muted)]">mg/dL</span>
            </div>
          </div>
          <div className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
            <ShieldCheck className="h-4 w-4" />
            {steadiness}
          </div>
        </div>
      </section>

      {/* 24-Hour Daily Pattern (AGP) */}
      <section className="gc-card p-6 space-y-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Daily Pattern (24-Hour Overlay)</h2>
          <p className="text-xs text-[var(--text-muted)]">
            Middle line shows your typical hour-by-hour reading; shaded band shows your usual range across days.
          </p>
        </div>
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={agpSeries} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E9DCCB" opacity={0.45} />
              <XAxis dataKey="label" stroke="#9C8E9E" fontSize={10} minTickGap={20} />
              <YAxis domain={[50, 230]} stroke="#9C8E9E" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-card)",
                  borderColor: "var(--border-clay)",
                  borderRadius: "14px",
                  fontSize: "12px",
                }}
              />
              <ReferenceArea y1={70} y2={180} fill="#F2A93B" fillOpacity={0.14} />
              <Area type="monotone" dataKey="p75" stroke="none" fill="#F2A93B" fillOpacity={0.25} isAnimationActive={false} />
              <Line type="monotone" dataKey="p50" stroke="#FF4D4D" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
