"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Clock, Search, Utensils } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { MealPlanResponse, MealResponseItem, RecipeOut } from "@/types/glycadence";

export default function MealsPage() {
  const { activePatientId } = usePatientContext();
  const [tab, setTab] = useState<"plan" | "log" | "ideas">("plan");
  const [plan, setPlan] = useState<MealPlanResponse | null>(null);
  const [mealLog, setMealLog] = useState<MealResponseItem[]>([]);
  const [recipes, setRecipes] = useState<RecipeOut[]>([]);
  const [slotFilter, setSlotFilter] = useState<string>("");
  const [vegOnly, setVegOnly] = useState(false);
  const [searchText, setSearchText] = useState("");

  useEffect(() => {
    if (!activePatientId) return;
    Promise.all([
      apiClient.getMealPlan(activePatientId),
      apiClient.getMealResponses(activePatientId),
    ]).then(([pl, ml]) => {
      setPlan(pl);
      setMealLog(ml);
    });
  }, [activePatientId]);

  useEffect(() => {
    apiClient
      .listRecipes({
        slot: slotFilter || undefined,
        vegetarian: vegOnly || undefined,
        q: searchText || undefined,
      })
      .then(setRecipes);
  }, [slotFilter, vegOnly, searchText]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Meals &amp; Timing</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Tap any meal or recipe to view ingredients, computed sugar &amp; fibre, and your personal glucose response.
          </p>
        </div>

        <div className="flex gap-1.5 bg-[var(--bg-muted)] p-1 rounded-full">
          {[
            { id: "plan", label: "My Plan" },
            { id: "log", label: "My Log" },
            { id: "ideas", label: "30 Desi Ideas" },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id as "plan" | "log" | "ideas")}
              className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${
                tab === t.id
                  ? "bg-[#2B1E2F] text-white dark:bg-[#F2A93B] dark:text-[#2B1E2F]"
                  : "text-[var(--text-muted)]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* TAB 1: My Daily Timing Plan */}
      {tab === "plan" && (
        <div className="space-y-5">
          {(plan?.slots ?? []).map((slot) => (
            <section key={slot.slot} className="gc-card p-5 space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="font-display text-lg font-semibold capitalize">{slot.slot}</span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-[#F2A93B]/20 px-3 py-0.5 text-xs font-semibold text-[#9B630B] dark:text-[#F2A93B]">
                    <Clock className="h-3 w-3" />
                    {slot.suggested_window}
                  </span>
                </div>
                <span className="text-xs text-[var(--text-muted)]">{slot.reason_chip}</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {slot.recommended_recipes.map((rec) => (
                  <Link
                    key={rec.id}
                    href={`/meals/${rec.id}`}
                    className="rounded-2xl border border-[var(--border-clay)] bg-[var(--bg-page)] overflow-hidden hover:border-[#FF4D4D] transition-colors flex flex-col"
                  >
                    <img src={rec.image_url} alt={rec.name} className="h-32 w-full object-cover" />
                    <div className="p-3 space-y-1.5 flex-1 flex flex-col justify-between">
                      <div className="font-semibold text-xs line-clamp-2">{rec.name}</div>
                      <div className="text-[11px] text-[var(--text-muted)]">
                        {rec.nutrition.carbs_g}g carbs · {rec.nutrition.sugar_g}g sugar · {rec.nutrition.gl_band} GL
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {/* TAB 2: Patient's Logged Meals & Observed Responses */}
      {tab === "log" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {mealLog.length === 0 ? (
            <div className="gc-card p-6 text-sm text-[var(--text-muted)]">
              No meals logged yet for this patient.
            </div>
          ) : (
            mealLog.map((m) => (
              <Link
                key={m.meal_id}
                href={`/meals/${m.meal_id}`}
                className="gc-card p-4 flex items-center justify-between gap-3 hover:border-[#FF4D4D]"
              >
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Utensils className="h-3.5 w-3.5 text-[#F2A93B] shrink-0" />
                    <span className="font-semibold text-sm truncate">{m.description}</span>
                  </div>
                  <div className="text-xs text-[var(--text-muted)] capitalize">
                    {m.meal_type} · {new Date(m.logged_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {m.iauc_valid && m.excursion_delta_mg_dl !== null ? (
                    <span className="rounded-full bg-[#F2A93B]/20 px-3 py-1 text-xs font-semibold tabular-nums text-[#9B630B] dark:text-[#F2A93B]">
                      {m.excursion_delta_mg_dl >= 0 ? `+${Math.round(m.excursion_delta_mg_dl)}` : Math.round(m.excursion_delta_mg_dl)} mg/dL
                    </span>
                  ) : (
                    <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-[11px] text-[var(--text-muted)]">
                      Tap for details
                    </span>
                  )}
                </div>
              </Link>
            ))
          )}
        </div>
      )}

      {/* TAB 3: Curated Recipe Ideas */}
      {tab === "ideas" && (
        <div className="space-y-4">
          <div className="gc-card p-4 flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="h-4 w-4 text-[var(--text-muted)] absolute left-3 top-2.5" />
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="Search chana, roti, tikka, dalia..."
                className="w-full rounded-[12px] border border-[var(--border-clay)] bg-[var(--bg-page)] pl-9 pr-3 py-2 text-xs focus:border-[#FF4D4D] focus:outline-none"
              />
            </div>

            <select
              value={slotFilter}
              onChange={(e) => setSlotFilter(e.target.value)}
              aria-label="Filter by meal time"
              className="rounded-[12px] border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-xs"
            >
              <option value="">All meal slots</option>
              <option value="breakfast">Breakfast</option>
              <option value="lunch">Lunch</option>
              <option value="dinner">Dinner</option>
              <option value="snack">Snack</option>
              <option value="suhoor">Suhoor</option>
              <option value="iftar">Iftar</option>
            </select>

            <label className="inline-flex items-center gap-2 text-xs font-medium cursor-pointer">
              <input type="checkbox" checked={vegOnly} onChange={(e) => setVegOnly(e.target.checked)} />
              Vegetarian only
            </label>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {recipes.map((rec) => (
              <Link
                key={rec.id}
                href={`/meals/${rec.id}`}
                className="gc-card overflow-hidden hover:border-[#FF4D4D] transition-colors flex flex-col"
              >
                <img src={rec.image_url} alt={rec.name} className="h-40 w-full object-cover" />
                <div className="p-4 space-y-2 flex-1 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between text-[11px] text-[var(--text-muted)] capitalize">
                      <span>{rec.slot} · {rec.prep_min} min</span>
                      <span>{rec.cost_tier === "low" ? "₨" : rec.cost_tier === "medium" ? "₨₨" : "₨₨₨"}</span>
                    </div>
                    <h3 className="font-display text-base font-semibold mt-1">{rec.name}</h3>
                  </div>
                  <div className="flex flex-wrap gap-1.5 text-[11px] pt-1">
                    <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-0.5">
                      {rec.nutrition.carbs_g}g carbs
                    </span>
                    <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-0.5">
                      {rec.nutrition.sugar_g}g sugar
                    </span>
                    <span className="rounded-full bg-[#F2A93B]/20 px-2.5 py-0.5 font-medium">
                      {rec.nutrition.gl_band} GL
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
