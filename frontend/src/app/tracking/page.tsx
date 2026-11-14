import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function DailyTrackingPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Daily Tracking</h1>
          <p className="text-sm text-slate-600">
            Low-friction logging for glucose, meals, medication events, sleep, activity, and wellbeing.
          </p>
        </div>
        <Badge variant="neutral">Day 2 Target</Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {[
          { title: "Glucose Readings", desc: "Fasting, pre-meal, post-meal, bedtime, and CGM logs." },
          { title: "Meals & Portions", desc: "Cultural staples, macros, and meal timestamps." },
          { title: "Medication Events", desc: "Taken, delayed, missed, or unknown status logs." },
          { title: "Wellbeing & Activity", desc: "Daily stress, fatigue, sleep quality, and steps." },
        ].map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <CardTitle>{item.title}</CardTitle>
              <CardDescription>{item.desc}</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-500">
              Logging forms and historical timeline will be enabled in Day 2.
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
