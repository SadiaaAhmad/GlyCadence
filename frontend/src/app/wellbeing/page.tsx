"use client";

import React, { useCallback, useEffect, useState } from "react";
import { HeartHandshake, MessageCircleHeart, Send, ShieldAlert } from "lucide-react";
import { BackToMoreButton } from "@/components/ui/BackToMoreButton";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { WellbeingSummaryResponse } from "@/types/glycadence";

export default function WellbeingPage() {
  const { activePatientId } = usePatientContext();
  const [data, setData] = useState<WellbeingSummaryResponse | null>(null);

  const [stress, setStress] = useState(2);
  const [fatigue, setFatigue] = useState(2);
  const [sleepHours, setSleepHours] = useState(7.0);
  const [sleepQuality, setSleepQuality] = useState(4);
  const [unwell, setUnwell] = useState(false);
  const [notes, setNotes] = useState("");
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const [ddsQ1, setDdsQ1] = useState(2);
  const [ddsQ2, setDdsQ2] = useState(2);
  const [ddsResult, setDdsResult] = useState<{ average_score: number; elevated_distress: boolean; message: string } | null>(null);

  const [chatMsg, setChatMsg] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "kindred"; text: string; flagged?: boolean }[]>([]);

  const load = useCallback(async () => {
    if (!activePatientId) return;
    const res = await apiClient.getWellbeingSummary(activePatientId);
    setData(res);
  }, [activePatientId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveCheckin(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId) return;
    await apiClient.createCheckin(activePatientId, {
      stress_score: stress,
      fatigue_score: fatigue,
      sleep_hours: sleepHours,
      sleep_quality: sleepQuality,
      illness_flag: unwell,
      mood_notes: notes.trim() || undefined,
    });
    setNotes("");
    setSavedMsg("Check-in saved. Kindred updated your mood & sleep patterns.");
    await load();
  }

  async function runDds2() {
    if (!activePatientId) return;
    const res = await apiClient.scoreDDS2(activePatientId, {
      feeling_overwhelmed_1_to_6: ddsQ1,
      failing_routine_1_to_6: ddsQ2,
    });
    setDdsResult(res);
  }

  async function sendToKindred(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId || !chatMsg.trim()) return;
    const text = chatMsg.trim();
    setChatMsg("");
    setChatHistory((prev) => [...prev, { role: "user", text }]);
    setChatBusy(true);
    try {
      const res = await apiClient.talkToKindred(activePatientId, text);
      setChatHistory((prev) => [...prev, { role: "kindred", text: res.reply, flagged: res.flagged_for_doctor }]);
      await load();
    } finally {
      setChatBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <BackToMoreButton />
      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold">Wellbeing (Kindred)</h1>
        <p className="text-sm text-[var(--text-muted)]">
          20-second mood, stress, sleep, and sick-day check-ins plus live Kindred support — saved for your doctor visit.
        </p>
      </div>

      {/* Live Talk to Kindred Chat */}
      <section className="gc-card p-5 space-y-3 border-[#FF4D4D]/35">
        <div className="flex items-center gap-2 font-display text-base font-semibold">
          <MessageCircleHeart className="h-5 w-5 text-[#FF4D4D]" />
          Talk to Kindred (Mental &amp; Physical Wellbeing Companion)
        </div>
        <p className="text-xs text-[var(--text-muted)]">
          Share how you&apos;re feeling physically or emotionally (e.g., diabetes burnout, stress, foot tingling, blurry vision, poor sleep). Kindred saves notes to your personal history and Doctor Visit Report.
        </p>
        {chatHistory.length > 0 && (
          <div className="space-y-2.5 max-h-72 overflow-y-auto rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3.5">
            {chatHistory.map((m, idx) => (
              <div
                key={idx}
                className={`rounded-xl px-3.5 py-2.5 text-sm ${
                  m.role === "user"
                    ? "ml-auto max-w-[85%] bg-[#FF4D4D] text-white"
                    : "mr-auto max-w-[90%] bg-[var(--bg-muted)] text-[var(--text-main)] border border-[var(--border-clay)]"
                }`}
              >
                <p className="whitespace-pre-line">{m.text}</p>
                {m.flagged && (
                  <p className="mt-1.5 text-[11px] font-semibold text-[#C8553D]">
                    • Noted &amp; flagged for your Doctor Visit Report
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        <form onSubmit={(e) => void sendToKindred(e)} className="flex gap-2">
          <input
            value={chatMsg}
            onChange={(e) => setChatMsg(e.target.value)}
            placeholder="Tell Kindred how you're feeling today..."
            className="flex-1 rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={chatBusy || !chatMsg.trim()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#FF4D4D] px-4 py-2 text-xs font-semibold text-white hover:bg-[#e84141] disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" /> {chatBusy ? "Listening…" : "Share"}
          </button>
        </form>
      </section>

      {/* Co-occurrence Findings */}
      {(data?.agent_summary?.findings ?? []).length > 0 && (
        <section className="gc-card p-5 space-y-2">
          <div className="flex items-center gap-2 font-display text-base font-semibold">
            <HeartHandshake className="h-4 w-4 text-[#FF4D4D]" />
            Kindred Insights
          </div>
          {data?.agent_summary.findings.map((f) => (
            <p key={f.id} className="text-sm text-[var(--text-muted)]">
              {f.rendered_text}
            </p>
          ))}
        </section>
      )}

      {/* Adaptive Physical & Mental Check-In Questions from Kindred */}
      {(data?.adaptive_questions ?? []).length > 0 && (
        <section className="gc-card p-5 space-y-3 border-[#FF4D4D]/30">
          <div className="font-display text-base font-semibold">
            Kindred&apos;s Questions Based on Your Recent Readings
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data?.adaptive_questions?.map((aq) => (
              <div key={aq.id} className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3.5 text-xs space-y-1.5">
                <span className="font-semibold text-[#FF4D4D]">{aq.category}</span>
                <p className="text-sm font-medium">{aq.question}</p>
                <p className="text-[var(--text-muted)]">{aq.reason}</p>
                <button
                  type="button"
                  onClick={() => setNotes((prev) => `${prev ? prev + "; " : ""}${aq.category}: noticed recently`)}
                  className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-[11px] font-semibold hover:opacity-80"
                >
                  + Add to today&apos;s note for doctor
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* 20-Second Check-in Form */}
        <form onSubmit={saveCheckin} className="gc-card p-6 space-y-4">
          <h2 className="font-display text-lg font-semibold">20-Second Check-in</h2>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Stress (1 calm – 5 high)</span>
              <input
                type="number"
                min={1}
                max={5}
                value={stress}
                onChange={(e) => setStress(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Energy fatigue (1 fresh – 5 tired)</span>
              <input
                type="number"
                min={1}
                max={5}
                value={fatigue}
                onChange={(e) => setFatigue(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Sleep hours</span>
              <input
                type="number"
                step={0.5}
                min={0}
                max={24}
                value={sleepHours}
                onChange={(e) => setSleepHours(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-[var(--text-muted)]">Sleep quality (1–5)</span>
              <input
                type="number"
                min={1}
                max={5}
                value={sleepQuality}
                onChange={(e) => setSleepQuality(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2"
              />
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={unwell} onChange={(e) => setUnwell(e.target.checked)} />
            <span>Feeling unwell today (fever, flu, stomach upset)?</span>
          </label>

          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional short note (e.g., busy day, walked 15 min)..."
            className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2 text-sm"
          />

          {savedMsg && <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">{savedMsg}</p>}

          <button
            type="submit"
            className="w-full rounded-[14px] bg-[#FF4D4D] py-2.5 text-sm font-semibold text-white hover:bg-[#e84141]"
          >
            Save Check-in
          </button>
        </form>

        {/* DDS-2 Distress Screener & Sick-Day Card */}
        <div className="space-y-5">
          <section className="gc-card p-6 space-y-3">
            <h2 className="font-display text-lg font-semibold">Diabetes Distress Check (DDS-2)</h2>
            <p className="text-xs text-[var(--text-muted)]">
              Over the last 2 weeks (1 = not a problem, 6 = very serious problem):
            </p>
            <label className="block text-xs space-y-1">
              <span>1. Feeling overwhelmed by the demands of living with diabetes</span>
              <input
                type="range"
                min={1}
                max={6}
                value={ddsQ1}
                onChange={(e) => setDdsQ1(Number(e.target.value))}
                className="w-full"
              />
              <span className="font-semibold">Score: {ddsQ1} / 6</span>
            </label>
            <label className="block text-xs space-y-1">
              <span>2. Feeling that I am often failing with my diabetes routine</span>
              <input
                type="range"
                min={1}
                max={6}
                value={ddsQ2}
                onChange={(e) => setDdsQ2(Number(e.target.value))}
                className="w-full"
              />
              <span className="font-semibold">Score: {ddsQ2} / 6</span>
            </label>
            <button
              type="button"
              onClick={() => void runDds2()}
              className="rounded-[14px] bg-[#2B1E2F] text-white dark:bg-[#F2A93B] dark:text-[#2B1E2F] px-4 py-2 text-xs font-semibold"
            >
              Check Distress Score
            </button>
            {ddsResult && (
              <div className="rounded-xl bg-[var(--bg-muted)] p-3 text-xs space-y-1">
                <div className="font-semibold">Average score: {ddsResult.average_score} / 6</div>
                <p>{ddsResult.message}</p>
              </div>
            )}
          </section>

          <section className="gc-card p-5 space-y-2 border-[#C8553D]/40">
            <div className="flex items-center gap-2 font-display text-base font-semibold text-[#C8553D]">
              <ShieldAlert className="h-4 w-4" />
              Sick-Day Helper Rules
            </div>
            <ul className="list-disc pl-5 text-xs space-y-1 text-[var(--text-muted)]">
              <li>Sip water or sugar-free fluids every hour.</li>
              <li>Check glucose every 3–4 hours when unwell.</li>
              <li>Do not stop basal insulin or tablets without medical advice.</li>
              <li>Call a clinician urgently if unable to keep fluids down or persistent &gt;250 mg/dL.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
