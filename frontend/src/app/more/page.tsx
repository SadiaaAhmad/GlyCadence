"use client";

import React from "react";
import Link from "next/link";
import {
  ClipboardList,
  Dumbbell,
  HeartHandshake,
  Layers,
  Moon,
  Pill,
  Settings,
} from "lucide-react";

const MORE_ITEMS = [
  {
    href: "/exercise",
    title: "Exercise Routine (Mover)",
    desc: "Weekly 150-min aerobic & strength tracker + 15-min post-meal walks",
    icon: Dumbbell,
  },
  {
    href: "/medicines",
    title: "Medicines (Dose Diary)",
    desc: "Daily checklist, plain medicine guides, hypo flags, and refills",
    icon: Pill,
  },
  {
    href: "/wellbeing",
    title: "Wellbeing (Kindred)",
    desc: "20-second check-in, sleep & stress links, distress check, sick-day help",
    icon: HeartHandshake,
  },
  {
    href: "/fasting",
    title: "Ramadan & Fasting (Roza Guide)",
    desc: "IDF-DAR safety check, Suhoor & Iftar timing, and break-the-fast rules",
    icon: Moon,
  },
  {
    href: "/visit",
    title: "Doctor Visit (Visit Notes)",
    desc: "Personal questions for your clinician & printable 1-page visit summary",
    icon: ClipboardList,
  },
  {
    href: "/settings",
    title: "Preferences & Memory",
    desc: "Targets, food budget, What Cadie remembers, and Demo/Research tools",
    icon: Settings,
  },
  {
    href: "/architecture",
    title: "Agent Architecture (Presentation)",
    desc: "Visual overview of Cadie and her helpers for project review",
    icon: Layers,
  },
];

export default function MorePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl sm:text-3xl font-semibold">Care Tools &amp; Settings</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Everything you need for medicines, wellbeing, Ramadan fasting, and doctor visits.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {MORE_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="gc-card p-5 flex items-start gap-4 hover:border-[#FF4D4D] transition-colors"
            >
              <div className="h-11 w-11 rounded-2xl bg-[#F2A93B]/20 flex items-center justify-center shrink-0">
                <Icon className="h-5 w-5 text-[#FF4D4D]" />
              </div>
              <div>
                <h2 className="font-display text-lg font-semibold">{item.title}</h2>
                <p className="text-sm text-[var(--text-muted)] mt-0.5">{item.desc}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
