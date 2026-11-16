"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChefHat, Clock, Plus, Search, Utensils } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { MealPlanResponse, MealResponseItem, RecipeOut } from "@/types/glycadence";

export default function MealsPage() {
  const { activePatientId } = usePatientContext();
  const [tab, setTab] = useState<"plan" | "log" | "ideas" | "chef">("plan");
  const [plan, setPlan] = useState<MealPlanResponse | null>(null);
  const [mealLog, setMealLog] = useState<MealResponseItem[]>([]);
  const [recipes, setRecipes] = useState<RecipeOut[]>([]);
  const [slotFilter, setSlotFilter] = useState<string>("");
  const [vegOnly, setVegOnly] = useState(false);
  const [searchText, setSearchText] = useState("");

  // Log Meal form
  const [logDesc, setLogDesc] = useState("");
  const [logType, setLogType] = useState<"breakfast" | "lunch" | "dinner" | "snack">("lunch");
  const [logCarbs, setLogCarbs] = useState("");
  const [logSugar, setLogSugar] = useState("");
  const [logBusy, setLogBusy] = useState(false);
  const [logMsg, setLogMsg] = useState<string | null>(null);

  // Kitchen Chef from ingredients
  const [ingText, setIngText] = useState("");
  const [ingType, setIngType] = useState<"breakfast" | "lunch" | "dinner" | "snack">("lunch");
  const [chefBusy, setChefBusy] = useState(false);
  const [chefResult, setChefResult] = useState<{
    recipe_title: string;
    matched_ingredients: string[];
    nutrition: {
      carbs_g: number;
      sugar_g: number;
      fibre_g: number;
      protein_g: number;
      fat_g: number;
      calories_kcal: number;
      estimated_gl: number;
    };
    suitability_verdict: string;
    steps: string[];
  } | null>(null);

  const loadMeals = useCallback(async () => {
    if (!activePatientId) return;
    const [pl, ml] = await Promise.all([
      apiClient.getMealPlan(activePatientId),
      apiClient.getMealResponses(activePatientId),
    ]);
    setPlan(pl);
    setMealLog(ml);
  }, [activePatientId]);

  useEffect(() => {
    void loadMeals();
  }, [loadMeals]);

  useEffect(() => {
    apiClient
      .listRecipes({
        slot: slotFilter || undefined,
        vegetarian: vegOnly || undefined,
        q: searchText || undefined,
      })
      .then(setRecipes);
  }, [slotFilter, vegOnly, searchText]);

  async function handleLogMeal(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId || !logDesc.trim()) return;
    setLogBusy(true);
    setLogMsg(null);
    try {
      await apiClient.logMeal(activePatientId, {
        description: logDesc.trim(),
        meal_type: logType,
        carbs_g: logCarbs ? Number(logCarbs) : undefined,
        glucose_mg_dl: logSugar ? Number(logSugar) : undefined,
      });
      setLogDesc("");
      setLogCarbs("");
      setLogSugar("");
      setLogMsg("Meal saved to your personal log.");
      await loadMeals();
    } finally {
      setLogBusy(false);
    }
  }

  async function handleChefGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId || !ingText.trim()) return;
    setChefBusy(true);
    try {
      const res = await apiClient.makeRecipeFromIngredients(activePatientId, {
        ingredients_text: ingText.trim(),
        meal_type: ingType,
      });
      setChefResult(res);
    } finally {
      setChefBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Meals &amp; Timing</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Log meals, generate a sugar-friendly recipe from ingredients at home, or view your personal glucose responses.
          </p>
        </div>

        <div className="flex flex-wrap gap-1 bg-[var(--bg-muted)] p-1 rounded-full">
          {[
            { id: "plan", label: "My Plan" },
            { id: "log", label: "Log & History" },
            { id: "chef", label: "Kitchen Chef" },
            { id: "ideas", label: "30 Desi Ideas" },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id as "plan" | "log" | "ideas" | "chef")}
              className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors ${
                tab === t.id
                  ? "bg-[#2B1E2F] text-white dark:bg-[#F2A93B] dark:text-[#2B1E2F]"
                  : "text-[var(--text-muted)] hover:text-[var(--text-main)]"
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
        <div className="space-y-4">
          <form onSubmit={(e) => void handleLogMeal(e)} className="gc-card p-5 space-y-3 border-[#FF4D4D]/30">
            <div className="flex items-center gap-2 font-display text-base font-semibold">
              <Plus className="h-4 w-4 text-[#FF4D4D]" /> Log a Meal
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
              <input
                required
                value={logDesc}
                onChange={(e) => setLogDesc(e.target.value)}
                placeholder="What did you eat? (e.g. Daal + 1 roti)"
                className="sm:col-span-2 rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
              />
              <select
                value={logType}
                onChange={(e) => setLogType(e.target.value as "breakfast" | "lunch" | "dinner" | "snack")}
                className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
              >
                <option value="breakfast">Breakfast</option>
                <option value="lunch">Lunch</option>
                <option value="dinner">Dinner</option>
                <option value="snack">Snack</option>
              </select>
              <input
                type="number"
                value={logSugar}
                onChange={(e) => setLogSugar(e.target.value)}
                placeholder="Optional sugar (mg/dL)"
                className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <input
                type="number"
                value={logCarbs}
                onChange={(e) => setLogCarbs(e.target.value)}
                placeholder="Optional carbs (g)"
                className="w-48 rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-1.5 text-xs"
              />
              <button
                type="submit"
                disabled={logBusy}
                className="rounded-full bg-[#FF4D4D] px-5 py-2 text-xs font-semibold text-white hover:bg-[#e84141] disabled:opacity-50"
              >
                {logBusy ? "Saving…" : "Save Meal"}
              </button>
            </div>
            {logMsg && <p className="text-xs font-semibold text-[#1D8353]">{logMsg}</p>}
          </form>

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
        </div>
      )}

      {/* TAB 4: Kitchen Chef — Make From My Ingredients */}
      {tab === "chef" && (
        <div className="space-y-4">
          <form onSubmit={(e) => void handleChefGenerate(e)} className="gc-card p-5 space-y-4 border-[#F2A93B]/40">
            <div className="flex items-center gap-2 font-display text-lg font-semibold">
              <ChefHat className="h-5 w-5 text-[#FF4D4D]" />
              Make a Sugar-Friendly Recipe From My Ingredients
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              Type what you have in your kitchen (e.g. eggs, spinach, tomato, whole wheat roti, chicken, chana). We compute exact carbs, sugar, fibre, glycemic load, and cooking steps.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
              <input
                required
                value={ingText}
                onChange={(e) => setIngText(e.target.value)}
                placeholder="eggs, spinach, tomato, whole wheat roti"
                className="sm:col-span-3 rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-2.5 text-sm"
              />
              <select
                value={ingType}
                onChange={(e) => setIngType(e.target.value as "breakfast" | "lunch" | "dinner" | "snack")}
                className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2.5 text-sm"
              >
                <option value="breakfast">Breakfast</option>
                <option value="lunch">Lunch</option>
                <option value="dinner">Dinner</option>
                <option value="snack">Snack</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={chefBusy}
              className="rounded-full bg-[#FF4D4D] px-6 py-2.5 text-xs font-semibold text-white hover:bg-[#e84141] disabled:opacity-50"
            >
              {chefBusy ? "Computing nutrition & steps…" : "Generate Sugar-Friendly Recipe"}
            </button>
          </form>

          {chefResult && (
            <div className="gc-card p-6 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-display text-xl font-semibold">{chefResult.recipe_title}</h2>
                <span className="rounded-full bg-[#239B62]/15 px-3 py-1 text-xs font-semibold text-[#1D8353]">
                  Est. GL {chefResult.nutrition.estimated_gl}
                </span>
              </div>
              <p className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3 text-sm font-medium text-[var(--text-main)]">
                {chefResult.suitability_verdict}
              </p>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center text-xs">
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.carbs_g}g</div>
                  <div className="text-[var(--text-muted)]">Carbs</div>
                </div>
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.sugar_g}g</div>
                  <div className="text-[var(--text-muted)]">Sugar</div>
                </div>
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.fibre_g}g</div>
                  <div className="text-[var(--text-muted)]">Fibre</div>
                </div>
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.protein_g}g</div>
                  <div className="text-[var(--text-muted)]">Protein</div>
                </div>
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.fat_g}g</div>
                  <div className="text-[var(--text-muted)]">Fat</div>
                </div>
                <div className="rounded-xl bg-[var(--bg-muted)] p-2.5">
                  <div className="font-bold text-base">{chefResult.nutrition.calories_kcal}</div>
                  <div className="text-[var(--text-muted)]">kcal</div>
                </div>
              </div>
              <div>
                <h3 className="text-sm font-semibold mb-2">Cooking Steps</h3>
                <ol className="list-decimal pl-5 space-y-1.5 text-sm text-[var(--text-muted)]">
                  {chefResult.steps.map((st, idx) => (
                    <li key={idx}>{st}</li>
                  ))}
                </ol>
              </div>
            </div>
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
