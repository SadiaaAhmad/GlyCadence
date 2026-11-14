"use client";

import React, { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Database, RefreshCw, ServerCrash } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/services/api";
import type { DatabaseHealthResponse, HealthResponse } from "@/types/health";

export function SystemStatusCard() {
  const [apiHealth, setApiHealth] = useState<HealthResponse | null>(null);
  const [dbHealth, setDbHealth] = useState<DatabaseHealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const runHealthCheck = useCallback(async () => {
    try {
      const [apiRes, dbRes] = await Promise.all([
        apiClient.getHealth(),
        apiClient.getDatabaseHealth(),
      ]);
      setApiHealth(apiRes);
      setDbHealth(dbRes);
      setError(null);
    } catch {
      setError("Unable to reach FastAPI backend on configured API URL.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const init = async () => {
      if (!active) return;
      await runHealthCheck();
    };
    void init();
    return () => {
      active = false;
    };
  }, [runHealthCheck]);

  const handleRecheck = () => {
    setLoading(true);
    void runHealthCheck();
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Platform Connectivity</CardTitle>
          <CardDescription>
            Live status between Next.js, FastAPI, and PostgreSQL (15+)
          </CardDescription>
        </div>
        <button
          type="button"
          onClick={handleRecheck}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Recheck</span>
        </button>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <div className="flex items-center justify-between rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5">
          <div className="flex items-center gap-2.5">
            {apiHealth ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            ) : (
              <ServerCrash className="h-5 w-5 text-amber-600" />
            )}
            <div>
              <p className="text-sm font-medium text-slate-900">FastAPI Backend</p>
              <p className="text-xs text-slate-500">
                {apiHealth ? `${apiHealth.service} v${apiHealth.version}` : error ?? "Checking..."}
              </p>
            </div>
          </div>
          <Badge variant={apiHealth ? "success" : "warning"}>
            {apiHealth ? "Online" : "Offline"}
          </Badge>
        </div>

        <div className="flex items-center justify-between rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5">
          <div className="flex items-center gap-2.5">
            <Database
              className={`h-5 w-5 ${
                dbHealth?.status === "ok" ? "text-emerald-600" : "text-amber-600"
              }`}
            />
            <div>
              <p className="text-sm font-medium text-slate-900">PostgreSQL Database</p>
              <p className="text-xs text-slate-500">
                {dbHealth
                  ? dbHealth.status === "ok"
                    ? `Connected (PostgreSQL ${dbHealth.detected_major_version})`
                    : `Status: ${dbHealth.database}`
                  : "Waiting for backend..."}
              </p>
            </div>
          </div>
          <Badge variant={dbHealth?.status === "ok" ? "success" : "warning"}>
            {dbHealth?.status === "ok" ? "Connected" : "Pending"}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}
