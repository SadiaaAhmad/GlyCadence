"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BrainCircuit,
  CalendarHeart,
  FileText,
  LayoutDashboard,
  MessageCircleQuestion,
  UtensilsCrossed,
} from "lucide-react";
import { CadieLogo } from "@/components/layout/CadieLogo";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/tracking", label: "Daily Tracking", icon: Activity },
  { href: "/intelligence", label: "Intelligence Center", icon: BrainCircuit },
  { href: "/meals", label: "Meal Planner", icon: UtensilsCrossed },
  { href: "/doctor-prep", label: "Doctor Visit Prep", icon: FileText },
  { href: "/ask", label: "Ask GlyCadence", icon: MessageCircleQuestion },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-[#FFFDFB] text-slate-900 flex flex-col lg:flex-row">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:w-68 lg:flex-col lg:border-r lg:border-slate-200/80 lg:bg-white lg:px-4 lg:py-6">
        <div className="px-2 mb-6">
          <CadieLogo />
        </div>

        <nav className="flex-1 space-y-1" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-[#0F4C5C] text-white shadow-xs"
                    : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/80 p-3.5 text-xs text-slate-600">
          <div className="flex items-center gap-1.5 font-semibold text-[#0F4C5C] mb-1">
            <CalendarHeart className="h-3.5 w-3.5 text-[#FF4D4D]" />
            <span>Non-Diagnostic Companion</span>
          </div>
          <p className="leading-relaxed">
            GlyCadence surfaces patterns and discussion points for your clinician. It never diagnoses or changes medications.
          </p>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur-sm px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between gap-4 max-w-6xl mx-auto">
            <div className="flex items-center gap-3 lg:hidden">
              <CadieLogo />
            </div>
            <div className="hidden lg:flex items-center gap-2 text-sm text-slate-600">
              <span className="font-medium text-slate-900">Longitudinal Diabetes &amp; Wellbeing Intelligence</span>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="coral">Day 1 Foundation</Badge>
            </div>
          </div>

          {/* Mobile Horizontal Nav */}
          <nav
            className="mt-3 flex gap-1.5 overflow-x-auto pb-1 lg:hidden"
            aria-label="Mobile navigation"
          >
            {NAV_ITEMS.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "bg-[#0F4C5C] text-white"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8 max-w-6xl w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
