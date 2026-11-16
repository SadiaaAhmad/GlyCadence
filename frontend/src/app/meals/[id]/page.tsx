"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Clock, MessageCircleHeart, Sparkles } from "lucide-react";
import { Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { MealDetailOut } from "@/types/glycadence";

export default function MealDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;
  const { activePatientId } = usePatientContext();

  const [detail, setDetail] = useState<MealDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id || !activePatientId) return;
    let cancelled = false;
    setError(null);
    // Try patient logged meal first, fall back cleanly to recipe catalog detail
    apiClient
      .getPatientMealDetail(activePatientId, id)
      .catch(() => apiClient.getRecipeDetail(id, activePatientId))
      .then((res) => {
        if (!cancelled) setDetail(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load meal details");
      });
    return () => {
      cancelled = true;
    };
  }, [id, activePatientId]);

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/meals" className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF4D4D]">
          <ArrowLeft className="h-4 w-4" /> Back to Meals
        </Link>
        <div className="gc-card p-6 text-sm text-[#8E2C5A]">{error}</div>
      </div>
    );
  }

  if (!detail) {
    return <div className="p-6 text-sm text-[var(--text-muted)]">Loading meal details...</div>;
  }

  const { recipe, personal_history } = detail;
  const n = recipe.nutrition;

  return (
    <div className="space-y-6">
      <Link href="/meals" className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF4D4D]">
        <ArrowLeft className="h-4 w-4" /> Back to Meals
      </Link>

      {/* Hero Photo + Title + Timing */}
      <section className="gc-card overflow-hidden">
        <div className="grid grid-cols-1 md:grid-cols-12">
          <div className="md:col-span-5">
            <img src={recipe.image_url} alt={recipe.name} className="h-64 md:h-full w-full object-cover" />
          </div>
          <div className="md:col-span-7 p-6 space-y-3 flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full bg-[#F2A93B]/20 px-3 py-0.5 font-semibold capitalize">
                  {detail.meal_type}
                </span>
                <span className="inline-flex items-center gap-1 rounded-full bg-[var(--bg-muted)] px-3 py-0.5">
                  <Clock className="h-3 w-3" /> Best window: {detail.recommended_time_window}
                </span>
                <span className="rounded-full bg-[var(--bg-muted)] px-3 py-0.5">
                  {recipe.prep_min} min · {recipe.cost_tier === "low" ? "Budget-friendly" : "Moderate cost"}
                </span>
                {detail.confidence_label && (
                  <span className="rounded-full bg-emerald-500/15 px-3 py-0.5 font-semibold text-emerald-700 dark:text-emerald-300">
                    {detail.confidence_label}
                  </span>
                )}
              </div>
              <h1 className="font-display text-2xl sm:text-3xl font-semibold mt-3">{recipe.name}</h1>
              <p className="text-sm text-[var(--text-muted)] mt-1">{detail.best_time_reason}</p>
            </div>

            <div className="pt-2">
              <button
                type="button"
                onClick={() =>
                  router.push(`/ask?q=${encodeURIComponent(`How does ${recipe.name} fit my glucose pattern?`)}`)
                }
                className="inline-flex items-center gap-2 rounded-[14px] bg-[#FF4D4D] px-4 py-2 text-sm font-semibold text-white hover:bg-[#e84141]"
              >
                <MessageCircleHeart className="h-4 w-4" />
                Ask Cadie about this meal
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Nutrition Table + Personal Response Curve */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <section className="lg:col-span-5 gc-card p-6 space-y-4">
          <div>
            <h2 className="font-display text-lg font-semibold">Nutrition per portion</h2>
            <p className="text-xs text-[var(--text-muted)]">Computed directly from ingredient grams</p>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm tabular-nums">
            <div className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3">
              <div className="text-xs text-[var(--text-muted)]">Total Carbs</div>
              <div className="text-xl font-bold mt-0.5">{n.carbs_g} g</div>
            </div>
            <div className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3">
              <div className="text-xs text-[var(--text-muted)]">Of which Sugar</div>
              <div className="text-xl font-bold text-[#C8553D] mt-0.5">{n.sugar_g} g</div>
            </div>
            <div className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3">
              <div className="text-xs text-[var(--text-muted)]">Dietary Fibre</div>
              <div className="text-xl font-bold mt-0.5">{n.fibre_g} g</div>
            </div>
            <div className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3">
              <div className="text-xs text-[var(--text-muted)]">Protein / Fat</div>
              <div className="text-base font-bold mt-1">{n.protein_g}g / {n.fat_g}g</div>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs pt-1 border-t border-[var(--border-clay)]">
            <span>Energy: <strong>{n.kcal} kcal</strong></span>
            <span className="rounded-full bg-[#F2A93B]/20 px-3 py-0.5 font-semibold">
              {n.gl_band} Glycaemic Load ({n.estimated_gl})
            </span>
          </div>
        </section>

        <section className="lg:col-span-7 gc-card p-6 space-y-3">
          <div>
            <h2 className="font-display text-lg font-semibold">How this meal has gone for you</h2>
            <p className="text-sm text-[var(--text-muted)]">{personal_history.summary_text}</p>
          </div>

          {personal_history.curve_points.length > 0 ? (
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={personal_history.curve_points} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
                  <XAxis
                    dataKey="offset_min"
                    tickFormatter={(v) => `${v}m`}
                    stroke="#9C8E9E"
                    fontSize={11}
                  />
                  <YAxis domain={[60, 220]} stroke="#9C8E9E" fontSize={11} />
                  <Tooltip
                    formatter={(val) => [`${val} mg/dL`, "Avg glucose"]}
                    labelFormatter={(lbl) => `${lbl} min from meal`}
                  />
                  <ReferenceArea y1={70} y2={180} fill="#F2A93B" fillOpacity={0.18} />
                  <Line type="monotone" dataKey="glucose_mg_dl" stroke="#FF4D4D" strokeWidth={2.5} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="rounded-2xl bg-[var(--bg-muted)] p-5 text-sm text-[var(--text-muted)]">
              Not logged with a sensor curve yet. Log this meal next time you eat it to see your personal curve here.
            </div>
          )}
        </section>
      </div>

      {/* What it may mean + Recipe Steps & Ingredients */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <section className="lg:col-span-5 gc-card p-6 space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[#F2A93B]" />
            <h2 className="font-display text-lg font-semibold">What this may mean for you</h2>
          </div>
          <ul className="space-y-2.5 text-sm leading-relaxed">
            {detail.what_it_may_mean.map((line, i) => (
              <li key={i} className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3">
                {line}
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-[var(--text-muted)]">Source: {detail.health_education_source}</p>
        </section>

        <section className="lg:col-span-7 gc-card p-6 space-y-4">
          <h2 className="font-display text-lg font-semibold">Authentic Home Recipe</h2>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-2">
              Ingredients (1 serving)
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
              {recipe.ingredients.map((ing, i) => (
                <div key={i} className="flex items-center justify-between rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] px-3 py-2">
                  <span>{ing.name}</span>
                  <span className="font-semibold tabular-nums">{ing.grams} g</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-2">
              Preparation Steps
            </div>
            <ol className="list-decimal pl-5 space-y-1.5 text-sm">
              {recipe.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
        </section>
      </div>
    </div>
  );
}
