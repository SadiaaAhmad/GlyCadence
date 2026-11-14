import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function AskGlyCadencePage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Ask GlyCadence
          </h1>
          <p className="text-sm text-slate-600">
            Ask questions about your longitudinal data and receive evidence-backed, non-prescriptive explanations.
          </p>
        </div>
        <Badge variant="neutral">Day 6 Target</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Evidence-Backed Conversational Q&amp;A</CardTitle>
          <CardDescription>
            All responses are grounded in deterministic Python analytics and audited by the Safety Guard.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-slate-500">
          Conversational interface will be connected in Day 6.
        </CardContent>
      </Card>
    </div>
  );
}
