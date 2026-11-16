"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, Clock, MessageCircleHeart, Pill, Plus, ShieldAlert } from "lucide-react";
import { BackToMoreButton } from "@/components/ui/BackToMoreButton";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { MedicinesSummaryResponse } from "@/types/glycadence";

export default function MedicinesPage() {
  const router = useRouter();
  const { activePatientId } = usePatientContext();
  const [data, setData] = useState<MedicinesSummaryResponse | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [medName, setMedName] = useState("");
  const [drugClass, setDrugClass] = useState("Biguanide");
  const [dose, setDose] = useState("500 mg");
  const [schedule, setSchedule] = useState("With dinner");
  const [units, setUnits] = useState(30);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    if (!activePatientId) return;
    const res = await apiClient.getMedicinesSummary(activePatientId);
    setData(res);
  }, [activePatientId]);

  useEffect(() => {
    void load();
  }, [load]);

  const latestStatusByMed = useMemo(() => {
    const map: Record<string, string> = {};
    for (const ev of data?.recent_events ?? []) {
      if (ev.medication_id && !map[ev.medication_id]) {
        map[ev.medication_id] = ev.status;
      }
    }
    return map;
  }, [data?.recent_events]);

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

  async function handleAddMedicine(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId || !medName.trim()) return;
    setAdding(true);
    try {
      await apiClient.addMedicine(activePatientId, {
        medication_name: medName.trim(),
        drug_class: drugClass,
        recorded_dose: dose.trim() || "As prescribed",
        prescribed_schedule: schedule.trim() || "Daily",
        units_on_hand: Number(units) || 30,
      });
      setMedName("");
      setShowAdd(false);
      setToast("Added medicine to your personal Dose Diary.");
      await load();
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="space-y-6">
      <BackToMoreButton />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Medicines (Dose Diary)</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Track your daily schedule, add your own medicines, and review sugar-linked clinician discussion points.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setShowAdd((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-[14px] border border-[var(--border-clay)] bg-[var(--bg-card)] px-4 py-2 text-xs font-semibold text-[var(--text-main)] hover:border-[#FF4D4D]"
          >
            <Plus className="h-3.5 w-3.5" /> Add Medicine
          </button>
          <button
            type="button"
            onClick={() => router.push(`/ask?q=${encodeURIComponent("Review my diabetes medicines with my recent glucose patterns")}`)}
            className="inline-flex items-center gap-1.5 rounded-[14px] bg-[#FF4D4D] px-4 py-2 text-xs font-semibold text-white hover:bg-[#e84141]"
          >
            <MessageCircleHeart className="h-3.5 w-3.5" /> Ask Cadie about medicines
          </button>
        </div>
      </div>

      {toast && (
        <div className="rounded-xl bg-[#239B62]/15 border border-[#239B62]/30 px-4 py-2 text-xs font-semibold text-[#1D8353]">
          {toast}
        </div>
      )}

      {showAdd && (
        <form onSubmit={(e) => void handleAddMedicine(e)} className="gc-card p-5 space-y-4 border-[#FF4D4D]/40">
          <h2 className="font-display text-base font-semibold">Add Your Prescribed Medicine</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <input
              required
              value={medName}
              onChange={(e) => setMedName(e.target.value)}
              placeholder="Medicine name (e.g. Metformin)"
              className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
            <select
              value={drugClass}
              onChange={(e) => setDrugClass(e.target.value)}
              className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            >
              <option value="Biguanide">Biguanide (Metformin)</option>
              <option value="Sulfonylurea">Sulfonylurea (Gliclazide/Glimepiride)</option>
              <option value="Basal Insulin">Basal Insulin</option>
              <option value="SGLT2i">SGLT2 Inhibitor</option>
              <option value="DPP4i">DPP-4 Inhibitor</option>
              <option value="Other">Other</option>
            </select>
            <input
              required
              value={dose}
              onChange={(e) => setDose(e.target.value)}
              placeholder="Dose (e.g. 500 mg)"
              className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
            <input
              required
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="Schedule (e.g. With dinner)"
              className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
            <input
              type="number"
              min={0}
              max={500}
              value={units}
              onChange={(e) => setUnits(Number(e.target.value))}
              placeholder="Units left"
              className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="rounded-full border border-[var(--border-clay)] px-4 py-1.5 text-xs font-semibold"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={adding}
              className="rounded-full bg-[#FF4D4D] px-5 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              {adding ? "Saving…" : "Save Medicine"}
            </button>
          </div>
        </form>
      )}

      {/* Dose Diary Agent Sugar-Linked Clinician Discussion Recommendations */}
      {(data?.agent_recommendations ?? []).length > 0 && (
        <section className="gc-card p-5 space-y-3 border-[#F2A93B]/50">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-base font-semibold text-[#9B630B] dark:text-[#F2A93B]">
              Dose Diary Agent · Personalized Medicine & Sugar Insights
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data?.agent_recommendations?.map((rec, idx) => (
              <div key={idx} className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] p-3.5 space-y-1.5">
                <div className="text-sm font-bold text-[var(--text-main)]">{rec.title}</div>
                <div className="text-xs font-semibold text-[#FF6B6B]">Option to discuss: {rec.option_class}</div>
                <p className="text-xs text-[var(--text-muted)] leading-relaxed">{rec.why}</p>
              </div>
            ))}
          </div>
          <div className="flex items-start gap-2 rounded-xl bg-[#FF4D4D]/12 border border-[#FF4D4D]/35 p-3 text-xs font-semibold text-[#C93B3B] dark:text-[#FF8A8A]">
            <ShieldAlert className="h-4 w-4 shrink-0 mt-0.5" />
            <span>
              {data?.safety_disclaimer ??
                "Discuss with and get a prescription from your doctor before starting or changing any medicine."}
            </span>
          </div>
        </section>
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

      {(data?.medications ?? []).length === 0 ? (
        <div className="gc-card p-6 text-center space-y-2">
          <p className="text-sm font-semibold">No medicines added yet.</p>
          <p className="text-xs text-[var(--text-muted)]">
            Click “Add Medicine” above to log your prescriptions and track daily doses.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(data?.medications ?? []).map((m) => {
            const activeStatus = latestStatusByMed[m.id] ?? "";
            return (
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
                    className={`inline-flex items-center gap-1 rounded-[12px] px-3 py-1.5 text-xs font-semibold transition disabled:opacity-60 ${
                      activeStatus === "taken"
                        ? "bg-[#239B62] text-white shadow-sm"
                        : "border border-[var(--border-clay)] bg-[var(--bg-page)] text-[var(--text-main)] hover:bg-[var(--bg-muted)]"
                    }`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" /> Taken
                  </button>
                  <button
                    type="button"
                    disabled={busyId === m.id}
                    onClick={() => void logDose(m.id, "delayed")}
                    className={`inline-flex items-center gap-1 rounded-[12px] px-3 py-1.5 text-xs font-semibold transition disabled:opacity-60 ${
                      activeStatus === "delayed"
                        ? "bg-[#F2A93B] text-white shadow-sm"
                        : "border border-[var(--border-clay)] bg-[var(--bg-page)] text-[var(--text-main)] hover:bg-[var(--bg-muted)]"
                    }`}
                  >
                    <Clock className="h-3.5 w-3.5" /> Delayed
                  </button>
                  <button
                    type="button"
                    disabled={busyId === m.id}
                    onClick={() => void logDose(m.id, "skipped")}
                    className={`rounded-[12px] px-3 py-1.5 text-xs font-semibold transition disabled:opacity-60 ${
                      activeStatus === "skipped"
                        ? "bg-[#8E2C5A] text-white shadow-sm"
                        : "border border-[var(--border-clay)] bg-[var(--bg-page)] text-[var(--text-main)] hover:bg-[var(--bg-muted)]"
                    }`}
                  >
                    Skipped
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Recent Diary Logs */}
      <section className="gc-card p-5 space-y-3">
        <h3 className="font-display text-base font-semibold">Recent Dose Diary Entries</h3>
        {(data?.recent_events ?? []).length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">No doses logged yet. Tap Taken, Delayed, or Skipped on a medicine above.</p>
        ) : (
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
        )}
      </section>
    </div>
  );
}
