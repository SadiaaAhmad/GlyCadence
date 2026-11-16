"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, CheckCircle2, Clock, MessageCircleHeart, Pill } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { MedicinesSummaryResponse } from "@/types/glycadence";

export default function MedicinesPage() {
  const router = useRouter();
  const { activePatientId } = usePatientContext();
  const [data, setData] = useState<MedicinesSummaryResponse | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!activePatientId) return;
    const res = await apiClient.getMedicinesSummary(activePatientId);
    setData(res);
  }, [activePatientId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function logDose(medId: string, status: "taken" | "delayed" | "skipped") {
    if (!activePatientId) return;
    setBusyId(medId);
    try {
      await apiClient.logMedicine(activePatientId, medId, status);
      setToast(`Marked as ${status}.`);
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/more" className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF4D4D]">
        <ArrowLeft className="h-4 w-4" /> Back to Care Tools
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Medicines (Dose Diary)</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Track your daily schedule, understand each medicine, and keep an eye on refills. GlyCadence never adjusts doses.
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push(`/ask?q=${encodeURIComponent("Review my diabetes medicines with my recent glucose patterns")}`)}
          className="inline-flex items-center gap-1.5 rounded-[14px] bg-[#FF4D4D] px-4 py-2 text-xs font-semibold text-white hover:bg-[#e84141]"
        >
          <MessageCircleHeart className="h-3.5 w-3.5" /> Ask Cadie about medicines
        </button>
      </div>

      {toast && (
        <div className="rounded-xl bg-[#F2A93B]/20 px-4 py-2 text-xs font-semibold">
          {toast}
        </div>
      )}

      {(data?.glucose_context ?? []).length > 0 && (
        <section className="gc-card p-4 space-y-1.5 border-[#F2A93B]/50">
          <div className="text-xs font-semibold text-[#9B630B] dark:text-[#F2A93B]">
            Dose Diary · Connected to Your Glucose Readings
          </div>
          {data?.glucose_context?.map((line, i) => (
            <p key={i} className="text-xs text-[var(--text-muted)]">
              • {line}
            </p>
          ))}
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(data?.medications ?? []).map((m) => (
          <div key={m.id} className="gc-card p-5 space-y-3 flex flex-col justify-between">
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <Pill className="h-4 w-4 text-[#FF4D4D]" />
                    <h2 className="font-display text-lg font-semibold">
                      {m.name} {m.dose}
                    </h2>
                  </div>
                  <div className="text-xs text-[var(--text-muted)] mt-0.5">
                    {m.schedule ?? "As prescribed"} · {m.drug_class ?? "Diabetes medicine"}
                  </div>
                </div>
                {m.days_left !== null && (
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                      m.days_left <= 7
                        ? "bg-[#C8553D]/15 text-[#C8553D]"
                        : "bg-[var(--bg-muted)] text-[var(--text-muted)]"
                    }`}
                  >
                    ~{m.days_left} days left
                  </span>
                )}
              </div>

              <p className="text-sm text-[var(--text-muted)] leading-relaxed">{m.plain_explanation}</p>

              {m.hypo_risk && (
                <div className="flex items-start gap-2 rounded-xl bg-[#8E2C5A]/10 border border-[#8E2C5A]/30 p-2.5 text-xs text-[#8E2C5A]">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>
                    Low-sugar caution: this medicine can lower sugar further if a meal is delayed. Carry fast sugar.
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-2 pt-2 border-t border-[var(--border-clay)]">
              <button
                type="button"
                disabled={busyId === m.id}
                onClick={() => void logDose(m.id, "taken")}
                className="inline-flex items-center gap-1 rounded-[12px] bg-[#FF4D4D] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#e84141] disabled:opacity-60"
              >
                <CheckCircle2 className="h-3.5 w-3.5" /> Taken
              </button>
              <button
                type="button"
                disabled={busyId === m.id}
                onClick={() => void logDose(m.id, "delayed")}
                className="inline-flex items-center gap-1 rounded-[12px] border border-[var(--border-clay)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--bg-muted)]"
              >
                <Clock className="h-3.5 w-3.5" /> Delayed
              </button>
              <button
                type="button"
                disabled={busyId === m.id}
                onClick={() => void logDose(m.id, "skipped")}
                className="rounded-[12px] border border-[var(--border-clay)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--bg-muted)]"
              >
                Skipped
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Diary Logs */}
      <section className="gc-card p-5 space-y-3">
        <h3 className="font-display text-base font-semibold">Recent Dose Diary Entries</h3>
        <div className="space-y-2 text-xs">
          {(data?.recent_events ?? []).map((ev) => (
            <div key={ev.id} className="flex items-center justify-between rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] px-3.5 py-2">
              <span>{new Date(ev.event_time).toLocaleString()}</span>
              <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-0.5 font-semibold capitalize">
                {ev.status}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
