"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, LogOut, ShieldAlert, Trash2 } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { InvestigationRun, MemoryFact, PatientPreferencesOut } from "@/types/glycadence";

export default function SettingsPage() {
  const { patients, activePatientId, setActivePatientId, logout } = usePatientContext();
  const [prefs, setPrefs] = useState<PatientPreferencesOut | null>(null);
  const [memories, setMemories] = useState<MemoryFact[]>([]);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [badDraftRun, setBadDraftRun] = useState<InvestigationRun | null>(null);
  const [badDraftBusy, setBadDraftBusy] = useState(false);

  const load = useCallback(async () => {
    if (!activePatientId) return;
    const [p, m] = await Promise.all([
      apiClient.getPreferences(activePatientId),
      apiClient.listMemory(activePatientId),
    ]);
    setPrefs(p);
    setMemories(m);
  }, [activePatientId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function savePrefs(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId || !prefs) return;
    const updated = await apiClient.updatePreferences(activePatientId, prefs);
    setPrefs(updated);
    setSavedMsg("Preferences updated.");
  }

  async function removeMemory(memId: string) {
    if (!activePatientId) return;
    await apiClient.deleteMemory(activePatientId, memId);
    setMemories((prev) => prev.filter((m) => m.id !== memId));
  }

  async function simulateBadDraft() {
    if (!activePatientId) return;
    setBadDraftBusy(true);
    try {
      const run = await apiClient.runInvestigation(activePatientId, { simulate_bad_draft: true });
      setBadDraftRun(run);
    } finally {
      setBadDraftBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/more" className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF4D4D]">
        <ArrowLeft className="h-4 w-4" /> Back to Care Tools
      </Link>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Preferences &amp; Memory</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Customize your targets, meals, city, and what Cadie remembers.
          </p>
        </div>

        <button
          type="button"
          onClick={logout}
          className="inline-flex items-center gap-1.5 rounded-[14px] border border-[var(--border-clay)] px-4 py-2 text-xs font-semibold hover:bg-[var(--bg-muted)]"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign Out
        </button>
      </div>

      {/* Preferences Form */}
      {prefs && (
        <form onSubmit={savePrefs} className="gc-card p-6 space-y-4">
          <h2 className="font-display text-lg font-semibold">Your Targets &amp; Profile</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Target range low (mg/dL)</span>
              <input
                type="number"
                value={prefs.target_low_mg_dl}
                onChange={(e) => setPrefs({ ...prefs, target_low_mg_dl: Number(e.target.value) })}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Target range high (mg/dL)</span>
              <input
                type="number"
                value={prefs.target_high_mg_dl}
                onChange={(e) => setPrefs({ ...prefs, target_high_mg_dl: Number(e.target.value) })}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">City (for Suhoor/Iftar times)</span>
              <input
                type="text"
                value={prefs.city}
                onChange={(e) => setPrefs({ ...prefs, city: e.target.value })}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Food budget tier</span>
              <select
                value={prefs.budget_tier}
                onChange={(e) =>
                  setPrefs({ ...prefs, budget_tier: e.target.value as "low" | "medium" | "high" })
                }
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              >
                <option value="low">Budget-friendly</option>
                <option value="medium">Moderate</option>
                <option value="high">Flexible</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Emergency contact name</span>
              <input
                type="text"
                value={prefs.emergency_contact_name ?? ""}
                onChange={(e) => setPrefs({ ...prefs, emergency_contact_name: e.target.value })}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Emergency contact phone</span>
              <input
                type="text"
                value={prefs.emergency_contact_phone ?? ""}
                onChange={(e) => setPrefs({ ...prefs, emergency_contact_phone: e.target.value })}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-6 text-sm">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={prefs.vegetarian}
                onChange={(e) => setPrefs({ ...prefs, vegetarian: e.target.checked })}
              />
              <span>Vegetarian meals only</span>
            </label>
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={prefs.gentle_mode}
                onChange={(e) => setPrefs({ ...prefs, gentle_mode: e.target.checked })}
              />
              <span>Gentle Mode (fewer prompts when feeling burnt out)</span>
            </label>
          </div>

          {savedMsg && <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">{savedMsg}</p>}

          <button
            type="submit"
            className="rounded-[14px] bg-[#FF4D4D] px-5 py-2 text-sm font-semibold text-white hover:bg-[#e84141]"
          >
            Save Preferences
          </button>
        </form>
      )}

      {/* What Cadie Remembers */}
      <section className="gc-card p-6 space-y-3">
        <h2 className="font-display text-lg font-semibold">What Cadie Remembers</h2>
        <p className="text-xs text-[var(--text-muted)]">
          Facts Cadie noticed from your conversations so you never have to repeat yourself. Remove any item anytime.
        </p>
        {memories.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">No remembered facts yet.</p>
        ) : (
          <div className="space-y-2">
            {memories.map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between gap-3 rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] px-3.5 py-2.5 text-sm"
              >
                <div>
                  <span className="font-medium">{m.fact_text}</span>
                  <span className="ml-2 text-[11px] text-[var(--text-muted)] capitalize">({m.fact_type.replace("_", " ")})</span>
                </div>
                <button
                  type="button"
                  onClick={() => void removeMemory(m.id)}
                  aria-label="Delete memory"
                  className="text-[#8E2C5A] hover:opacity-80"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Demo & Research Controls (Hidden here away from Patient Today screen) */}
      <section className="gc-card p-6 space-y-4">
        <h2 className="font-display text-lg font-semibold">Demo &amp; Research Switcher</h2>
        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
          <select
            value={activePatientId}
            onChange={(e) => setActivePatientId(e.target.value)}
            aria-label="Select demo or research subject"
            className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2 text-sm"
          >
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name} ({p.cohort_type})
              </option>
            ))}
          </select>

          <button
            type="button"
            disabled={badDraftBusy || !activePatientId}
            onClick={() => void simulateBadDraft()}
            className="inline-flex items-center gap-2 rounded-[14px] border border-[#8E2C5A] bg-[#8E2C5A]/10 px-4 py-2 text-xs font-semibold text-[#8E2C5A]"
          >
            <ShieldAlert className="h-4 w-4" />
            {badDraftBusy ? "Running Safety Gate Demo..." : "Simulate Unsafe Draft (Demo)"}
          </button>
        </div>

        {badDraftRun && (
          <div className="rounded-xl border border-[#8E2C5A]/40 bg-[#8E2C5A]/10 p-3.5 text-xs space-y-1">
            <div className="font-semibold text-[#8E2C5A]">
              Safety Check result: {badDraftRun.verifier_report.verification_status.toUpperCase()} (display suppressed:{" "}
              {String(!badDraftRun.doctor_report?.is_safe_to_display)})
            </div>
            <div>Blocked reasons: {badDraftRun.verifier_report.failed_reasons.join(", ")}</div>
          </div>
        )}
      </section>
    </div>
  );
}
