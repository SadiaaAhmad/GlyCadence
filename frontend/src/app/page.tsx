"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Clock,
  HeartHandshake,
  MessageCircleHeart,
  MoveRight,
  Pill,
  Send,
  Utensils,
} from "lucide-react";
import {
  Area,
  AreaChart,
  ReferenceArea,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { GlucoseReadingsResponse, TodayOverview } from "@/types/glycadence";

function timeGreeting(): string {
  const hr = new Date().getHours();
  if (hr < 12) return "Good morning";
  if (hr < 17) return "Good afternoon";
  return "Good evening";
}

function zoneMeta(val: number | null | undefined, low = 70, high = 180) {
  if (val === null || val === undefined) {
    return { label: "Waiting for reading", badge: "bg-[var(--bg-muted)] text-[var(--text-muted)]", icon: "" };
  }
  if (val < low) {
    return { label: "Below target ▼", badge: "bg-[#8E2C5A]/15 text-[#8E2C5A]", icon: "▼" };
  }
  if (val > high) {
    return { label: "Above target ▲", badge: "bg-[#C8553D]/15 text-[#C8553D]", icon: "▲" };
  }
  return { label: "In target", badge: "bg-[#F2A93B]/20 text-[#9B630B] dark:text-[#F2A93B]", icon: "●" };
}

export default function TodayPage() {
  const router = useRouter();
  const { activePatientId, activePatient } = usePatientContext();
  const [overview, setOverview] = useState<TodayOverview | null>(null);
  const [readings, setReadings] = useState<GlucoseReadingsResponse | null>(null);
  const [quickQuestion, setQuickQuestion] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activePatientId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      apiClient.getTodayOverview(activePatientId),
      apiClient.getGlucoseReadings(activePatientId, 1),
    ])
      .then(([ov, rd]) => {
        if (cancelled) return;
        setOverview(ov);
        setReadings(rd);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePatientId]);

  const firstName = activePatient?.display_name?.split(" ")[0] ?? "there";
  const latestVal = overview?.hero?.latest_mg_dl ?? readings?.latest_glucose_mg_dl;
  const zm = zoneMeta(latestVal, readings?.target_low_mg_dl, readings?.target_high_mg_dl);
  const trend = overview?.hero?.trend ?? readings?.trend_arrow ?? "steady";

  const chartData = (readings?.readings ?? []).slice(-48).map((pt) => ({
    time: new Date(pt.recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    glucose: pt.glucose_mg_dl,
  }));

  function handleAskSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = quickQuestion.trim();
    if (!q) {
      router.push("/ask");
      return;
    }
    router.push(`/ask?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="space-y-6">
      {/* Greeting Header */}
      <section className="space-y-1.5">
        <h1 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight">
          {timeGreeting()}, {firstName}
        </h1>
        <p className="text-base text-[var(--text-muted)]">
          {overview?.greeting_line || (loading ? "Loading your day..." : "Your sensor, meal, and medicine patterns are ready.")}
        </p>
      </section>

      {/* Primary Card 1: Glucose Hero Card */}
      <section className="gc-card p-6 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-[var(--text-muted)]">Latest Glucose</div>
            <div className="flex items-baseline gap-3 mt-1">
              <span className="text-5xl sm:text-[56px] font-bold leading-none tabular-nums">
                {latestVal !== null && latestVal !== undefined ? Math.round(latestVal) : "—"}
              </span>
              <span className="text-sm text-[var(--text-muted)]">mg/dL</span>
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-xs font-medium capitalize">
                {trend.includes("up") ? (
                  <ArrowUpRight className="h-4 w-4 text-[#C8553D]" />
                ) : trend.includes("down") ? (
                  <ArrowDownRight className="h-4 w-4 text-[#8E2C5A]" />
                ) : (
                  <MoveRight className="h-4 w-4 text-[#F2A93B]" />
                )}
                {trend.replace("_", " ")}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${zm.badge}`}>
              {zm.label}
            </span>
            {overview?.hero?.tir_pct !== null && overview?.hero?.tir_pct !== undefined && (
              <span className="rounded-full bg-[var(--bg-muted)] px-3 py-1 text-xs font-medium tabular-nums">
                Time in target: {overview.hero.tir_pct}%
              </span>
            )}
          </div>
        </div>

        {/* Mini 24-hour curve with Saffron target band */}
        <div className="h-44 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
              <defs>
                <linearGradient id="saffronCurveFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FF4D4D" stopOpacity={0.28} />
                  <stop offset="95%" stopColor="#FF4D4D" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" stroke="#9C8E9E" fontSize={11} minTickGap={30} />
              <YAxis domain={[50, 230]} stroke="#9C8E9E" fontSize={11} />
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
                strokeWidth={2.5}
                fill="url(#saffronCurveFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
          <span>Shaded saffron band: 70–180 mg/dL target range</span>
          <Link href="/glucose" className="font-semibold text-[#FF4D4D] inline-flex items-center gap-1 hover:underline">
            Full glucose curve <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </section>

      {/* Primary Card 2: Next Up Horizontal Timeline */}
      <section className="space-y-3">
        <h2 className="font-display text-lg font-semibold">Next up today</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {(overview?.next_up ?? []).map((item) => {
            const Icon =
              item.slot.includes("Meal")
                ? Utensils
                : item.slot.includes("Medicine")
                ? Pill
                : HeartHandshake;
            const href = item.slot.includes("Meal")
              ? item.recipe_id
                ? `/meals/${item.recipe_id}`
                : "/meals"
              : item.slot.includes("Medicine")
              ? "/medicines"
              : "/wellbeing";

            return (
              <Link key={item.slot} href={href} className="gc-card p-4 hover:border-[#FF4D4D]/50 transition-colors">
                <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
                  <span className="font-semibold uppercase tracking-wide">{item.slot}</span>
                  <Icon className="h-4 w-4 text-[#FF4D4D]" />
                </div>
                <div className="mt-2 font-semibold text-sm line-clamp-1">{item.title}</div>
                <div className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--text-muted)]">
                  <Clock className="h-3.5 w-3.5" />
                  {item.window}
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Primary Card 3: One Featured Suggestion */}
      {overview?.featured_recipe && (
        <section className="gc-card p-5 flex flex-col sm:flex-row gap-5 items-center">
          <img
            src={overview.featured_recipe.image_url}
            alt={overview.featured_recipe.name}
            className="h-28 w-full sm:w-40 rounded-2xl object-cover shrink-0 bg-[var(--bg-muted)]"
          />
          <div className="flex-1 space-y-2">
            <div className="inline-flex items-center rounded-full bg-[#F2A93B]/20 px-2.5 py-0.5 text-xs font-semibold text-[#9B630B] dark:text-[#F2A93B]">
              Gentle meal idea · {overview.featured_recipe.slot}
            </div>
            <h3 className="font-display text-lg font-semibold">{overview.featured_recipe.name}</h3>
            <p className="text-sm text-[var(--text-muted)]">{overview.featured_suggestion}</p>
            <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
              <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1">
                {overview.featured_recipe.carbs_g}g carbs · {overview.featured_recipe.sugar_g}g sugar
              </span>
              <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1">
                {overview.featured_recipe.fibre_g}g fibre
              </span>
              <Link
                href={`/meals/${overview.featured_recipe.recipe_id}`}
                className="ml-auto font-semibold text-[#FF4D4D] inline-flex items-center gap-1 hover:underline"
              >
                Recipe &amp; your response <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </section>
      )}

      {/* Ask Cadie Quick Bar */}
      <form onSubmit={handleAskSubmit} className="gc-card p-3 flex items-center gap-2.5">
        <MessageCircleHeart className="h-5 w-5 text-[#FF4D4D] ml-2 shrink-0" />
        <input
          type="text"
          value={quickQuestion}
          onChange={(e) => setQuickQuestion(e.target.value)}
          placeholder="Ask Cadie about meals, low sugar, medicines, or Ramadan..."
          className="flex-1 bg-transparent text-sm focus:outline-none placeholder:text-[var(--text-muted)]"
        />
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 rounded-[14px] bg-[#FF4D4D] px-4 py-2 text-sm font-semibold text-white hover:bg-[#e84141]"
        >
          Ask <Send className="h-3.5 w-3.5" />
        </button>
      </form>
    </div>
  );
}
