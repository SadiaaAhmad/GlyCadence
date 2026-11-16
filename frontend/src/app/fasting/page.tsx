"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, Moon } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";

interface RozaCard {
  city: string;
  risk_tier: string;
  score: number;
  break_fast_rules: string[];
  suhoor_recipe_id?: string | null;
  suhoor_name: string;
  iftar_recipe_id?: string | null;
  iftar_name: string;
  check_times: string[];
}

export default function FastingPage() {
  const { activePatientId } = usePatientContext();
  const [rozaCard, setRozaCard] = useState<RozaCard | null>(null);
  const [egfr, setEgfr] = useState<string>("");
  const [pregnant, setPregnant] = useState(false);
  const [extraHypos, setExtraHypos] = useState(0);
  const [customRisk, setCustomRisk] = useState<{
    score: number;
    risk_tier: string;
    reasons: string[];
    summary: string;
  } | null>(null);

  useEffect(() => {
    if (!activePatientId) return;
    apiClient.getRamadanPlan(activePatientId).then((res) => {
      const cards = (res.roza?.cards as RozaCard[]) ?? [];
      if (cards.length > 0) setRozaCard(cards[0]);
    });
  }, [activePatientId]);

  async function runRiskCheck(e: React.FormEvent) {
    e.preventDefault();
    if (!activePatientId) return;
    const res = await apiClient.postFastingRiskCheck(activePatientId, {
      egfr: egfr.trim() ? Number(egfr) : undefined,
      pregnant,
      extra_recent_hypos: extraHypos,
    });
    setCustomRisk(res);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold">Ramadan &amp; Fasting (Roza Guide)</h1>
        <p className="text-sm text-[var(--text-muted)]">
          IDF-DAR 2021 fasting risk screening, Suhoor/Iftar meal ideas, and when to break the fast for safety.
        </p>
      </div>

      {/* Break the fast safety banner */}
      <section className="gc-card p-5 border-2 border-[#8E2C5A]/50 bg-[#8E2C5A]/8 space-y-2">
        <div className="flex items-center gap-2 font-display text-base font-semibold text-[#8E2C5A]">
          <AlertTriangle className="h-5 w-5" />
          When to Break the Fast Immediately (IDF-DAR Guidance)
        </div>
        <ul className="list-disc pl-5 text-sm space-y-1">
          {(rozaCard?.break_fast_rules ?? [
            "Break the fast if blood sugar drops below 70 mg/dL.",
            "Break the fast if blood sugar rises above 300 mg/dL.",
            "Break the fast if you feel shaky, dizzy, confused, or acutely unwell.",
          ]).map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* IDF-DAR Interactive Risk Check */}
        <form onSubmit={runRiskCheck} className="gc-card p-6 space-y-4">
          <div className="flex items-center gap-2">
            <Moon className="h-5 w-5 text-[#F2A93B]" />
            <h2 className="font-display text-lg font-semibold">IDF-DAR Risk Check</h2>
          </div>

          <label className="block text-xs space-y-1">
            <span>Latest kidney eGFR (leave blank if unknown)</span>
            <input
              type="number"
              value={egfr}
              onChange={(e) => setEgfr(e.target.value)}
              placeholder="e.g., 75"
              className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-xs space-y-1">
            <span>Additional lows in past 3 months</span>
            <input
              type="number"
              min={0}
              max={20}
              value={extraHypos}
              onChange={(e) => setExtraHypos(Number(e.target.value))}
              className="w-full rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] px-3 py-2 text-sm"
            />
          </label>

          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={pregnant} onChange={(e) => setPregnant(e.target.checked)} />
            <span>Currently pregnant</span>
          </label>

          <button
            type="submit"
            className="w-full rounded-[14px] bg-[#FF4D4D] py-2.5 text-sm font-semibold text-white hover:bg-[#e84141]"
          >
            Calculate IDF-DAR Tier
          </button>

          {(customRisk || rozaCard) && (
            <div className="rounded-xl bg-[var(--bg-muted)] p-3.5 text-xs space-y-1">
              <div className="font-semibold uppercase">
                Risk tier: {customRisk ? customRisk.risk_tier : rozaCard?.risk_tier} (Score:{" "}
                {customRisk ? customRisk.score : rozaCard?.score})
              </div>
              <p>{customRisk ? customRisk.summary : "Discuss your fasting plan and medicine timing with your doctor before Ramadan."}</p>
            </div>
          )}
        </form>

        {/* Suhoor & Iftar Meal Plan + Check Schedule */}
        <section className="gc-card p-6 space-y-4">
          <h2 className="font-display text-lg font-semibold">
            Suhoor &amp; Iftar Plan ({rozaCard?.city ?? "Lahore"})
          </h2>
          <div className="space-y-3 text-sm">
            {rozaCard?.suhoor_recipe_id && (
              <Link
                href={`/meals/${rozaCard.suhoor_recipe_id}`}
                className="block rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] p-3.5 hover:border-[#FF4D4D]"
              >
                <div className="text-xs font-semibold text-[#9B630B] dark:text-[#F2A93B]">Suhoor (Pre-dawn)</div>
                <div className="font-semibold mt-0.5">{rozaCard.suhoor_name}</div>
              </Link>
            )}
            {rozaCard?.iftar_recipe_id && (
              <Link
                href={`/meals/${rozaCard.iftar_recipe_id}`}
                className="block rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] p-3.5 hover:border-[#FF4D4D]"
              >
                <div className="text-xs font-semibold text-[#FF4D4D]">Iftar (Sunset)</div>
                <div className="font-semibold mt-0.5">{rozaCard.iftar_name}</div>
              </Link>
            )}
          </div>

          <div className="pt-2 border-t border-[var(--border-clay)]">
            <div className="flex items-center gap-1.5 text-xs font-semibold mb-2">
              <Clock className="h-3.5 w-3.5 text-[#F2A93B]" />
              Recommended Sugar Checks (Checking does not break the fast)
            </div>
            <div className="flex flex-wrap gap-2">
              {(rozaCard?.check_times ?? ["Mid-day", "Pre-Iftar", "2 hours post-Iftar"]).map((t) => (
                <span key={t} className="rounded-full bg-[var(--bg-muted)] px-3 py-1 text-xs">
                  {t}
                </span>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
