"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BrainCircuit,
  CalendarHeart,
  Layers,
  LayoutDashboard,
  Moon,
  Sun,
} from "lucide-react";
import { CadieLogo } from "@/components/layout/CadieLogo";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard", label: "Intelligence Dashboard", icon: BrainCircuit },
  { href: "/architecture", label: "Agent Architecture", icon: Layers },
  { href: "/tracking", label: "Daily Tracking", icon: Activity },
];

function DesktopNav() {
  const pathname = usePathname();
  return (
    <nav className="flex-1 space-y-1.5" aria-label="Primary navigation">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active =
          item.href === "/"
            ? pathname === "/"
            : pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-2xl px-3.5 py-2.5 text-sm font-medium transition-all duration-150",
              active
                ? "bg-[#0F4C5C] text-white shadow-sm"
                : "text-slate-700 hover:bg-slate-100/80 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800/80 dark:hover:text-white"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function MobileNav() {
  const pathname = usePathname();
  return (
    <nav
      className="mt-3 flex gap-1.5 overflow-x-auto pb-1 lg:hidden"
      aria-label="Mobile navigation"
    >
      {NAV_ITEMS.map((item) => {
        const active =
          item.href === "/"
            ? pathname === "/"
            : pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-medium transition-colors",
              active
                ? "bg-[#0F4C5C] text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("glycadence_theme");
    const prefersDark =
      saved === "dark" ||
      (!saved && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    setDark(prefersDark);
    document.documentElement.classList.toggle("dark", prefersDark);
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    window.localStorage.setItem("glycadence_theme", next ? "dark" : "light");
  };

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)] flex flex-col lg:flex-row">
      {/* Desktop Frosted Sidebar */}
      <aside className="hidden lg:flex lg:w-72 lg:flex-col lg:border-r lg:border-slate-200/70 lg:bg-white/80 lg:backdrop-blur-xl lg:px-5 lg:py-6 dark:lg:border-slate-800/80 dark:lg:bg-slate-950/75">
        <div className="px-2 mb-7">
          <CadieLogo />
        </div>

        <Suspense fallback={<div className="flex-1" />}>
          <DesktopNav />
        </Suspense>

        <div className="mt-6 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4 text-xs text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
          <div className="flex items-center gap-1.5 font-semibold text-[#0F4C5C] dark:text-teal-300 mb-1.5">
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
        {/* Frosted-Glass Top Bar */}
        <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/75 backdrop-blur-xl px-4 py-3.5 sm:px-6 dark:border-slate-800/80 dark:bg-slate-950/75">
          <div className="flex items-center justify-between gap-4 max-w-6xl mx-auto">
            <div className="flex items-center gap-3 lg:hidden">
              <CadieLogo />
            </div>
            <div className="hidden lg:flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
              <span className="font-semibold tracking-tight text-slate-900 dark:text-slate-100">
                Longitudinal Diabetes &amp; Wellbeing Intelligence
              </span>
            </div>
            <div className="flex items-center gap-2.5">
              <Badge variant="coral">CS325 Demo</Badge>
              <button
                type="button"
                onClick={toggleTheme}
                aria-label="Toggle light or dark appearance"
                className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/80 bg-white/80 text-slate-700 shadow-xs transition-all hover:scale-105 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <Suspense fallback={null}>
            <MobileNav />
          </Suspense>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10 max-w-6xl w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
