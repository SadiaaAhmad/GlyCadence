import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function IntelligenceCenterPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Intelligence Center</h1>
          <p className="text-sm text-slate-600">
            Pattern detection, medication-pattern analysis, food-response evidence, and agent reasoning traces.
          </p>
        </div>
        <Badge variant="neutral">Day 4–5 Target</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Cross-Signal Evidence &amp; Provenance</CardTitle>
          <CardDescription>
            Every insight displays supporting observation counts, time windows, missingness, and uncertainty notes.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-slate-500">
          Multi-agent LangGraph investigations and EvidenceItem provenance cards will populate here.
        </CardContent>
      </Card>
    </div>
  );
}
