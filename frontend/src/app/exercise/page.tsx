"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Dumbbell, Footprints, ShieldCheck } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";

interface ExerciseCard {
  weekly_minutes: number;
  target_minutes: number;
  resistance_sessions: number;
  target_resistance: number;
  active_days: number;
  safety_note: string;
  weekly_plan: { day: string; title: string; kind: string; minutes: number }[];
  recent_logs: { id: string; activity_type: string; duration_min: number; intensity: string; logged_at: string }[];
}

export default function ExercisePage() {
  const { activePatientId } = usePatientContext();
  const [card, setCard] = useState<ExerciseCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!activePatientId) return;
    const res = await apiClient.getExercisePlan(activePatientId);
    const found = (res.mover?.cards ?? [])[0] as unknown as ExerciseCard | undefined;
    if (found) setCard(found);
  }, [activePatientId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function quickLog(activity_type: string, duration_min: number, intensity: "low" | "moderate" | "vigorous") {
    if (!activePatientId) return;
    setBusy(true);
    try {
      await apiClient.logExercise(activePatientId, { activity_type, duration_min, intensity });
      setToast(`Logged ${duration_min} min ${activity_type}.`);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const pct = card ? Math.min(100, Math.round((card.weekly_minutes / card.target_minutes) * 100)) : 0;

  return (
    <div className="space-y-6">
      <Link href="/more" className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF4D4D]">
        <ArrowLeft className="h-4 w-4" /> Back to Care Tools
      </Link>

      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold">Exercise Routine (Mover)</h1>
        <p className="text-sm text-[var(--text-muted)]">
          ADA 2025 weekly movement plan: 150 min/week aerobic activity, 2+ strength sessions, and 15-min post-meal walks.
        </p>
      </div>

      {toast && <div className="rounded-xl bg-[#F2A93B]/20 px-4 py-2 text-xs font-semibold">{toast}</div>}

      {card && (
        <>
          {/* Weekly Goal Progress Card */}
          <section className="gc-card p-6 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-xs text-[var(--text-muted)]">This Week&apos;s Progress</div>
                <div className="text-3xl font-bold tabular-nums mt-1">
                  {card.weekly_minutes} / {card.target_minutes}{" "}
                  <span className="text-sm font-normal text-[var(--text-muted)]">min</span>
                </div>
              </div>
              <div className="flex gap-3 text-xs">
                <span className="rounded-full bg-[var(--bg-muted)] px-3 py-1 font-semibold">
                  {card.active_days} active day(s)
                </span>
                <span className="rounded-full bg-[#F2A93B]/20 px-3 py-1 font-semibold">
                  {card.resistance_sessions} / {card.target_resistance} strength
                </span>
              </div>
            </div>

            <div className="h-3 w-full rounded-full bg-[var(--bg-muted)] overflow-hidden">
              <div style={{ width: `${pct}%` }} className="h-full bg-[#FF4D4D] transition-all" />
            </div>

            <div className="flex items-start gap-2 rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3 text-xs">
              <ShieldCheck className="h-4 w-4 text-[#F2A93B] shrink-0 mt-0.5" />
              <span>{card.safety_note}</span>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void quickLog("post_meal_walk", 15, "low")}
                className="inline-flex items-center gap-1.5 rounded-[12px] bg-[#FF4D4D] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#e84141]"
              >
                <Footprints className="h-3.5 w-3.5" /> +15 min Post-Meal Walk
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void quickLog("brisk_walk", 30, "moderate")}
                className="inline-flex items-center gap-1.5 rounded-[12px] border border-[var(--border-clay)] px-3.5 py-2 text-xs font-semibold hover:bg-[var(--bg-muted)]"
              >
                <CheckCircle2 className="h-3.5 w-3.5 text-[#F2A93B]" /> +30 min Brisk Walk
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void quickLog("strength", 20, "moderate")}
                className="inline-flex items-center gap-1.5 rounded-[12px] border border-[var(--border-clay)] px-3.5 py-2 text-xs font-semibold hover:bg-[var(--bg-muted)]"
              >
                <Dumbbell className="h-3.5 w-3.5 text-[#FF4D4D]" /> +20 min Strength
              </button>
            </div>
          </section>

          {/* 7-Day Schedule */}
          <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {card.weekly_plan.map((item) => (
              <div key={item.day} className="gc-card p-4 space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-[#FF4D4D]">{item.day}</span>
                  <span className="rounded-full bg-[var(--bg-muted)] px-2 py-0.5 capitalize">{item.kind}</span>
                </div>
                <p className="text-sm font-medium">{item.title}</p>
                <div className="text-xs text-[var(--text-muted)]">{item.minutes} min target</div>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}
