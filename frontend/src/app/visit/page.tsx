"use client";

import React, { useEffect, useState } from "react";
import { HelpCircle, Printer } from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient, API_BASE_URL, getStoredToken } from "@/services/api";
import type { VisitReportResponse } from "@/types/glycadence";

export default function VisitPage() {
  const { activePatientId } = usePatientContext();
  const [report, setReport] = useState<VisitReportResponse | null>(null);
  const [openWhy, setOpenWhy] = useState<number | null>(null);
  const [forClinicians, setForClinicians] = useState(false);

  useEffect(() => {
    if (!activePatientId) return;
    apiClient.getVisitReport(activePatientId).then(setReport);
  }, [activePatientId]);

  async function openPrintableReport() {
    if (!activePatientId) return;
    const tok = getStoredToken();
    const res = await fetch(`${API_BASE_URL}/api/v1/patients/${activePatientId}/visit-report?format=html`, {
      headers: tok ? { Authorization: `Bearer ${tok}` } : {},
    });
    const html = await res.text();
    const w = window.open("", "_blank");
    if (w) {
      w.document.write(html);
      w.document.close();
      w.focus();
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-semibold">Doctor Visit Report</h1>
          <p className="text-sm text-[var(--text-muted)]">
            A clear 1-page summary and personal questions for your next 7-minute clinic appointment.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void openPrintableReport()}
          className="inline-flex items-center gap-2 rounded-[14px] bg-[#FF4D4D] px-4 py-2 text-sm font-semibold text-white hover:bg-[#e84141]"
        >
          <Printer className="h-4 w-4" />
          Open Printable Report / PDF
        </button>
      </div>

      {report && (
        <>
          <section className="gc-card p-6 space-y-3">
            <h2 className="font-display text-lg font-semibold">Your Recent Overview</h2>
            <ul className="space-y-1.5 text-sm">
              {report.personal_summary.map((line, i) => (
                <li key={i} className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] px-3.5 py-2">
                  {line}
                </li>
              ))}
            </ul>
          </section>

          <section className="gc-card p-6 space-y-3">
            <h2 className="font-display text-lg font-semibold">Questions to Ask Your Doctor</h2>
            <div className="space-y-3">
              {report.questions.map((q, idx) => (
                <div key={idx} className="rounded-2xl border border-[var(--border-clay)] bg-[var(--bg-page)] p-4 space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium">{q.question}</p>
                    <button
                      type="button"
                      onClick={() => setOpenWhy(openWhy === idx ? null : idx)}
                      className="inline-flex items-center gap-1 rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-xs font-semibold shrink-0 hover:border-[#FF4D4D]"
                    >
                      <HelpCircle className="h-3.5 w-3.5 text-[#FF4D4D]" />
                      Why?
                    </button>
                  </div>
                  {openWhy === idx && (
                    <p className="text-xs text-[var(--text-muted)] border-t border-[var(--border-clay)] pt-2">
                      {q.why}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section className="gc-card p-5 space-y-3">
            <label className="inline-flex items-center gap-2 text-xs font-semibold cursor-pointer">
              <input
                type="checkbox"
                checked={forClinicians}
                onChange={(e) => setForClinicians(e.target.checked)}
              />
              <span>For clinicians (technical metadata)</span>
            </label>
            {forClinicians && (
              <pre className="rounded-xl bg-[var(--bg-page)] border border-[var(--border-clay)] p-3 text-xs overflow-x-auto">
                {JSON.stringify(report.clinician_appendix, null, 2)}
              </pre>
            )}
          </section>
        </>
      )}
    </div>
  );
}
