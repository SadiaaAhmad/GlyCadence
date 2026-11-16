"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BrainCircuit,
  Layers,
  LayoutDashboard,
  MessageSquareHeart,
  ShieldCheck,
} from "lucide-react";
import { CadieLogo } from "@/components/layout/CadieLogo";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/#care-team-chat", label: "Care Team Chat", icon: MessageSquareHeart },
  { href: "/#glucose-insights", label: "Insights", icon: BrainCircuit },
  { href: "/architecture", label: "Architecture", icon: Layers },
  { href: "/tracking", label: "Daily Tracking", icon: Activity },
];

function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex-1 space-y-1.5" aria-label="Primary navigation">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active =
          item.href === "/"
            ? pathname === "/" || pathname === "/dashboard"
            : pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all",
              active
                ? "bg-[#1E293B] text-white border border-slate-700/70 shadow-sm"
                : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100"
            )}
          >
            <Icon className={cn("h-4 w-4 shrink-0", active ? "text-[#FF4D4D]" : "text-slate-400")} />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0B101B] text-slate-100 flex flex-col lg:flex-row">
      {/* Desktop Dark-Navy Sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:shrink-0 lg:flex-col lg:border-r lg:border-slate-800/80 lg:bg-[#0F172A] lg:px-4 lg:py-6">
        <div className="px-2 mb-8">
          <CadieLogo />
          <p className="mt-1.5 text-[11px] text-slate-400">Your AI Diabetes Companion</p>
        </div>

        <Suspense fallback={<div className="flex-1" />}>
          <SidebarNav />
        </Suspense>

        <div className="mt-6 rounded-2xl border border-slate-700/60 bg-[#162032] p-3.5 text-xs text-slate-300">
          <div className="flex items-center gap-1.5 font-semibold text-emerald-400 mb-1">
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Safety Verifier Active</span>
          </div>
          <p className="leading-relaxed text-slate-400">
            Deterministic analytics compute every metric; the Verifier blocks ungrounded or causal claims.
          </p>
        </div>
      </aside>

      {/* Mobile Compact Header (hidden on lg+) */}
      <header className="lg:hidden sticky top-0 z-20 flex items-center justify-between border-b border-slate-800 bg-[#0F172A]/90 backdrop-blur-md px-4 py-3">
        <CadieLogo />
        <div className="flex items-center gap-2 text-xs">
          <Link href="/" className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-slate-200">
            Dashboard
          </Link>
          <Link href="/architecture" className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-slate-200">
            Architecture
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 min-w-0 px-4 py-6 sm:px-6 lg:px-8 max-w-[1440px] w-full mx-auto">
        {children}
      </main>
    </div>
  );
}
