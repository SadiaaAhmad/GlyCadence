import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SystemStatusCard } from "@/components/dashboard/SystemStatusCard";
import { SampleGlucosePreview } from "@/components/charts/SampleGlucosePreview";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Dashboard
          </h1>
          <p className="text-sm text-slate-600">
            Today&apos;s glucose overview, personal baseline comparison, and what&apos;s changed.
          </p>
        </div>
        <Badge variant="neutral">UI Skeleton · Day 1</Badge>
      </div>

      <SystemStatusCard />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Glucose Rhythm Preview</CardTitle>
            <CardDescription>
              Recharts visualization container ready for Day 2–3 longitudinal data.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SampleGlucosePreview />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>What&apos;s Changed?</CardTitle>
            <CardDescription>
              Cross-signal insights will appear here once analytics &amp; agents are connected.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-600">
            <div className="rounded-xl bg-slate-50 p-3 border border-slate-200/70">
              Personal baseline comparison pending patient records (Day 2–3).
            </div>
            <div className="rounded-xl bg-[#FFF1F1]/70 p-3 border border-[#FF4D4D]/20 text-slate-700">
              Cadie is ready to guide daily logging and pre-visit summaries.
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
