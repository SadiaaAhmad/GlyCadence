"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Home,
  LayoutGrid,
  MessageCircleHeart,
  Moon,
  Sun,
  UtensilsCrossed,
} from "lucide-react";
import { CadieLogo } from "@/components/layout/CadieLogo";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { cn } from "@/lib/utils";

const PRIMARY_TABS = [
  { href: "/", label: "Today", icon: Home },
  { href: "/ask", label: "Ask Cadie", icon: MessageCircleHeart },
  { href: "/glucose", label: "Glucose", icon: Activity },
  { href: "/meals", label: "Meals", icon: UtensilsCrossed },
  { href: "/more", label: "More", icon: LayoutGrid },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { activePatient, dark, toggleDark } = usePatientContext();

  const isTabActive = (href: string) => {
    if (href === "/") return pathname === "/" || pathname === "/dashboard";
    if (href === "/more") {
      return ["/more", "/medicines", "/wellbeing", "/visit", "/fasting", "/settings", "/architecture"].some((p) =>
        pathname.startsWith(p)
      );
    }
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-[var(--bg-page)] text-[var(--text-ink)]">
      {/* Desktop Left Navigation Rail */}
      <aside className="hidden lg:flex lg:w-64 lg:shrink-0 lg:flex-col lg:border-r lg:border-[var(--border-clay)] lg:bg-[var(--bg-card)] lg:px-4 lg:py-6">
        <div className="px-2 mb-7">
          <CadieLogo />
          <p className="mt-1 text-xs text-[var(--text-muted)]">Your daily diabetes companion</p>
        </div>

        <nav className="flex-1 space-y-1.5" aria-label="Primary navigation">
          {PRIMARY_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = isTabActive(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "flex items-center gap-3 rounded-[14px] px-3.5 py-2.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-[#2B1E2F] text-white dark:bg-[#F2A93B] dark:text-[#2B1E2F]"
                    : "text-[var(--text-ink)] hover:bg-[var(--bg-muted)]"
                )}
              >
                <Icon className={cn("h-4 w-4 shrink-0", active && "text-[#FF4D4D] dark:text-[#2B1E2F]")} />
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-6 space-y-3 border-t border-[var(--border-clay)] pt-4">
          {activePatient && (
            <Link
              href="/settings"
              className="block rounded-[14px] bg-[var(--bg-muted)] px-3.5 py-2.5 text-xs hover:opacity-90"
            >
              <div className="font-semibold truncate">{activePatient.display_name}</div>
              <div className="text-[var(--text-muted)] mt-0.5">Tap for preferences &amp; memory</div>
            </Link>
          )}
          <button
            type="button"
            onClick={toggleDark}
            className="w-full flex items-center justify-between rounded-[14px] border border-[var(--border-clay)] px-3.5 py-2 text-xs font-medium hover:bg-[var(--bg-muted)]"
          >
            <span>{dark ? "Warm Light Mode" : "Deep Plum Dark"}</span>
            {dark ? <Sun className="h-3.5 w-3.5 text-[#F2A93B]" /> : <Moon className="h-3.5 w-3.5" />}
          </button>
        </div>
      </aside>

      {/* Mobile Compact Header */}
      <header className="lg:hidden sticky top-0 z-20 flex items-center justify-between border-b border-[var(--border-clay)] bg-[var(--bg-card)]/90 backdrop-blur-md px-4 py-3">
        <CadieLogo />
        <button
          type="button"
          onClick={toggleDark}
          aria-label="Toggle theme"
          className="rounded-full border border-[var(--border-clay)] p-2"
        >
          {dark ? <Sun className="h-4 w-4 text-[#F2A93B]" /> : <Moon className="h-4 w-4" />}
        </button>
      </header>

      {/* Page Body */}
      <main className="flex-1 min-w-0 px-4 py-6 pb-24 lg:pb-8 sm:px-6 lg:px-8 max-w-5xl w-full mx-auto">
        {children}
      </main>

      {/* Mobile Bottom 5-Tab Bar */}
      <nav
        aria-label="Mobile bottom navigation"
        className="lg:hidden fixed bottom-0 inset-x-0 z-30 border-t border-[var(--border-clay)] bg-[var(--bg-card)]/95 backdrop-blur-md px-2 py-1.5 flex justify-around"
      >
        {PRIMARY_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = isTabActive(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "flex flex-col items-center gap-0.5 rounded-xl px-2.5 py-1 text-[11px] font-medium",
                active ? "text-[#FF4D4D]" : "text-[var(--text-muted)]"
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{tab.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
