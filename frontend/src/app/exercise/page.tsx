"use client";

import React, { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Dumbbell, Flame, Pause, Play, RotateCcw, ShieldAlert, ShieldCheck, Timer } from "lucide-react";
import { BackToMoreButton } from "@/components/ui/BackToMoreButton";
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

interface WorkoutRoutine {
  id: string;
  title: string;
  activity_type: string;
  duration_min: number;
  intensity: "low" | "moderate" | "vigorous";
  subtitle: string;
  steps: { name: string; sets: number; detail: string }[];
}

const ROUTINES: WorkoutRoutine[] = [
  {
    id: "walk",
    title: "Post-Meal Brisk Walk",
    activity_type: "post_meal_walk",
    duration_min: 15,
    intensity: "moderate",
    subtitle: "Gentle glucose-lowering walk 15–30 min after eating",
    steps: [
      { name: "Easy warm-up pace", sets: 1, detail: "3 min relaxed walking" },
      { name: "Brisk steady stride", sets: 2, detail: "5 min each set, comfortable breathing" },
      { name: "Cool-down & calf stretch", sets: 1, detail: "2 min slow walk" },
    ],
  },
  {
    id: "strength",
    title: "Home Strength Circuit",
    activity_type: "strength_circuit",
    duration_min: 20,
    intensity: "moderate",
    subtitle: "Builds muscle insulin sensitivity with bodyweight moves",
    steps: [
      { name: "Chair squats or bodyweight squats", sets: 3, detail: "10–12 slow reps" },
      { name: "Wall or incline push-ups", sets: 3, detail: "8–12 controlled reps" },
      { name: "Standing marching + heel raises", sets: 2, detail: "45 sec continuous" },
    ],
  },
  {
    id: "stretch",
    title: "Gentle Mobility & Stretch",
    activity_type: "gentle_stretch",
    duration_min: 10,
    intensity: "low",
    subtitle: "Safe option when sugar is high (>=250) or energy is low",
    steps: [
      { name: "Seated shoulder & neck rolls", sets: 2, detail: "60 sec slow breathing" },
      { name: "Seated ankle circles & hamstring reach", sets: 2, detail: "60 sec each side" },
      { name: "Deep diaphragmatic breathing", sets: 1, detail: "2 min calm recovery" },
    ],
  },
];

function RingGauge({ value, max, label, sublabel, color }: { value: number; max: number; label: string; sublabel: string; color: string }) {
  const pct = Math.min(100, Math.round((value / Math.max(1, max)) * 100));
  const r = 42;
  const c = 2 * Math.PI * r;
  const dash = c - (pct / 100) * c;
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[#E9DCCB] bg-[#FBF6EF] p-4">
      <svg className="h-24 w-24 -rotate-90" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="#E9DCCB" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={dash}
        />
        <text
          x="50"
          y="54"
          textAnchor="middle"
          className="rotate-90 origin-center fill-[#2B1E2F] text-sm font-bold"
          style={{ transformBox: "fill-box" }}
        >
          {pct}%
        </text>
      </svg>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-[#7E6E64]">{label}</p>
        <p className="mt-1 text-2xl font-bold text-[#2B1E2F]">
          {value} <span className="text-sm font-medium text-[#7E6E64]">/ {max}</span>
        </p>
        <p className="mt-0.5 text-xs text-[#6B5A50]">{sublabel}</p>
      </div>
    </div>
  );
}

export default function ExercisePage() {
  const { activePatientId } = usePatientContext();
  const [card, setCard] = useState<ExerciseCard | null>(null);
  const [preSugar, setPreSugar] = useState<string>("");
  const [sugarChecked, setSugarChecked] = useState(false);

  const [selectedRoutine, setSelectedRoutine] = useState<WorkoutRoutine>(ROUTINES[0]);
  const [secondsLeft, setSecondsLeft] = useState<number>(ROUTINES[0].duration_min * 60);
  const [running, setRunning] = useState(false);
  const [restSeconds, setRestSeconds] = useState<number>(0);
  const [completedSets, setCompletedSets] = useState<Record<string, boolean>>({});
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

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      setSecondsLeft((s) => (s > 0 ? s - 1 : 0));
      setRestSeconds((r) => (r > 0 ? r - 1 : 0));
    }, 1000);
    return () => clearInterval(t);
  }, [running]);

  const sugarNum = preSugar ? Number(preSugar) : null;
  const sugarLow = sugarNum !== null && !Number.isNaN(sugarNum) && sugarNum < 100;
  const sugarHigh = sugarNum !== null && !Number.isNaN(sugarNum) && sugarNum >= 250;

  function chooseRoutine(r: WorkoutRoutine) {
    setSelectedRoutine(r);
    setSecondsLeft(r.duration_min * 60);
    setRunning(false);
    setRestSeconds(0);
    setCompletedSets({});
  }

  function toggleSet(stepIdx: number, setIdx: number) {
    const key = `${stepIdx}-${setIdx}`;
    setCompletedSets((prev) => {
      const nextVal = !prev[key];
      if (nextVal) setRestSeconds(30);
      return { ...prev, [key]: nextVal };
    });
  }

  async function finishAndSave() {
    if (!activePatientId) return;
    const elapsedMin = Math.max(5, Math.round((selectedRoutine.duration_min * 60 - secondsLeft) / 60) || selectedRoutine.duration_min);
    setBusy(true);
    try {
      await apiClient.logExercise(activePatientId, {
        activity_type: selectedRoutine.activity_type,
        duration_min: elapsedMin,
        intensity: selectedRoutine.intensity,
      });
      setRunning(false);
      setToast(`Saved ${elapsedMin} min of ${selectedRoutine.title} to your personal history.`);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const ss = String(secondsLeft % 60).padStart(2, "0");
  const totalSec = selectedRoutine.duration_min * 60;
  const timerPct = Math.round(((totalSec - secondsLeft) / Math.max(1, totalSec)) * 100);

  return (
    <div className="space-y-6">
      <BackToMoreButton />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#2B1E2F]">Mover — Guided Exercise Studio</h1>
          <p className="text-sm text-[#6B5A50]">
            Pre-workout sugar safety check, live guided timer, set tracking, and weekly ADA goals.
          </p>
        </div>
      </div>

      {toast && (
        <div className="flex items-center gap-2 rounded-2xl border border-[#239B62]/30 bg-[#EDF8F2] px-4 py-3 text-sm font-medium text-[#1D8353]">
          <CheckCircle2 className="h-4 w-4" />
          <span>{toast}</span>
        </div>
      )}

      {card && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <RingGauge
            value={card.weekly_minutes}
            max={card.target_minutes}
            label="Weekly Aerobic Goal"
            sublabel="ADA target: 150 min/week"
            color="#239B62"
          />
          <RingGauge
            value={card.resistance_sessions}
            max={card.target_resistance}
            label="Strength Sessions"
            sublabel="Target: 2+ sessions/week"
            color="#FF4D4D"
          />
        </div>
      )}

      {/* Compulsory Pre-Workout Sugar Safety Check */}
      <div className="rounded-2xl border border-[#E9DCCB] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-[#2B1E2F]">
              <ShieldCheck className="h-5 w-5 text-[#239B62]" />
              Step 1: Pre-Workout Sugar Check
            </h2>
            <p className="text-xs text-[#6B5A50]">Enter your current reading before starting your guided timer.</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={40}
              max={600}
              value={preSugar}
              onChange={(e) => {
                setPreSugar(e.target.value);
                setSugarChecked(Boolean(e.target.value));
              }}
              placeholder="mg/dL (e.g. 135)"
              className="w-40 rounded-xl border border-[#E9DCCB] bg-[#FBF6EF] px-3 py-2 text-sm font-semibold text-[#2B1E2F]"
            />
          </div>
        </div>
        {sugarChecked && sugarNum !== null && (
          <div
            className={`mt-3 flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-sm ${
              sugarLow
                ? "border-[#F2A93B]/40 bg-[#FEF7E8] text-[#9A6210]"
                : sugarHigh
                  ? "border-[#FF4D4D]/40 bg-[#FFF5F4] text-[#C93B3B]"
                  : "border-[#239B62]/30 bg-[#EDF8F2] text-[#1D8353]"
            }`}
          >
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              {sugarLow
                ? "Below 100 mg/dL: Eat a 15g fast-acting carb snack (e.g., 1 small banana or 3 dates) and re-check before exercising."
                : sugarHigh
                  ? "250 mg/dL or higher: Skip brisk cardio today; choose Gentle Mobility & Stretch only and stay hydrated."
                  : "Safe zone (100–249 mg/dL): You are cleared for your guided workout."}
            </span>
          </div>
        )}
      </div>

      {/* Routine Selector + Live Guided Player */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-2.5 rounded-2xl border border-[#E9DCCB] bg-white p-5 shadow-sm">
          <h2 className="text-base font-bold text-[#2B1E2F]">Step 2: Choose Today’s Session</h2>
          {ROUTINES.map((r) => {
            const active = selectedRoutine.id === r.id;
            const disabledForHigh = sugarHigh && r.id !== "stretch";
            return (
              <button
                key={r.id}
                type="button"
                disabled={disabledForHigh}
                onClick={() => chooseRoutine(r)}
                className={`w-full rounded-xl border p-3.5 text-left transition ${
                  active
                    ? "border-[#FF4D4D] bg-[#FFF5F4]"
                    : "border-[#E9DCCB] bg-[#FBF6EF] hover:border-[#FF4D4D]/60"
                } disabled:cursor-not-allowed disabled:opacity-45`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-[#2B1E2F]">{r.title}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-[#6B5A50]">
                    {r.duration_min} min
                  </span>
                </div>
                <p className="mt-1 text-xs text-[#6B5A50]">{r.subtitle}</p>
              </button>
            );
          })}
        </div>

        <div className="space-y-4 rounded-2xl border border-[#E9DCCB] bg-white p-5 shadow-sm lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#EFE4D6] pb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-[#FF4D4D]">Live Guided Player</p>
              <h3 className="text-xl font-bold text-[#2B1E2F]">{selectedRoutine.title}</h3>
            </div>
            <div className="flex items-center gap-3">
              {restSeconds > 0 && (
                <span className="inline-flex items-center gap-1 rounded-full bg-[#FEF7E8] px-3 py-1 text-xs font-bold text-[#9A6210]">
                  <Timer className="h-3.5 w-3.5" /> Rest {restSeconds}s
                </span>
              )}
              <span className="rounded-xl bg-[#2B1E2F] px-4 py-2 font-mono text-2xl font-bold text-white">
                {mm}:{ss}
              </span>
            </div>
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-[#F2E9DD]">
            <div className="h-full bg-[#239B62] transition-all" style={{ width: `${timerPct}%` }} />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!sugarChecked || sugarLow}
              onClick={() => setRunning((r) => !r)}
              className="inline-flex items-center gap-2 rounded-full bg-[#FF4D4D] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#e53e3e] disabled:opacity-45"
            >
              {running ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {running ? "Pause" : "Start Workout"}
            </button>
            <button
              type="button"
              onClick={() => chooseRoutine(selectedRoutine)}
              className="inline-flex items-center gap-1.5 rounded-full border border-[#E9DCCB] bg-[#FBF6EF] px-4 py-2.5 text-sm font-semibold text-[#2B1E2F]"
            >
              <RotateCcw className="h-4 w-4" /> Reset
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void finishAndSave()}
              className="ml-auto inline-flex items-center gap-2 rounded-full bg-[#239B62] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#1d8353] disabled:opacity-50"
            >
              <Flame className="h-4 w-4" /> Finish & Save
            </button>
          </div>

          {!sugarChecked && (
            <p className="text-xs font-medium text-[#7E6E64]">
              Enter your pre-workout sugar above to unlock Start Workout.
            </p>
          )}

          <div className="space-y-3 pt-2">
            {selectedRoutine.steps.map((step, idx) => (
              <div key={step.name} className="rounded-xl border border-[#E9DCCB] bg-[#FBF6EF] p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-bold text-[#2B1E2F]">
                      {idx + 1}. {step.name}
                    </p>
                    <p className="text-xs text-[#6B5A50]">{step.detail}</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Array.from({ length: step.sets }).map((_, setIdx) => {
                      const done = Boolean(completedSets[`${idx}-${setIdx}`]);
                      return (
                        <button
                          key={setIdx}
                          type="button"
                          onClick={() => toggleSet(idx, setIdx)}
                          className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold transition ${
                            done
                              ? "border-[#239B62] bg-[#239B62] text-white"
                              : "border-[#E9DCCB] bg-white text-[#2B1E2F] hover:border-[#239B62]"
                          }`}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" /> Set {setIdx + 1}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {card && card.recent_logs.length > 0 && (
        <div className="rounded-2xl border border-[#E9DCCB] bg-white p-5 shadow-sm">
          <h2 className="flex items-center gap-2 text-base font-bold text-[#2B1E2F]">
            <Dumbbell className="h-4 w-4 text-[#FF4D4D]" /> Recent Saved Sessions
          </h2>
          <div className="mt-3 space-y-2">
            {card.recent_logs.map((log) => (
              <div key={log.id} className="flex items-center justify-between rounded-xl bg-[#FBF6EF] px-3.5 py-2.5 text-sm">
                <span className="font-semibold capitalize text-[#2B1E2F]">{log.activity_type.replace(/_/g, " ")}</span>
                <span className="text-xs text-[#6B5A50]">
                  {log.duration_min} min • {log.intensity} • {new Date(log.logged_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
