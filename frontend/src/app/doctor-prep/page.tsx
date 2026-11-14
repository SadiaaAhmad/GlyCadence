import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function DoctorPrepPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Doctor Visit Preparation
          </h1>
          <p className="text-sm text-slate-600">
            Structured longitudinal trends, medication timelines, clinician discussion questions, and protected PDF export.
          </p>
        </div>
        <Badge variant="neutral">Day 5–6 Target</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>One-Page Clinician Briefing</CardTitle>
          <CardDescription>
            Generated only after passing the mandatory fail-closed Safety Guard.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-slate-500">
          Pre-appointment summary and ReportLab PDF download will be enabled in Day 6.
        </CardContent>
      </Card>
    </div>
  );
}
