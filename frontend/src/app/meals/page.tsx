import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function MealPlannerPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Personalized Meal Planner
          </h1>
          <p className="text-sm text-slate-600">
            Neutral, evidence-based food-response history and culturally familiar meal alternatives.
          </p>
        </div>
        <Badge variant="neutral">Day 4–6 Target</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Adaptive Cultural Meal Suggestions</CardTitle>
          <CardDescription>
            Respects dietary restrictions and uses neutral, non-judgmental phrasing.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-slate-500">
          Postprandial meal response curves and weekly meal suggestions will appear here.
        </CardContent>
      </Card>
    </div>
  );
}
