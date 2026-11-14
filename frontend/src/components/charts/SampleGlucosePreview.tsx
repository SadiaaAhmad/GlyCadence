"use client";

import React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const PLACEHOLDER_PREVIEW = [
  { time: "08:00", mgDl: 112 },
  { time: "10:00", mgDl: 138 },
  { time: "12:00", mgDl: 118 },
  { time: "14:00", mgDl: 146 },
  { time: "16:00", mgDl: 124 },
  { time: "18:00", mgDl: 119 },
];

export function SampleGlucosePreview() {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={PLACEHOLDER_PREVIEW} margin={{ top: 10, right: 12, left: -16, bottom: 0 }}>
          <defs>
            <linearGradient id="cadenceTeal" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#0F4C5C" stopOpacity={0.22} />
              <stop offset="95%" stopColor="#0F4C5C" stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
          <XAxis dataKey="time" tick={{ fontSize: 12, fill: "#64748B" }} />
          <YAxis domain={[70, 180]} tick={{ fontSize: 12, fill: "#64748B" }} />
          <Tooltip />
          <Area
            type="monotone"
            dataKey="mgDl"
            stroke="#0F4C5C"
            strokeWidth={2.5}
            fill="url(#cadenceTeal)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
